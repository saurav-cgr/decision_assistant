import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getEvaluationRun: vi.fn(),
  startEvaluationRun: vi.fn(),
}));

vi.mock("../api/client", () => ({
  getEvaluationRun: api.getEvaluationRun,
  startEvaluationRun: api.startEvaluationRun,
}));

const sharedRequest = {
  dataset_version: "atlas-v1",
  configuration: { top_k: 5, rrf_k: 60 },
  generation_profile: { provider: "ollama", model: "qwen3:8b" },
  embedding_profile: { provider: "ollama", model: "embeddinggemma" },
  judge_profile: {
    provider: "ollama",
    model: "qwen3:8b",
    temperature: 0,
  },
};

const results = [
  {
    id: "result-auth",
    question_id: "question-auth",
    external_id: "auth-why",
    retrieved_ranks: {
      ids: ["unrelated", "passage-auth"],
      document_ids: [],
      ranks: { unrelated: 1, "passage-auth": 2 },
    },
    generated_output: { state: "answered", answer: "Billing was prioritized." },
    citation_checks: {
      checks: [{ structurally_valid: true, gold_relevant: true }],
    },
    expected_values: {
      question: "Why was authentication postponed?",
      expectation: "answer",
      expected_passages: [{ passage_id: "passage-auth" }],
    },
    actual_values: { expectation: "answer" },
    latency_ms: 42,
    judge_prompt: "stored judge prompt",
    judge_profile: { temperature: 0 },
    judge_output: { claims: [{ supported: true }] },
    failure_reason: null,
  },
  {
    id: "result-unsupported",
    question_id: "question-unsupported",
    external_id: "unsupported-vendor",
    retrieved_ranks: { ids: [], document_ids: [], ranks: {} },
    generated_output: { state: "answered", answer: "PostgreSQL was selected." },
    citation_checks: {
      checks: [{ structurally_valid: false, gold_relevant: false }],
    },
    expected_values: {
      question: "Why was CockroachDB rejected?",
      expectation: "abstain",
      expected_passages: [],
    },
    actual_values: { expectation: "answer" },
    latency_ms: 56,
    judge_prompt: null,
    judge_profile: null,
    judge_output: null,
    failure_reason: null,
  },
];

function completedRun(
  strategy: "semantic" | "hybrid",
  overrides: Record<string, unknown> = {},
) {
  return {
    id: `${strategy}-run`,
    strategy,
    status: "completed",
    completed_questions: 20,
    total_questions: 20,
    failure: null,
    ...sharedRequest,
    aggregate_metrics: {
      top_five_hit_rate: strategy === "hybrid" ? 0.85 : 0.7,
      mean_reciprocal_rank: strategy === "hybrid" ? 0.76 : 0.61,
      citation_structural_validity: 0.95,
      citation_correctness: 0.9,
      abstention_accuracy: 0.8,
      facet_abstention_accuracy: 0.75,
      answer_faithfulness: 0.88,
      median_latency_ms: 42,
      p95_latency_ms: 120,
      question_failures: 0,
    },
    started_at: "2026-08-11T05:00:00Z",
    completed_at: "2026-08-11T05:02:00Z",
    results,
    ...overrides,
  };
}

async function renderEvaluation() {
  const modulePath = "./Evaluation";
  const { Evaluation } = await import(/* @vite-ignore */ modulePath);
  return render(<Evaluation />);
}

async function startBoth() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /start semantic/i }));
  await user.click(screen.getByRole("button", { name: /start hybrid/i }));
}

