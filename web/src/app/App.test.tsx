import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

it("renders all primary navigation destinations", async () => {
  const appModule = "./App";
  const { App } = await import(/* @vite-ignore */ appModule);

  render(<App />);

  const destinations = {
    Workspace: "/",
    Ask: "/ask",
    Timeline: "/timeline",
    Evaluation: "/evaluation",
  };
  for (const [label, path] of Object.entries(destinations)) {
    expect(screen.getByRole("link", { name: label })).toHaveAttribute(
      "href",
      path,
    );
  }
});
