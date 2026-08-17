import type { DecisionAnalysisResponse } from "../api/types";

type Props = { result: DecisionAnalysisResponse };

export function DecisionAnalysisResult({ result }: Props) {
  const winner = result.ranked_options[0];

  return (
    <article className="decision-analysis-result" aria-labelledby="analysis-result-title">
      <header className="decision-analysis-result__header">
        <div>
          <p className="eyebrow">Verified calculation</p>
          <h2 id="analysis-result-title">Decision result</h2>
        </div>
        {winner && (
          <div className="decision-analysis-result__winner">
            <span>Top option</span>
            <strong>{winner.option_id}</strong>
            <small>Score {winner.total_score}</small>
          </div>
        )}
      </header>

      {!result.verification.valid && (
        <p className="decision-analysis-result__error" role="alert">
          Verification failed: {result.verification.errors.join(", ")}
        </p>
      )}

      <section aria-labelledby="ranking-title">
        <h3 id="ranking-title">Ranking</h3>
        <div className="decision-analysis-result__scroll">
          <table>
            <thead><tr><th scope="col">Rank</th><th scope="col">Option</th><th scope="col">Total</th><th scope="col">Contributions</th></tr></thead>
            <tbody>{result.ranked_options.map((option) => <tr key={option.option_id}><td>{option.rank}</td><th scope="row">{option.option_id}</th><td>{option.total_score}</td><td>{option.contributions.map((item) => `${item.criterion_id}: ${item.weighted_contribution}`).join(" · ")}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      {result.tie_groups.length > 0 && (
        <aside className="decision-analysis-result__warning" role="alert">
          <strong>Tied options</strong>
          <span>{result.tie_groups.map((group) => group.join(" and ")).join("; ")}. Display order is not a recommendation.</span>
        </aside>
      )}

      {result.sensitivity && (
        <section className={`decision-analysis-result__sensitivity decision-analysis-result__sensitivity--${result.sensitivity.stability}`} aria-labelledby="sensitivity-title">
          <h3 id="sensitivity-title">Sensitivity</h3>
          <p>
            {result.sensitivity.stability === "sensitive"
              ? `Result changes when weights vary: ${result.sensitivity.reversing_criterion_ids.join(", ")}.`
              : "Top option remained stable across tested weight variations."}
          </p>
        </section>
      )}

      <section className="decision-analysis-result__provenance" aria-labelledby="provenance-title">
        <h3 id="provenance-title">Input provenance</h3>
        <ul>
          <li>{result.evidence_coverage.user_provided_score_count} assumptions</li>
          <li>{result.evidence_coverage.derived_score_count} derived values</li>
          <li>{result.evidence_coverage.evidence_backed_score_count} evidence-backed values</li>
          <li>Evidence-backed weight: {result.evidence_coverage.evidence_backed_weight}</li>
        </ul>
      </section>

      {result.verification.warnings.length > 0 && (
        <aside className="decision-analysis-result__warning">
          <strong>Review before acting</strong>
          <ul>{result.verification.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </aside>
      )}

      {result.narrative_status === "generated" && result.narrative && (
        <section className="decision-analysis-result__narrative" aria-labelledby="narrative-title">
          <h3 id="narrative-title">Explanation</h3>
          <p>{result.narrative.summary}</p>
          {result.narrative.tradeoffs.length > 0 && <p>Trade-offs: {result.narrative.tradeoffs.join(" ")}</p>}
        </section>
      )}
    </article>
  );
}
