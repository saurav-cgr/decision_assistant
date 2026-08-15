import { useState } from "react";

import { getRetrievalTrace } from "../api/client";
import type {
  RetrievalCandidate,
  RetrievalTraceResponse,
  RerankTrace,
} from "../api/types";

type RetrievalTraceProps = {
  traceId: string;
};

type CandidateRegionProps = {
  label: string;
  candidates: RetrievalCandidate[];
};

function CandidateRegion({ label, candidates }: CandidateRegionProps) {  return (
    <section className="trace-region" aria-label={label}>
      <h3>{label}</h3>
      {candidates.length === 0 ? (
        <p>No candidates</p>
      ) : (
        <ol>
          {candidates.map((candidate, index) => (
            <li key={`${candidate.passage_id}-${index}`}>
              <strong>Rank {candidate.rank ?? index + 1}</strong>
              <code>{candidate.passage_id}</code>
              {candidate.source_ranks && (
                <span>
                  {Object.entries(candidate.source_ranks)
                    .map(([source, rank]) => `${source} #${rank}`)
                    .join(" · ")}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

type RerankerRegionProps = {
  rerank: RerankTrace;
  rerankMs?: number;
};

function RerankerRegion({ rerank, rerankMs }: RerankerRegionProps) {
  const fallback = rerank.fallback_reason
    ? ` · fallback: ${rerank.fallback_reason}`
    : "";
  return (
    <section className="trace-region" aria-label="Reranker">
      <h3>Reranker</h3>
      <p>
        Status <code>{rerank.status}</code>
        {fallback}
        {typeof rerankMs === "number" && <span> · {rerankMs} ms</span>}
      </p>
      <p>
        <strong>Input order</strong>
      </p>
      <ol>
        {rerank.input_passage_ids.map((passageId, index) => (
          <li key={`${passageId}-in-${index}`}>
            <code>{passageId}</code>
          </li>
        ))}
      </ol>
      <p>
        <strong>Output order</strong>
      </p>
      <ol>
        {rerank.output_passage_ids.map((passageId, index) => (
          <li key={`${passageId}-out-${index}`}>
            <code>{passageId}</code>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function RetrievalTrace({ traceId }: RetrievalTraceProps) {
  const [expanded, setExpanded] = useState(false);
  const [trace, setTrace] = useState<RetrievalTraceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const showTrace = async () => {
    setExpanded(true);
    if (trace || loading) return;
    setLoading(true);
    setError(null);
    try {
      setTrace(await getRetrievalTrace(traceId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Trace could not be loaded.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="retrieval-trace">
      <button type="button" onClick={expanded ? () => setExpanded(false) : showTrace}>
        {expanded ? "Hide retrieval trace" : "Show retrieval trace"}
      </button>
      {expanded && loading && <p role="status">Loading retrieval trace…</p>}
      {expanded && error && <p role="alert">{error}</p>}
      {expanded && trace && (
        <div className="trace-panel">
          <div className="trace-summary">
            <span>Request {trace.request_id}</span>
            {typeof trace.timings.total_ms === "number" && (
              <span>{trace.timings.total_ms} ms total</span>
            )}
          </div>
          <CandidateRegion
            label="Semantic candidates"
            candidates={trace.semantic_candidates}
          />
          <CandidateRegion
            label="Keyword candidates"
            candidates={trace.keyword_candidates}
          />
          <CandidateRegion
            label="Decision candidates"
            candidates={trace.decision_candidates}
          />
          <CandidateRegion label="Fused results" candidates={trace.fused_results} />
          {trace.rerank && (
            <RerankerRegion
              rerank={trace.rerank}
              rerankMs={trace.timings.rerank_ms}
            />
          )}
        </div>
      )}
    </section>
  );
}
