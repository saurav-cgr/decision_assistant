import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  answerQuestion: vi.fn(),
  getRetrievalTrace: vi.fn(),
}));

vi.mock("../api/client", () => ({
  answerQuestion: api.answerQuestion,
  documentDetailUrl: (documentId: string) =>
    `http://localhost:8000/api/v1/documents/${documentId}`,
  getRetrievalTrace: api.getRetrievalTrace,
}));

const passageOne = "11111111-1111-4111-8111-111111111111";
const passageTwo = "22222222-2222-4222-8222-222222222222";
const traceId = "33333333-3333-4333-8333-333333333333";

const firstCitation = {
  passage_id: passageOne,
  quote: "Authentication was postponed until Q4 because billing was the launch priority.",
  start_offset: 0,
  end_offset: 78,
  content_hash: "a".repeat(64),
  document_id: "document-1",
  document_name: "architecture-review.md",
  locator: { kind: "lines", start: 12, end: 14 },
};

const secondCitation = {
  passage_id: passageTwo,
  quote: "The team later moved authentication back into the Q3 release.",
  start_offset: 0,
  end_offset: 61,
  content_hash: "b".repeat(64),
  document_id: "document-2",
  document_name: "release-planning.md",
  locator: { kind: "lines", start: 8, end: 9 },
};

function response(overrides: Record<string, unknown> = {}) {
  return {
    answer: "Authentication was postponed until Q4, with Priya owning the decision.",
    state: "answered",
    confidence: "high",
    claims: [
      {
        text: "Authentication was postponed until Q4.",
        central: true,
        passage_ids: [passageOne],
        explicit_entities: [],
        explicit_dates: ["Q4"],
      },
      {
        text: "Priya owned the decision.",
        central: false,
        passage_ids: [passageOne],
        explicit_entities: ["Priya"],
        explicit_dates: [],
      },
    ],
    citations: [firstCitation],
    conflicts: [],
    unsupported_facets: [],
    trace_id: traceId,
    ...overrides,
  };
}

async function renderAsk() {
  const modulePath = "./Ask";
  const { Ask } = await import(/* @vite-ignore */ modulePath);
  return render(<Ask />);
}

async function ask(question = "Why was authentication postponed?") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/ask about project decisions/i), question);
  await user.click(screen.getByRole("button", { name: /^ask$/i }));
}

