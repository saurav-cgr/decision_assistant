import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
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

  it("posts stateless decision analyses with decimal strings", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ranked_options: [] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const clientModule = "./client";
    const { analyzeDecision } = await import(/* @vite-ignore */ clientModule);

    await analyzeDecision({
      title: "Choose hosting",
      options: [
        { id: "managed", label: "Managed" },
        { id: "self_hosted", label: "Self-hosted" },
      ],
      criteria: [
        {
          id: "cost",
          label: "Cost",
          direction: "cost",
          weight: "1.0",
          scale: "numeric",
        },
      ],
      scores: [
        {
          option_id: "managed",
          criterion_id: "cost",
          value: "100",
          provenance: "user_provided",
        },
        {
          option_id: "self_hosted",
          criterion_id: "cost",
          value: "40",
          provenance: "derived",
          rationale: "Capacity estimate",
        },
      ],
      narrative_requested: false,
    });

    const [requestedUrl, init] = fetchMock.mock.calls[0];
    expect(String(requestedUrl)).toMatch(/\/api\/v1\/decision-analyses$/);
    expect(init).toMatchObject({ method: "POST" });
    const body = JSON.parse(String(init.body));
    expect(body.criteria[0].weight).toBe("1.0");
    expect(body.scores[0].value).toBe("100");
    expect(body.scores[1]).toMatchObject({
      value: "40",
      provenance: "derived",
      rationale: "Capacity estimate",
    });
  });
});
