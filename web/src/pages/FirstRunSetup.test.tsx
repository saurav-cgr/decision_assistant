/**
 * T044 (US5): the first-run "create password" screen.
 *
 * What these tests pin down is the two-step contract and the gate's failure direction:
 *   - the form creates the password, then shows the recovery code *before* entering the app
 *   - a second submit that the server refuses (409) surfaces the server's message, not a blank screen
 *   - the local mismatch check happens before any request
 *   - when the status probe fails, the shell falls back to the sign-in form instead of locking the
 *     operator out of an install that already has a user (the DB59 decision's "first-run flow, not
 *     access control" made concrete)
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../app/App";
import { setAccessToken } from "../api/client";

const SETUP_STATUS_URL = "/api/v1/setup/status";
const SETUP_PASSWORD_URL = "/api/v1/setup/password";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mockFetch(handler: (url: string, init?: RequestInit) => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      return Promise.resolve(handler(url, init));
    }),
  );
}

beforeEach(() => {
  setAccessToken(null);
  vi.unstubAllGlobals();
});

// `App` brings its own `BrowserRouter`, so these render it directly — wrapping it in a
// `MemoryRouter` is what a first attempt did, and React Router throws on a nested router (the
// error boundary then renders "Something interrupted this view" and hides the real failure).
function renderApp() {
  return render(<App />);
}

describe("first-run setup screen", () => {
  it("asks for the password when the install has no user, and keeps the sign-in form away", async () => {
    mockFetch((url) => {
      if (url.includes(SETUP_STATUS_URL)) {
        return jsonResponse({ needs_password_setup: true, needs_provider_disclosure: true });
      }
      return jsonResponse({ detail: "unexpected" }, 404);
    });

    renderApp();

    expect(await screen.findByRole("heading", { name: /set up this install/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /sign in/i })).not.toBeInTheDocument();
  });

  it("shows the recovery code before entering the app, and only then continues", async () => {
    const user = userEvent.setup();
    let posted: unknown = null;
    mockFetch((url, init) => {
      if (url.includes(SETUP_STATUS_URL)) {
        return jsonResponse({ needs_password_setup: true, needs_provider_disclosure: true });
      }
      if (url.includes(SETUP_PASSWORD_URL)) {
        posted = JSON.parse(String(init?.body ?? "{}"));
        return jsonResponse({
          access_token: "setup-token",
          token_type: "bearer",
          user: { id: "u1", username: "decision_assistant" },
          recovery_code: "RECOVERY-CODE-123",
        });
      }
      return jsonResponse({ detail: "unexpected" }, 404);
    });

    renderApp();

    await user.type(await screen.findByLabelText(/new password/i), "a-first-run-password");
    await user.type(screen.getByLabelText(/repeat password/i), "a-first-run-password");
    await user.click(screen.getByRole("button", { name: /set password and continue/i }));

    // The code is on screen and the app has not been entered yet: the recovery code is the only way
    // back in if the password is forgotten, and the API returns it exactly once.
    expect(await screen.findByText("RECOVERY-CODE-123")).toBeInTheDocument();
    expect(posted).toEqual({ password: "a-first-run-password" });
    expect(screen.getByRole("button", { name: /i saved my recovery code/i })).toBeInTheDocument();
    // Still the setup screen — entering the app happens on the next click, not automatically.
    expect(screen.queryByRole("heading", { name: /sign in/i })).not.toBeInTheDocument();
  });

  it("surfaces the server's refusal when a password already exists", async () => {
    const user = userEvent.setup();
    mockFetch((url) => {
      if (url.includes(SETUP_STATUS_URL)) {
        return jsonResponse({ needs_password_setup: true, needs_provider_disclosure: true });
      }
      return jsonResponse(
        {
          code: "password_already_set_up",
          message: "A password has already been set up for this install",
          request_id: "r1",
          retryable: false,
        },
        409,
      );
    });

    renderApp();

    await user.type(await screen.findByLabelText(/new password/i), "a-first-run-password");
    await user.type(screen.getByLabelText(/repeat password/i), "a-first-run-password");
    await user.click(screen.getByRole("button", { name: /set password and continue/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/already been set up/i);
  });

  it("checks the two passwords locally before spending a request", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes(SETUP_STATUS_URL)) {
        return Promise.resolve(
          jsonResponse({ needs_password_setup: true, needs_provider_disclosure: true }),
        );
      }
      return Promise.resolve(jsonResponse({ detail: "unexpected" }, 404));
    });
    vi.stubGlobal("fetch", fetchSpy);

    renderApp();

    await user.type(await screen.findByLabelText(/new password/i), "a-first-run-password");
    await user.type(screen.getByLabelText(/repeat password/i), "a-different-password");
    await user.click(screen.getByRole("button", { name: /set password and continue/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/do not match/i);
    await waitFor(() =>
      expect(fetchSpy.mock.calls.some((call) => String(call[0]).includes(SETUP_PASSWORD_URL))).toBe(
        false,
      ),
    );
  });

  it("falls back to the sign-in form when the status probe fails", async () => {
    // An install that already has a user must stay reachable when this probe cannot run; that is why
    // the gate treats "unknown" as "sign in" rather than "blocked".
    mockFetch(() => jsonResponse({ detail: "service unavailable" }, 503));

    renderApp();

    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
  });
});
