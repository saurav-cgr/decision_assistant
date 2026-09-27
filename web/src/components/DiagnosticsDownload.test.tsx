import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, downloadDiagnosticsBundle } from "../api/client";
import { DiagnosticsDownload, saveBundleBlob } from "./DiagnosticsDownload";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  downloadDiagnosticsBundle: vi.fn(),
}));

const download = vi.mocked(downloadDiagnosticsBundle);

// jsdom does not implement the object-URL API, so the two methods the download path uses are
// installed per test and removed afterwards.
let createObjectURL: ReturnType<typeof vi.fn>;
let revokeObjectURL: ReturnType<typeof vi.fn>;

beforeEach(() => {
  createObjectURL = vi.fn(() => "blob:diagnostics");
  revokeObjectURL = vi.fn();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    writable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    writable: true,
    value: revokeObjectURL,
  });
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("saveBundleBlob", () => {
  it("hands the blob to the browser under the filename the server chose", () => {
    const clicked: HTMLAnchorElement[] = [];
    const createElement = document.createElement.bind(document);
    const spy = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = createElement(tag);
      if (tag === "a") {
        element.click = () => clicked.push(element as HTMLAnchorElement);
      }
      return element;
    });

    try {
      saveBundleBlob(new Blob(["zip-bytes"]), "decision-assistant-diagnostics-test.zip");
    } finally {
      spy.mockRestore();
    }

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("decision-assistant-diagnostics-test.zip");
    expect(clicked[0].getAttribute("href")).toBe("blob:diagnostics");
    // The anchor is not left in the document behind the click.
    expect(document.querySelectorAll("a")).toHaveLength(0);
  });

  it("revokes the object URL after the click, not during it", async () => {
    vi.useFakeTimers();
    const createElement = document.createElement.bind(document);
    const spy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tag: string) => createElement(tag));
    try {
      saveBundleBlob(new Blob(["zip-bytes"]), "bundle.zip");
      // Revoking in the same task as the click can cancel the download in some browsers.
      expect(revokeObjectURL).not.toHaveBeenCalled();
      vi.runAllTimers();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:diagnostics");
    } finally {
      spy.mockRestore();
    }
  });
});

describe("DiagnosticsDownload", () => {
  it("downloads the bundle and reports the filename", async () => {
    download.mockResolvedValue({
      blob: new Blob(["zip-bytes"]),
      filename: "decision-assistant-diagnostics-20260926T120000Z.zip",
    });
    const createElement = document.createElement.bind(document);
    const spy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tag: string) => createElement(tag));

    try {
      render(<DiagnosticsDownload />);
      await userEvent.click(
        screen.getByRole("button", { name: /download diagnostics bundle/i }),
      );

      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(
          "decision-assistant-diagnostics-20260926T120000Z.zip",
        ),
      );
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    } finally {
      spy.mockRestore();
    }
  });

  it("disables the button while the bundle is being prepared", async () => {
    let resolve: (value: { blob: Blob; filename: string }) => void = () => {};
    download.mockReturnValue(
      new Promise((settle) => {
        resolve = settle;
      }),
    );
    const createElement = document.createElement.bind(document);
    const spy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tag: string) => createElement(tag));

    try {
      render(<DiagnosticsDownload />);
      await userEvent.click(
        screen.getByRole("button", { name: /download diagnostics bundle/i }),
      );

      const pendingButton = screen.getByRole("button", { name: /preparing bundle/i });
      expect(pendingButton).toBeDisabled();

      resolve({ blob: new Blob(["zip-bytes"]), filename: "bundle.zip" });
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: /download diagnostics bundle/i }),
        ).toBeEnabled(),
      );
    } finally {
      spy.mockRestore();
    }
  });

  it("shows the API's message and re-enables the button when the download fails", async () => {
    download.mockRejectedValue(
      new ApiClientError(401, {
        code: "invalid_credentials",
        message: "Not authenticated",
        request_id: "test",
        retryable: false,
        details: null,
      }),
    );

    render(<DiagnosticsDownload />);
    await userEvent.click(
      screen.getByRole("button", { name: /download diagnostics bundle/i }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Not authenticated");
    expect(
      screen.getByRole("button", { name: /download diagnostics bundle/i }),
    ).toBeEnabled();
    expect(createObjectURL).not.toHaveBeenCalled();
  });
});
