import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

it("renders the sign-in screen before a user authenticates", async () => {
  const appModule = "./App";
  const { App } = await import(/* @vite-ignore */ appModule);

  render(<App />);

  expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
});

it("offers a sign-up and recovery flow", async () => {
  const user = userEvent.setup();
  const appModule = "./App";
  const { App } = await import(/* @vite-ignore */ appModule);

  render(<App />);
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(screen.getByRole("heading", { name: "Create account" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Forgot username" }));
  expect(screen.getByRole("heading", { name: "Recover access" })).toBeInTheDocument();
  expect(screen.getByLabelText("Recovery code")).toBeInTheDocument();
});
