import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  correctDecision: vi.fn(),
  createDecisionRelation: vi.fn(),
  getDecision: vi.fn(),
  listDecisions: vi.fn(),
}));

vi.mock("../api/client", () => ({
  correctDecision: api.correctDecision,
  createDecisionRelation: api.createDecisionRelation,
  getDecision: api.getDecision,
  listDecisions: api.listDecisions,
}));

const decisionId = "11111111-1111-4111-8111-111111111111";
const targetDecisionId = "22222222-2222-4222-8222-222222222222";
const passageId = "33333333-3333-4333-8333-333333333333";
const sourceQuote =
  "Authentication was postponed because billing had launch priority.";

const detail = {
  id: decisionId,
  document_version_id: "44444444-4444-4444-8444-444444444444",
  statement: "Postpone authentication until Q4.",
  effective_date: "2026-07-15",
  owner: "Maya",
  status: "active",
  reasons: ["Billing had launch priority"],
  alternatives: ["Ship limited authentication"],
  project: "Atlas",
  topic: "Authentication",
  extraction_confidence: 0.91,
  provenance: "extracted",
  review_state: "supported",
  user_edited: false,
  retired: false,
  evidence: [
    {
      passage_id: passageId,
      field_name: "statement",
      quote: sourceQuote,
      start_offset: 0,
      end_offset: sourceQuote.length,
      content_hash: "a".repeat(64),
      support_state: "supported",
      is_primary: true,
    },
  ],
  revisions: [
    {
      id: "55555555-5555-4555-8555-555555555555",
      field_name: "owner",
      old_value: "Unassigned",
      new_value: "Maya",
      evidence_passage_ids: [passageId],
      support_state: "supported",
    },
  ],
  relations: [
    {
      id: "66666666-6666-4666-8666-666666666666",
      source_decision_id: decisionId,
      target_decision_id: targetDecisionId,
      relation_type: "revises",
      authority: "user_confirmed",
      confidence: null,
      rationale: "Team confirmed this during review.",
    },
  ],
};

const targetDecision = {
  ...detail,
  id: targetDecisionId,
  statement: "Ship authentication in Q3.",
  evidence: undefined,
  revisions: undefined,
  relations: undefined,
};

async function renderDecisionDetail() {
  const modulePath = "./DecisionDetail";
  const { DecisionDetail } = await import(/* @vite-ignore */ modulePath);
  return render(
    <MemoryRouter initialEntries={[`/decisions/${decisionId}`]}>
      <Routes>
        <Route path="/decisions/:id" element={<DecisionDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  api.correctDecision.mockReset();
  api.createDecisionRelation.mockReset();
  api.getDecision.mockReset().mockResolvedValue(detail);
  api.listDecisions.mockReset().mockResolvedValue({ items: [detail, targetDecision] });
});

describe("Decision detail", () => {
  it("keeps source evidence immutable and shows revision history", async () => {
    await renderDecisionDetail();

    expect(await screen.findByText(sourceQuote)).toBeVisible();
    expect(screen.queryByDisplayValue(sourceQuote)).not.toBeInTheDocument();
    const revisions = screen.getByRole("list", { name: /revision history/i });
    expect(revisions).toHaveTextContent("owner");
    expect(revisions).toHaveTextContent("Unassigned → Maya");
    expect(revisions).toHaveTextContent(/supported/i);
  });

  it("saves a supported correction with selected evidence", async () => {
    api.correctDecision.mockResolvedValue({ ...detail, owner: "Ravi" });
    const user = userEvent.setup();
    await renderDecisionDetail();
    await screen.findByText(sourceQuote);

    await user.selectOptions(screen.getByLabelText(/field to correct/i), "owner");
    await user.clear(screen.getByLabelText(/new value/i));
    await user.type(screen.getByLabelText(/new value/i), "Ravi");
    await user.click(
      screen.getByLabelText(/^supported by source evidence$/i),
    );
    await user.click(screen.getByLabelText(`Use evidence: ${sourceQuote}`));
    await user.click(screen.getByRole("button", { name: /save correction/i }));

    await waitFor(() =>
      expect(api.correctDecision).toHaveBeenCalledWith(decisionId, {
        changes: [
          {
            field_name: "owner",
            value: "Ravi",
            support_state: "supported",
            evidence: [
              {
                passage_id: passageId,
                start_offset: 0,
                end_offset: sourceQuote.length,
                content_hash: "a".repeat(64),
              },
            ],
          },
        ],
      }),
    );
  });

  it("requires explicit confirmation before an unsupported correction", async () => {
    api.correctDecision.mockResolvedValue({ ...detail, owner: "Unknown approver" });
    const user = userEvent.setup();
    await renderDecisionDetail();
    await screen.findByText(sourceQuote);

    await user.selectOptions(screen.getByLabelText(/field to correct/i), "owner");
    await user.clear(screen.getByLabelText(/new value/i));
    await user.type(screen.getByLabelText(/new value/i), "Unknown approver");
    await user.click(
      screen.getByLabelText(/^not supported by source evidence$/i),
    );
    await user.click(screen.getByRole("button", { name: /save correction/i }));

    expect(api.correctDecision).not.toHaveBeenCalled();
    const warning = screen.getByRole("alert");
    expect(warning).toHaveTextContent(/stored as unsupported/i);

    await user.click(
      screen.getByRole("button", { name: /confirm unsupported correction/i }),
    );
    await waitFor(() =>
      expect(api.correctDecision).toHaveBeenCalledWith(decisionId, {
        changes: [
          {
            field_name: "owner",
            value: "Unknown approver",
            support_state: "unsupported",
            evidence: [],
          },
        ],
      }),
    );
  });

  it("creates and labels a team-confirmed relationship", async () => {
    api.createDecisionRelation.mockResolvedValue({
      id: "77777777-7777-4777-8777-777777777777",
      source_decision_id: decisionId,
      target_decision_id: targetDecisionId,
      relation_type: "supersedes",
      authority: "user_confirmed",
      confidence: null,
      rationale: "Approved during architecture review.",
    });
    const user = userEvent.setup();
    await renderDecisionDetail();
    await screen.findByText(sourceQuote);

    const form = screen.getByRole("form", { name: /confirm decision relationship/i });
    await user.selectOptions(
      within(form).getByLabelText(/target decision/i),
      targetDecisionId,
    );
    await user.selectOptions(within(form).getByLabelText(/relationship type/i), "supersedes");
    await user.type(
      within(form).getByLabelText(/rationale/i),
      "Approved during architecture review.",
    );
    await user.click(within(form).getByRole("button", { name: /confirm relationship/i }));

    await waitFor(() =>
      expect(api.createDecisionRelation).toHaveBeenCalledWith(decisionId, {
        target_decision_id: targetDecisionId,
        relation_type: "supersedes",
        rationale: "Approved during architecture review.",
      }),
    );
    expect(screen.getByText(/team-confirmed relationships/i)).toBeVisible();
  });
});
