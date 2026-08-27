import type { EvaluationResult, EvaluationRun } from "../api/types";
import { AnswerPipelineDiagnostics } from "./AnswerPipelineDiagnostics";
import { MetricSummary } from "./MetricSummary";

type EvaluationResultsProps = {
  run: EvaluationRun;
};

function FacetList({ value, label }: { value: unknown; label: string }) {
  const entries =
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.entries(value)
      : [];
  if (entries.length === 0) return <span>None</span>;
  return (
    <ul className="evaluation-facet-list" aria-label={label}>
      {entries.map(([facet, outcome]) => (
        <li key={facet}>
          <span>{facet.replaceAll("_", " ")}</span>
          <strong>{String(outcome)}</strong>
        </li>
      ))}
    </ul>
  );
}

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
      check.structurally_valid !== true || check.supports_claim !== true,
  );
}

function goldCoverageFailed(result: EvaluationResult): boolean {
  const expectation = result.expected_values.expectation;
  if (expectation !== "answer" && expectation !== "partial") return false;
  return !(result.citation_checks.checks || []).some(
    (check) => check.matches_gold_evidence === true,
  );
}

function abstentionFailed(result: EvaluationResult): boolean {
  return (
    result.expected_values.expectation !== result.actual_values.expectation
  );
}

function facetFailed(result: EvaluationResult): boolean {
  const expected = result.expected_values.facets;
  const actual = result.actual_values.facets;
  if (!expected || typeof expected !== "object" || Array.isArray(expected)) {
    return false;
  }
  const actualFacets =
    actual && typeof actual === "object" && !Array.isArray(actual)
      ? actual
      : {};
  return Object.entries(expected).some(
    ([facet, outcome]) =>
      (actualFacets as Record<string, unknown>)[facet] !== outcome,
  );
}

function hasFailure(result: EvaluationResult): boolean {
  return Boolean(
    result.failure_reason ||
      citationFailed(result) ||
      goldCoverageFailed(result) ||
      abstentionFailed(result) ||
      facetFailed(result),
  );
}

export function EvaluationResults({ run }: EvaluationResultsProps) {
  const strategy = run.strategy.charAt(0).toUpperCase() + run.strategy.slice(1);
  const active = run.status === "pending" || run.status === "running";
  const progress =
    run.total_questions > 0
      ? Math.round((run.completed_questions / run.total_questions) * 100)
      : 0;

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

      {active && (
        <div className="evaluation-progress" role="status">
          <strong>Evaluation in progress</strong>
          <span>
            Running the {run.total_questions}-question benchmark against{" "}
            {run.dataset_version}. This takes a few minutes — results appear
            here automatically when it finishes.
          </span>
          <div
            className="evaluation-progress__bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
          >
            <span style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {run.failure && (
        <p className="answer-error" role="alert">
          {String(run.failure.message || run.failure.code || "Evaluation failed")}
        </p>
      )}

      {run.aggregate_metrics && <MetricSummary metrics={run.aggregate_metrics} />}

      {run.results.length > 0 && (
        <details className="evaluation-details" open>
          <summary>
            <span>Question-level results</span>
            <small>{run.results.length} questions</small>
          </summary>
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
                const goldFailure = goldCoverageFailed(result);
                const abstentionFailure = abstentionFailed(result);
                const facetFailure = facetFailed(result);
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
                        {citationFailure && <span>Unsupported citation</span>}
                        {goldFailure && <span>Gold evidence missing</span>}
                        {abstentionFailure && <span>Abstention failure</span>}
                        {facetFailure && <span>Facet failure</span>}
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
        </details>
      )}

      {run.results.filter(hasFailure).map((result) => (
        <details className="evaluation-details evaluation-diagnostic-details" open key={result.id}>
          <summary>
            <span>Diagnostic · {result.external_id}</span>
            <small>Failure details</small>
          </summary>
          <section
            className="evaluation-diagnostic"
            id={`diagnostic-${result.id}`}
            aria-label={`Diagnostic ${result.id}`}
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
            <div>
              <dt>Expected facets</dt>
              <dd>
                <FacetList
                  value={result.expected_values.facets}
                  label="Expected facets"
                />
              </dd>
            </div>
            <div>
              <dt>Actual facets</dt>
              <dd>
                <FacetList
                  value={result.actual_values.facets}
                  label="Actual facets"
                />
              </dd>
            </div>
          </dl>
          <AnswerPipelineDiagnostics value={result.answer_diagnostics} />
          {(result.citation_checks.checks || []).length > 0 && (
            <div className="evaluation-citation-diagnostics">
              <h4>Citation diagnostics</h4>
              <ul>
                {(result.citation_checks.checks || []).map((check, index) => (
                  <li key={`${check.claim_index}-${check.passage_id}-${index}`}>
                    <strong>
                      {check.document_name || check.passage_id}
                    </strong>{" "}
                    — claim {check.claim_index === null ? "unlinked" : check.claim_index + 1}:{" "}
                    {check.structurally_valid !== true
                      ? "structurally invalid"
                      : check.supports_claim !== true
                        ? "does not support claim"
                        : check.matches_gold_evidence
                          ? "supports claim; matches gold evidence"
                          : "supports claim; alternative evidence"}
                    {check.reason ? ` — ${check.reason}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <details>
            <summary>Stored diagnostic payload</summary>
            <pre>{JSON.stringify(result, null, 2)}</pre>
          </details>
          </section>
        </details>
      ))}
    </section>
  );
}