beforeEach(() => {
  api.getEvaluationRun.mockReset();
  api.startEvaluationRun.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("Evaluation dashboard", () => {
  it("starts semantic and hybrid runs from one reproducible configuration", async () => {
    api.startEvaluationRun.mockImplementation(
      ({ strategy }: { strategy: "semantic" | "hybrid" }) =>
        Promise.resolve(completedRun(strategy)),
    );
    await renderEvaluation();

    await startBoth();

    expect(api.startEvaluationRun).toHaveBeenNthCalledWith(1, {
      strategy: "semantic",
      ...sharedRequest,
    });
    expect(api.startEvaluationRun).toHaveBeenNthCalledWith(2, {
      strategy: "hybrid",
      ...sharedRequest,
    });
  });

  it("polls progress every two seconds and stops after terminal state", async () => {
    vi.useFakeTimers();
    api.startEvaluationRun.mockResolvedValue({
      ...completedRun("semantic"),
      status: "pending",
      completed_questions: 0,
      aggregate_metrics: null,
      results: [],
      completed_at: null,
    });
    api.getEvaluationRun
      .mockResolvedValueOnce({
        ...completedRun("semantic"),
        status: "running",
        completed_questions: 4,
        aggregate_metrics: null,
        results: [],
        completed_at: null,
      })
      .mockResolvedValueOnce(completedRun("semantic"));
    await renderEvaluation();

    fireEvent.click(screen.getByRole("button", { name: /start semantic/i }));
    await act(async () => Promise.resolve());
    expect(screen.getByText("0 of 20 questions")).toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(api.getEvaluationRun).toHaveBeenCalledTimes(1);
    expect(screen.getByText("4 of 20 questions")).toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(api.getEvaluationRun).toHaveBeenCalledTimes(2);
    expect(screen.getByText("20 of 20 questions")).toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_000);
    });
    expect(api.getEvaluationRun).toHaveBeenCalledTimes(2);
  });

  it("compares aggregate metrics with definitions and millisecond latency", async () => {
    api.startEvaluationRun.mockImplementation(
      ({ strategy }: { strategy: "semantic" | "hybrid" }) =>
        Promise.resolve(completedRun(strategy)),
    );
    await renderEvaluation();
    await startBoth();

    const semantic = await screen.findByRole("region", {
      name: /semantic evaluation/i,
    });
    const hybrid = screen.getByRole("region", { name: /hybrid evaluation/i });
    const semanticMetrics = within(semantic).getByRole("region", {
      name: /aggregate metrics/i,
    });
    const hybridMetrics = within(hybrid).getByRole("region", {
      name: /aggregate metrics/i,
    });
    expect(within(semanticMetrics).getByText("Top-five hit rate")).toBeVisible();
    expect(
      within(semanticMetrics).getByText(
        /expected source appears in first five results/i,
      ),
    ).toBeVisible();
    expect(within(hybridMetrics).getByText("Mean reciprocal rank")).toBeVisible();
    expect(within(hybridMetrics).getByText("Citation correctness")).toBeVisible();
    expect(within(hybridMetrics).getByText("Answer faithfulness")).toBeVisible();
    expect(within(hybridMetrics).getByText("Abstention accuracy")).toBeVisible();
    expect(within(hybridMetrics).getByText("42 ms")).toBeVisible();
    expect(within(hybridMetrics).getByText("120 ms")).toBeVisible();
  });

  it("shows per-question ranks and links citation/abstention failures to diagnostics", async () => {
    api.startEvaluationRun.mockResolvedValue(completedRun("hybrid"));
    await renderEvaluation();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /start hybrid/i }));

    const table = await screen.findByRole("table", {
      name: /hybrid per-question results/i,
    });
    expect(within(table).getByText("auth-why")).toBeVisible();
    expect(within(table).getByText("Rank 2")).toBeVisible();
    const failedRow = within(table)
      .getByText("unsupported-vendor")
      .closest("tr");
    expect(failedRow).not.toBeNull();
    expect(within(failedRow!).getByText("Citation failure")).toBeVisible();
    expect(within(failedRow!).getByText("Abstention failure")).toBeVisible();
    expect(
      within(failedRow!).getByRole("link", { name: /view diagnostics/i }),
    ).toHaveAttribute("href", "#diagnostic-result-unsupported");
    expect(
      screen.getByRole("region", { name: /diagnostic result-unsupported/i }),
    ).toBeVisible();
  });

  it("blocks side-by-side comparison when run snapshots differ", async () => {
    api.startEvaluationRun.mockImplementation(
      ({ strategy }: { strategy: "semantic" | "hybrid" }) =>
        Promise.resolve(
          completedRun(
            strategy,
            strategy === "hybrid"
              ? { embedding_profile: { provider: "ollama", model: "different" } }
              : {},
          ),
        ),
    );
    await renderEvaluation();
    await startBoth();

    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent(/configuration mismatch/i);
    expect(
      screen.queryByRole("region", { name: /semantic evaluation/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: /hybrid evaluation/i }),
    ).not.toBeInTheDocument();
  });
});
