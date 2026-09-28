import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// T044: the shell now asks the server whether this install has a user before deciding between the
// create-password screen and the sign-in form, so these tests have to answer that probe. They are
// about the sign-in form, so the answer is "setup is not needed".
function stubSetupStatus(needsPasswordSetup: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/v1/setup/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ needs_password_setup: needsPasswordSetup }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
      }
      return Promise.resolve(new Response(null, { status: 204 }));
    }),
  );
}

beforeEach(() => {
  stubSetupStatus(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("renders the sign-in screen before a user authenticates", async () => {
  const appModule = "./App";
  const { App } = await import(/* @vite-ignore */ appModule);

  render(<App />);

  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
});

it("offers a sign-up and recovery flow", async () => {
  const user = userEvent.setup();
  const appModule = "./App";
  const { App } = await import(/* @vite-ignore */ appModule);

  render(<App />);
  await user.click(await screen.findByRole("button", { name: "Create account" }));
  expect(screen.getByRole("heading", { name: "Create account" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Forgot username" }));
  expect(screen.getByRole("heading", { name: "Recover access" })).toBeInTheDocument();
  expect(screen.getByLabelText("Recovery code")).toBeInTheDocument();
});
