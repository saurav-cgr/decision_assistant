import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ analyzeDecision: vi.fn() }));

vi.mock("../api/client", () => ({ analyzeDecision: api.analyzeDecision }));

async function renderPage() {
  const modulePath = "./DecisionAnalysis";
  const { DecisionAnalysis } = await import(/* @vite-ignore */ modulePath);
  return render(<DecisionAnalysis />);
}

async function fillValidForm() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/decision title/i), "Choose hosting");
  await user.type(screen.getByLabelText("Option 1 label"), "Managed");
  await user.type(screen.getByLabelText("Option 2 label"), "Self-hosted");
  await user.type(screen.getByLabelText("Criterion 1 label"), "Cost");
  await user.type(screen.getByLabelText("Criterion 2 label"), "Quality");
  await user.type(screen.getByLabelText("Managed Cost score"), "100");
  await user.type(screen.getByLabelText("Managed Quality score"), "8");
  await user.type(screen.getByLabelText("Self-hosted Cost score"), "40");
  await user.type(screen.getByLabelText("Self-hosted Quality score"), "6");
  return user;
}

beforeEach(() => api.analyzeDecision.mockReset());
afterEach(() => vi.clearAllMocks());

describe("DecisionAnalysis", () => {
  it("requires complete inputs, then posts a server-authoritative analysis", async () => {
    api.analyzeDecision.mockResolvedValue({});
    await renderPage();

    expect(screen.getByRole("button", { name: /analyze decision/i })).toBeDisabled();
    await fillValidForm();
    const submit = screen.getByRole("button", { name: /analyze decision/i });
    expect(submit).toBeEnabled();

    await userEvent.setup().click(submit);

    await waitFor(() => expect(api.analyzeDecision).toHaveBeenCalledTimes(1));
    expect(api.analyzeDecision).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Choose hosting",
        criteria: expect.arrayContaining([
          expect.objectContaining({ weight: "0.5" }),
        ]),
        scores: expect.arrayContaining([
          expect.objectContaining({ value: "100", provenance: "user_provided" }),
        ]),
      }),
    );
    expect(await screen.findByText(/analysis calculated/i)).toBeVisible();
  });

});
