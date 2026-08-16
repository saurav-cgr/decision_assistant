import { useEffect, useRef, useState } from "react";

import { getEvaluationRun, listEvaluationRuns, startEvaluationRun } from "../api/client";
import type {
  EvaluationRun,
  EvaluationRunRequest,
  EvaluationStrategy,
} from "../api/types";
import { EvaluationResults } from "../components/EvaluationResults";

const POLL_INTERVAL_MS = 2_000;

const benchmarkConfiguration: Omit<EvaluationRunRequest, "strategy"> = {
  dataset_version: import.meta.env.VITE_EVALUATION_DATASET_VERSION || "atlas-v3",
  configuration: {
    top_k: Number(import.meta.env.VITE_EVALUATION_TOP_K || 5),
    rrf_k: Number(import.meta.env.VITE_EVALUATION_RRF_K || 60),
  },
};

function isActive(run: EvaluationRun): boolean {
  return run.status === "pending" || run.status === "running";
}

function sameSnapshot(left: EvaluationRun, right: EvaluationRun): boolean {
  return (
    left.dataset_version === right.dataset_version &&
    JSON.stringify(left.configuration) === JSON.stringify(right.configuration) &&
    JSON.stringify(left.generation_profile) ===
      JSON.stringify(right.generation_profile) &&
    JSON.stringify(left.embedding_profile) ===
      JSON.stringify(right.embedding_profile) &&
    JSON.stringify(left.judge_profile) === JSON.stringify(right.judge_profile)
  );
}

export function Evaluation() {
  const [runs, setRuns] = useState<
    Partial<Record<EvaluationStrategy, EvaluationRun>>
  >({});
  const [error, setError] = useState<string | null>(null);
  const timers = useRef<Partial<Record<EvaluationStrategy, ReturnType<typeof setTimeout>>>>(
    {},
  );
  const mounted = useRef(true);

  useEffect(() => {
    // React StrictMode double-mounts in dev; re-arm the flag on each mount so
    // the async start/load handlers don't silently bail after their first await.
    mounted.current = true;
    return () => {
      mounted.current = false;
      for (const timer of Object.values(timers.current)) {
        if (timer !== undefined) clearTimeout(timer);
      }
    };
  }, []);

  // Load the most recent run for each strategy so past results remain visible
  // after a reload, instead of showing only the start buttons.
  useEffect(() => {
    const loadExisting = async () => {
      try {
        const summaries = await listEvaluationRuns();
        if (!mounted.current) return;
        const loadFor = async (strategy: EvaluationStrategy) => {
          const summary = summaries.find(
            (item) =>
              item.strategy === strategy &&
              item.dataset_version === benchmarkConfiguration.dataset_version,
          );
          if (!summary) return;
          const run = await getEvaluationRun(summary.id);
          if (!mounted.current) return;
          setRuns((current) => ({ ...current, [strategy]: run }));
          if (isActive(run)) schedulePoll(strategy, run.id);
        };
        await Promise.all([loadFor("semantic"), loadFor("hybrid")]);
      } catch (caught) {
        if (mounted.current) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Evaluation history could not be loaded.",
          );
        }
      }
    };
    void loadExisting();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const schedulePoll = (strategy: EvaluationStrategy, runId: string) => {
    timers.current[strategy] = setTimeout(async () => {
      try {
        const updated = await getEvaluationRun(runId);
        if (!mounted.current) return;
        setRuns((current) => ({ ...current, [strategy]: updated }));
        if (isActive(updated)) schedulePoll(strategy, runId);
      } catch (caught) {
        if (mounted.current) {
          setError(
            caught instanceof Error ? caught.message : "Evaluation status could not be loaded.",
          );
        }
      }
    }, POLL_INTERVAL_MS);
  };

  const start = async (strategy: EvaluationStrategy) => {
    const existingTimer = timers.current[strategy];
    if (existingTimer !== undefined) clearTimeout(existingTimer);
    setError(null);
    try {
      const run = await startEvaluationRun({ strategy, ...benchmarkConfiguration });
      if (!mounted.current) return;
      setRuns((current) => ({ ...current, [strategy]: run }));
      if (isActive(run)) schedulePoll(strategy, run.id);
    } catch (caught) {
      if (mounted.current) {
        setError(caught instanceof Error ? caught.message : "Evaluation could not start.");
      }
    }
  };

  const semantic = runs.semantic;
  const hybrid = runs.hybrid;
  const mismatch = Boolean(
    semantic && hybrid && !sameSnapshot(semantic, hybrid),
  );

  return (
    <section className="evaluation-page" aria-labelledby="evaluation-title">
      <header>
        <p className="eyebrow">Quality lab</p>
        <h1 id="evaluation-title">Measure retrieval and answer quality</h1>
        <p className="page-description">
          Compare semantic-only and hybrid retrieval against one curated,
          reproducible benchmark snapshot.
        </p>
      </header>

      <div className="evaluation-controls">
        <div>
          <strong>{benchmarkConfiguration.dataset_version}</strong>
          <span>
            top-k {String(benchmarkConfiguration.configuration.top_k)} · RRF k{" "}
            {String(benchmarkConfiguration.configuration.rrf_k)}
          </span>
        </div>
        <button
          type="button"
          onClick={() => void start("semantic")}
          disabled={Boolean(semantic && isActive(semantic))}
        >
          {semantic && isActive(semantic)
            ? "Semantic evaluation running…"
            : "Start semantic evaluation"}
        </button>
        <button
          type="button"
          onClick={() => void start("hybrid")}
          disabled={Boolean(hybrid && isActive(hybrid))}
        >
          {hybrid && isActive(hybrid)
            ? "Hybrid evaluation running…"
            : "Start hybrid evaluation"}
        </button>
      </div>

      {(semantic && isActive(semantic)) || (hybrid && isActive(hybrid)) ? (
        <p className="evaluation-running-hint" role="status">
          Evaluation in progress — a run takes a few minutes. Start buttons
          stay disabled until the current run completes, then re-enable
          automatically.
        </p>
      ) : null}

      {error && <p className="answer-error" role="alert">{error}</p>}

      {mismatch && (
        <div className="configuration-warning" role="alert">
          <strong>Configuration mismatch</strong>
          <span>
            Dataset or model snapshots differ. Start new runs with matching
            configuration before comparing results.
          </span>
        </div>
      )}

      {!mismatch && (semantic || hybrid) && (
        <div className="evaluation-comparison">
          {semantic && <EvaluationResults run={semantic} />}
          {hybrid && <EvaluationResults run={hybrid} />}
        </div>
      )}
    </section>
  );
}
