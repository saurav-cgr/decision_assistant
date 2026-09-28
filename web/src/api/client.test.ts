import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("diagnostics bundle download", () => {
  it("sends the bearer token and uses the filename from the download headers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("zip-bytes", {
        status: 200,
        headers: {
          "content-type": "application/zip",
          "content-disposition":
            'attachment; filename="decision-assistant-diagnostics-20260926T120000Z.zip"',
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { downloadDiagnosticsBundle, setAccessToken } = await import(
      /* @vite-ignore */ "./client"
    );
    setAccessToken("token-123");

    const bundle = await downloadDiagnosticsBundle();

    const [requestedUrl, init] = fetchMock.mock.calls[0];
    expect(String(requestedUrl)).toMatch(/\/api\/v1\/diagnostics\/bundle$/);
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("authorization")).toBe("Bearer token-123");
    expect(bundle.filename).toBe("decision-assistant-diagnostics-20260926T120000Z.zip");
    // The body is asserted by size: jsdom's Blob has no `text()`, and a Blob *body* is stringified
    // by jsdom's Response (hence the raw string above).
    expect(bundle.blob.size).toBe("zip-bytes".length);
  });

  it("falls back to a stable filename when the header is missing or malformed", async () => {
    for (const disposition of [null, "attachment;", "inline"]) {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response("zip-bytes", {
          status: 200,
          headers: disposition ? { "content-disposition": disposition } : {},
        }),
      );
      vi.stubGlobal("fetch", fetchMock);
      const { downloadDiagnosticsBundle } = await import(
        /* @vite-ignore */ "./client"
      );

      const bundle = await downloadDiagnosticsBundle();

      expect(bundle.filename).toBe("decision-assistant-diagnostics.zip");
    }
  });

  it("surfaces an API error when the bundle cannot be fetched", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "invalid_credentials",
          message: "Not authenticated",
          request_id: "request-401",
          retryable: false,
          details: null,
        }),
        { status: 401, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { ApiClientError, downloadDiagnosticsBundle } = await import(
      /* @vite-ignore */ "./client"
    );

    await expect(downloadDiagnosticsBundle()).rejects.toMatchObject({
      code: "invalid_credentials",
      status: 401,
      requestId: "request-401",
    });
    await expect(downloadDiagnosticsBundle()).rejects.toBeInstanceOf(ApiClientError);
  });
});

describe("Decision Assistant API client", () => {
  it("lists documents through the versioned business API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const clientModule = "./client";
    const { listDocuments, setActiveWorkspaceId } = await import(
      /* @vite-ignore */ clientModule
    );
    setActiveWorkspaceId("workspace-1");

    await listDocuments();

    const [requestedUrl] = fetchMock.mock.calls[0];
    expect(String(requestedUrl)).toMatch(
      /\/api\/v1\/workspaces\/workspace-1\/documents$/,
    );
  });

  it("preserves the stable API error and request ID", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "retry_not_available",
          message: "No failed ingestion to retry",
          request_id: "request-123",
          retryable: false,
          details: { document_id: "document-1" },
        }),
        {
          status: 409,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const clientModule = "./client";
    const { listDocuments, setActiveWorkspaceId } = await import(
      /* @vite-ignore */ clientModule
    );
    setActiveWorkspaceId("workspace-1");

    await expect(listDocuments()).rejects.toMatchObject({
      name: "ApiClientError",
      status: 409,
      code: "retry_not_available",
      message: "No failed ingestion to retry",
      requestId: "request-123",
      retryable: false,
      details: { document_id: "document-1" },
    });
  });

  it("sends refresh intent and paginated question-history search", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const clientModule = "./client";
    const { answerQuestion, listQuestionHistory, setActiveWorkspaceId } =
      await import(/* @vite-ignore */ clientModule);
    setActiveWorkspaceId("workspace-1");

    await answerQuestion("Why authentication?", true);
    await listQuestionHistory("authentication owner", 2, 5);

    const [, answerInit] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(answerInit.body))).toEqual({
      question: "Why authentication?",
      force_refresh: true,
    });
    const [historyUrl] = fetchMock.mock.calls[1];
    expect(String(historyUrl)).toContain(
      "/questions/history?page=2&page_size=5&query=authentication+owner",
    );
  });

  it("adds the in-memory bearer token to protected requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const clientModule = "./client";
    const { listWorkspaces, setAccessToken } = await import(
      /* @vite-ignore */ clientModule
    );
    setAccessToken("access-token");

    await listWorkspaces();

    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init.headers).get("authorization")).toBe(
      "Bearer access-token",
    );
    setAccessToken(null);
  });

  it("adds the in-memory bearer token to document uploads", async () => {
    const loadListeners: Array<() => void> = [];
    const xhr = {
      upload: { addEventListener: vi.fn() },
      open: vi.fn(),
      setRequestHeader: vi.fn(),
      addEventListener: vi.fn((event: string, listener: () => void) => {
        if (event === "load") loadListeners.push(listener);
      }),
      send: vi.fn(() => loadListeners[0]?.()),
      status: 202,
      responseText: JSON.stringify({ request_id: "upload", results: [] }),
    };
    vi.stubGlobal("XMLHttpRequest", vi.fn(() => xhr));
    const clientModule = "./client";
    const { setAccessToken, setActiveWorkspaceId, uploadDocuments } = await import(
      /* @vite-ignore */ clientModule
    );
    setAccessToken("access-token");
    setActiveWorkspaceId("workspace-1");

    await uploadDocuments([new File(["content"], "meeting.md")], vi.fn());

    expect(xhr.setRequestHeader).toHaveBeenCalledWith(
      "authorization",
      "Bearer access-token",
    );
    setAccessToken(null);
  });
});
