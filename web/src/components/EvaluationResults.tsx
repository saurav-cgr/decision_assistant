import type { EvaluationResult, EvaluationRun } from "../api/types";
import { MetricSummary } from "./MetricSummary";

type EvaluationResultsProps = {
  run: EvaluationRun;
};

function expectedIdentifiers(result: EvaluationResult): string[] {
  const passages = result.expected_values.expected_passages;
  if (Array.isArray(passages)) {
    const ids = passages.flatMap((item) => {
      if (!item || typeof item !== "object" || !("passage_id" in item)) return [];
      return [String(item.passage_id)];
    });
    if (ids.length > 0) return ids;
  }
  const documents = result.expected_values.expected_documents;
  if (!Array.isArray(documents)) return [];
  return documents.flatMap((item) => {
    if (!item || typeof item !== "object" || !("document_id" in item)) return [];
    return [String(item.document_id)];
  });
}

function retrievalRank(result: EvaluationResult): number | null {
  const ranks = result.retrieved_ranks.ranks || {};
  const found = expectedIdentifiers(result)
    .map((identifier) => ranks[identifier])
    .filter((rank): rank is number => typeof rank === "number");
  return found.length > 0 ? Math.min(...found) : null;
}

function citationFailed(result: EvaluationResult): boolean {
  const checks = result.citation_checks.checks || [];
  return checks.some(
    (check) =>
      check.structurally_valid !== true || check.gold_relevant !== true,
  );
}

function abstentionFailed(result: EvaluationResult): boolean {
  return (
    result.expected_values.expectation !== result.actual_values.expectation
  );
}

function hasFailure(result: EvaluationResult): boolean {
  return Boolean(
    result.failure_reason || citationFailed(result) || abstentionFailed(result),
  );
}

export function EvaluationResults({ run }: EvaluationResultsProps) {
  const strategy = run.strategy.charAt(0).toUpperCase() + run.strategy.slice(1);

  return (
    <section className="evaluation-run" aria-label={`${strategy} evaluation`}>
      <div className="evaluation-run__heading">
        <div>
          <p className="eyebrow">{run.dataset_version}</p>
          <h2>{strategy}</h2>
        </div>
        <div className={`run-status run-status--${run.status}`}>
          <strong>{run.status}</strong>
          <span>
            {run.completed_questions} of {run.total_questions} questions
          </span>
        </div>
      </div>

      {run.failure && (
        <p className="answer-error" role="alert">
          {String(run.failure.message || run.failure.code || "Evaluation failed")}
        </p>
      )}

      {run.aggregate_metrics && <MetricSummary metrics={run.aggregate_metrics} />}

      {run.results.length > 0 && (
        <div className="evaluation-table-wrap">
          <table aria-label={`${run.strategy} per-question results`}>
            <thead>
              <tr>
                <th>Question</th>
                <th>Retrieval</th>
                <th>Latency</th>
                <th>Quality</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {run.results.map((result) => {
                const rank = retrievalRank(result);
                const citationFailure = citationFailed(result);
                const abstentionFailure = abstentionFailed(result);
                return (
                  <tr key={result.id}>
                    <th scope="row">{result.external_id}</th>
                    <td>{rank === null ? "Not retrieved" : `Rank ${rank}`}</td>
                    <td>
                      {result.latency_ms === null ? "Not recorded" : `${result.latency_ms} ms`}
                    </td>
                    <td>
                      <div className="result-flags">
                        {result.failure_reason && <span>Execution failure</span>}
                        {citationFailure && <span>Citation failure</span>}
                        {abstentionFailure && <span>Abstention failure</span>}
                        {!hasFailure(result) && <span className="result-pass">Passed</span>}
                      </div>
                    </td>
                    <td>
                      {hasFailure(result) ? (
                        <a href={`#diagnostic-${result.id}`}>View diagnostics</a>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {run.results.filter(hasFailure).map((result) => (
        <section
          className="evaluation-diagnostic"
          id={`diagnostic-${result.id}`}
          aria-label={`Diagnostic ${result.id}`}
          key={result.id}
        >
          <h3>{result.external_id}</h3>
          {result.failure_reason && <p>{result.failure_reason}</p>}
          <dl>
            <div>
              <dt>Expected</dt>
              <dd>{String(result.expected_values.expectation || "unspecified")}</dd>
            </div>
            <div>
              <dt>Actual</dt>
              <dd>{String(result.actual_values.expectation || "unspecified")}</dd>
            </div>
          </dl>
          <details>
            <summary>Stored diagnostic payload</summary>
            <pre>{JSON.stringify(result, null, 2)}</pre>
          </details>
        </section>
      ))}
    </section>
  );
}