beforeEach(() => {
  api.answerQuestion.mockReset();
  api.getRetrievalTrace.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("Ask", () => {
  it("renders a supported answer with stable claim citations and source link", async () => {
    api.answerQuestion.mockResolvedValue(response());
    await renderAsk();

    await ask();

    expect(
      await screen.findByText(
        "Authentication was postponed until Q4, with Priya owning the decision.",
      ),
    ).toBeVisible();
    expect(screen.getByText(/^answered$/i)).toBeVisible();

    const claims = within(screen.getByRole("list", { name: /answer claims/i }))
      .getAllByRole("listitem");
    expect(claims[0]).toHaveTextContent("Authentication was postponed until Q4. [1]");
    expect(claims[1]).toHaveTextContent("Priya owned the decision. [1]");

    expect(screen.getByText(firstCitation.quote)).toBeVisible();
    expect(
      screen.getByRole("link", { name: /architecture-review\.md.*lines 12–14/i }),
    ).toHaveAttribute(
      "href",
      "http://localhost:8000/api/v1/documents/document-1",
    );
  });

  it("shows unsupported facets beside a partial answer", async () => {
    api.answerQuestion.mockResolvedValue(
      response({
        answer: "Authentication was postponed, but the later owner is not documented.",
        state: "partial",
        confidence: "medium",
        unsupported_facets: ["who approved the later change"],
      }),
    );
    await renderAsk();

    await ask("Why was authentication postponed and who changed it later?");

    expect(await screen.findByText(/^partial$/i)).toBeVisible();
    expect(screen.getByText(/unsupported by current evidence/i)).toBeVisible();
    expect(screen.getByText("who approved the later change")).toBeVisible();
  });

  it("renders an honest abstention when evidence is insufficient", async () => {
    api.answerQuestion.mockResolvedValue(
      response({
        answer: "Insufficient evidence to answer that question.",
        state: "abstained",
        confidence: "none",
        claims: [],
        citations: [],
        unsupported_facets: ["database vendor selection"],
      }),
    );
    await renderAsk();

    await ask("Why did the team select CockroachDB?");

    expect(await screen.findByText(/^abstained$/i)).toBeVisible();
    expect(
      screen.getByText("Insufficient evidence to answer that question."),
    ).toBeVisible();
    expect(screen.getByText("database vendor selection")).toBeVisible();
    expect(screen.queryByRole("list", { name: /citations/i })).not.toBeInTheDocument();
  });

  it("identifies conflicting evidence and shows every conflicting source", async () => {
    api.answerQuestion.mockResolvedValue(
      response({
        answer: "The schedule changed, but the sources disagree on its final status.",
        state: "conflicted",
        confidence: "low",
        citations: [firstCitation, secondCitation],
        conflicts: [
          { facet: "status", passage_ids: [passageOne, passageTwo] },
        ],
      }),
    );
    await renderAsk();

    await ask("Was authentication later changed?");

    expect(await screen.findByText(/^conflicted$/i)).toBeVisible();
    const warning = screen.getByRole("alert");
    expect(warning).toHaveTextContent(/conflicting evidence/i);
    expect(warning).toHaveTextContent(/status/i);
    expect(screen.getByText(firstCitation.quote)).toBeVisible();
    expect(screen.getByText(secondCitation.quote)).toBeVisible();
  });

  it("loads retrieval ranks only when the developer trace is expanded", async () => {
    api.answerQuestion.mockResolvedValue(response());
    api.getRetrievalTrace.mockResolvedValue({
      id: traceId,
      request_id: "request-trace-1",
      normalized_question: "why was authentication postponed?",
      filters: {},
      semantic_candidates: [
        { passage_id: passageOne, rank: 1, score: 0.91 },
      ],
      keyword_candidates: [
        { passage_id: passageOne, rank: 3, score: 0.72 },
      ],
      decision_candidates: [],
      fused_results: [
        {
          passage_id: passageOne,
          rank: 1,
          fused_score: 0.032,
          source_ranks: { semantic: 1, keyword: 3 },
        },
      ],
      selected_passage_ids: [passageOne],
      timings: { total_ms: 84 },
      configuration: { top_k: 5, rrf_k: 60 },
      created_at: "2026-08-11T04:00:00Z",
    });
    const user = userEvent.setup();
    await renderAsk();
    await ask();

    expect(await screen.findByText(/^answered$/i)).toBeVisible();
    expect(api.getRetrievalTrace).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("region", { name: /semantic candidates/i }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /show retrieval trace/i }));

    expect(api.getRetrievalTrace).toHaveBeenCalledWith(traceId);
    expect(
      within(
        await screen.findByRole("region", { name: /semantic candidates/i }),
      ).getByText("Rank 1"),
    ).toBeVisible();
    expect(
      within(screen.getByRole("region", { name: /keyword candidates/i })).getByText(
        "Rank 3",
      ),
    ).toBeVisible();
    expect(
      within(screen.getByRole("region", { name: /fused results/i })).getByText(
        "Rank 1",
      ),
    ).toBeVisible();
  });

  it("shows the stable request ID when answering fails", async () => {
    api.answerQuestion.mockRejectedValue(
      Object.assign(new Error("The local model is unavailable"), {
        requestId: "request-answer-123",
      }),
    );
    await renderAsk();

    await ask();

    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("The local model is unavailable");
    expect(error).toHaveTextContent("Request ID: request-answer-123");
  });
});
