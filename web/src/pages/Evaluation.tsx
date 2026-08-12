import { useEffect, useRef, useState } from "react";

import { getEvaluationRun, startEvaluationRun } from "../api/client";
import type {
  EvaluationRun,
  EvaluationRunRequest,
  EvaluationStrategy,
} from "../api/types";
import { EvaluationResults } from "../components/EvaluationResults";

const POLL_INTERVAL_MS = 2_000;

const benchmarkConfiguration: Omit<EvaluationRunRequest, "strategy"> = {
  dataset_version: import.meta.env.VITE_EVALUATION_DATASET_VERSION || "atlas-v1",
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

  useEffect(
    () => () => {
      mounted.current = false;
      for (const timer of Object.values(timers.current)) {
        if (timer !== undefined) clearTimeout(timer);
      }
    },
    [],
  );

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
          Start semantic evaluation
        </button>
        <button
          type="button"
          onClick={() => void start("hybrid")}
          disabled={Boolean(hybrid && isActive(hybrid))}
        >
          Start hybrid evaluation
        </button>
      </div>

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
