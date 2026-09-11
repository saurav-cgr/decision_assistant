import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ appendConversationMessage: vi.fn(), createConversation: vi.fn(), getConversation: vi.fn(), getDocument: vi.fn(), getRetrievalTrace: vi.fn(), listConversations: vi.fn() }));
vi.mock("../api/client", () => api);

const response = { answer: "Priya changed authentication.", state: "answered", confidence: "high", claims: [], citations: [], conflicts: [], unsupported_facets: [], trace_id: "33333333-3333-4333-8333-333333333333" };
const summary = { id: "44444444-4444-4444-8444-444444444444", title: "Who changed authentication?", created_at: "2026-08-16T10:00:00Z", updated_at: "2026-08-16T10:00:00Z" };
const detail = { ...summary, messages: [{ id: "55555555-5555-4555-8555-555555555555", turn_number: 1, question: summary.title, response, answered_at: summary.created_at, stale: false }] };

async function renderAsk() { const { Ask } = await import("./Ask"); return render(<Ask />); }

beforeEach(() => { Object.values(api).forEach((mock) => mock.mockReset()); api.listConversations.mockResolvedValue([summary]); api.getConversation.mockResolvedValue(detail); });

describe("Ask", () => {
  it("resumes the newest saved conversation", async () => {
    await renderAsk();
    expect(await screen.findByText("Priya changed authentication.")).toBeVisible();
    expect(api.getConversation).toHaveBeenCalledWith(summary.id);
    expect(screen.getByRole("button", { name: new RegExp(summary.title) })).toHaveAttribute("aria-current", "page");
  });

  it("appends a follow-up to the selected conversation", async () => {
    const user = userEvent.setup();
    api.appendConversationMessage.mockResolvedValue({ id: "66666666-6666-4666-8666-666666666666", turn_number: 2, question: "Why did this get changed?", response, answered_at: summary.updated_at, stale: false });
    await renderAsk();
    await screen.findByText("Priya changed authentication.");
    await user.type(screen.getByLabelText(/ask a follow-up/i), "Why did this get changed?");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));
    await waitFor(() => expect(api.appendConversationMessage).toHaveBeenCalledWith(summary.id, "Why did this get changed?"));
    expect(screen.getAllByText("Why did this get changed?")).toHaveLength(1);
  });

  it("starts a new persisted conversation", async () => {
    const user = userEvent.setup();
    api.listConversations.mockResolvedValue([]);
    api.createConversation.mockResolvedValue(detail);
    await renderAsk();
    await user.type(screen.getByLabelText(/start a conversation/i), summary.title);
    await user.click(screen.getByRole("button", { name: /^ask$/i }));
    await waitFor(() => expect(api.createConversation).toHaveBeenCalledWith(summary.title));
    expect(await screen.findByText("Priya changed authentication.")).toBeVisible();
  });
});
