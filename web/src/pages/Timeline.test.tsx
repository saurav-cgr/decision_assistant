import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getTimeline: vi.fn(),
}));

vi.mock("../api/client", () => ({
  documentDetailUrl: (documentId: string) =>
    `http://localhost:8000/api/v1/documents/${documentId}`,
  getTimeline: api.getTimeline,
}));

const proposedId = "11111111-1111-4111-8111-111111111111";
const acceptedId = "22222222-2222-4222-8222-222222222222";
const revisedId = "33333333-3333-4333-8333-333333333333";

const timeline = {
  topic: "Authentication",
  entries: [
    {
      decision_id: proposedId,
      statement: "Authentication postponement was proposed.",
      effective_date: "2026-07-10",
      display_date: "2026-07-10",
      date_is_fallback: false,
      original_status: "proposed",
      display_status: "proposed",
      owner: "Maya",
      project: "Atlas",
      topic: "Authentication",
      provenance: "extracted",
      evidence: [
        {
          passage_id: "44444444-4444-4444-8444-444444444444",
          document_id: "document-1",
          document_version_id: "55555555-5555-4555-8555-555555555555",
          quote: "Authentication postponement was proposed.",
          start_offset: 0,
          end_offset: 44,
          content_hash: "a".repeat(64),
          locator: { kind: "lines", start: 4, end: 4 },
        },
      ],
      relationships: [],
    },
    {
      decision_id: acceptedId,
      statement: "Authentication postponement was accepted.",
      effective_date: null,
      display_date: "2026-07-15",
      date_is_fallback: true,
      original_status: "active",
      display_status: "active",
      owner: "Maya",
      project: "Atlas",
      topic: "Authentication",
      provenance: "extracted",
      evidence: [
        {
          passage_id: "66666666-6666-4666-8666-666666666666",
          document_id: "document-2",
          document_version_id: "77777777-7777-4777-8777-777777777777",
          quote: "Authentication postponement was accepted.",
          start_offset: 0,
          end_offset: 44,
          content_hash: "b".repeat(64),
          locator: { kind: "pdf_page", page: 2 },
        },
      ],
      relationships: [
        {
          source_decision_id: acceptedId,
          target_decision_id: proposedId,
          relation_type: "supersedes",
          label: "supersedes",
          authority: "user_confirmed",
          confidence: null,
          rationale: "Team confirmed acceptance.",
        },
      ],
    },
    {
      decision_id: revisedId,
      statement: "Authentication may return to the Q3 release.",
      effective_date: "2026-07-20",
      display_date: "2026-07-20",
      date_is_fallback: false,
      original_status: "proposed",
      display_status: "superseded",
      owner: "Ravi",
      project: "Atlas",
      topic: "Authentication",
      provenance: "extracted",
      evidence: [
        {
          passage_id: "88888888-8888-4888-8888-888888888888",
          document_id: "document-3",
          document_version_id: "99999999-9999-4999-8999-999999999999",
          quote: "Authentication may return to the Q3 release.",
          start_offset: 0,
          end_offset: 45,
          content_hash: "c".repeat(64),
          locator: { kind: "lines", start: 9, end: 10 },
        },
      ],
      relationships: [
        {
          source_decision_id: revisedId,
          target_decision_id: acceptedId,
          relation_type: "revises",
          label: "possible_revision",
          authority: "model_inferred",
          confidence: "low",
          rationale: "Topic and timing suggest a revision.",
        },
      ],
    },
  ],
};

async function renderTimeline() {
  const modulePath = "./Timeline";
  const { Timeline } = await import(/* @vite-ignore */ modulePath);
  return render(<Timeline />);
}

async function buildTimeline() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/timeline topic/i), "Authentication");
  await user.click(screen.getByRole("button", { name: /build timeline/i }));
}

beforeEach(() => {
  api.getTimeline.mockReset().mockResolvedValue(timeline);
});

describe("Decision timeline", () => {
  it("renders authoritative events chronologically with status and evidence links", async () => {
    await renderTimeline();
    await buildTimeline();

    expect(api.getTimeline).toHaveBeenCalledWith("Authentication");
    const orderedTimeline = await screen.findByRole("list", {
      name: /decision timeline/i,
    });
    expect(orderedTimeline.tagName).toBe("OL");
    const events = within(orderedTimeline).getAllByRole("article");
    expect(events).toHaveLength(3);
    expect(events[0]).toHaveTextContent("2026-07-10");
    expect(events[0]).toHaveTextContent("Proposed");
    expect(events[1]).toHaveTextContent("2026-07-15");
    expect(events[1]).toHaveTextContent("Active");
    expect(events[1]).toHaveTextContent(/document date/i);
    expect(events[2]).toHaveTextContent("2026-07-20");
    expect(events[2]).toHaveTextContent("Superseded");

    const evidenceLinks = within(orderedTimeline).getAllByRole("link", {
      name: /view source evidence/i,
    });
    expect(evidenceLinks).toHaveLength(3);
    expect(evidenceLinks[0]).toHaveAttribute(
      "href",
      "http://localhost:8000/api/v1/documents/document-1",
    );
    expect(evidenceLinks[1]).toHaveAttribute(
      "href",
      "http://localhost:8000/api/v1/documents/document-2",
    );
    expect(evidenceLinks[2]).toHaveAttribute(
      "href",
      "http://localhost:8000/api/v1/documents/document-3",
    );
  });

  it("labels model-inferred revision candidates as possible", async () => {
    await renderTimeline();
    await buildTimeline();

    const orderedTimeline = await screen.findByRole("list", {
      name: /decision timeline/i,
    });
    expect(within(orderedTimeline).getByText("Possible revision")).toBeVisible();
    expect(within(orderedTimeline).getByText(/low confidence/i)).toBeVisible();
  });
});
