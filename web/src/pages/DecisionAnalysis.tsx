import { type FormEvent, useMemo, useState } from "react";

import { analyzeDecision } from "../api/client";
import type {
  DecisionAnalysisCriterion,
  DecisionAnalysisOption,
  DecisionAnalysisRequest,
  DecisionScoreProvenance,
} from "../api/types";
import "./DecisionAnalysis.css";

type ScoreDraft = {
  value: string;
  provenance: Exclude<DecisionScoreProvenance, "evidence_backed">;
  rationale: string;
};

const EMPTY_SCORE: ScoreDraft = {
  value: "",
  provenance: "user_provided",
  rationale: "",
};

function scoreKey(optionId: string, criterionId: string): string {
  return `${optionId}:${criterionId}`;
}

function newOption(index: number): DecisionAnalysisOption {
  return { id: `option_${index}`, label: "" };
}

function newCriterion(index: number): DecisionAnalysisCriterion {
  return {
    id: `criterion_${index}`,
    label: "",
    direction: "benefit",
    weight: "0.5",
    scale: "ordinal",
  };
}

function validDecimal(value: string): boolean {
  return /^\d+(?:\.\d{1,8})?$/.test(value);
}

function decimalUnits(value: string): bigint | null {
  if (!validDecimal(value)) return null;
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * 100_000_000n + BigInt(fraction.padEnd(8, "0"));
}

function validationMessage(
  title: string,
  options: DecisionAnalysisOption[],
  criteria: DecisionAnalysisCriterion[],
  scores: Record<string, ScoreDraft>,
): string | null {
  if (!title.trim()) return "Enter a decision title.";
  if (options.some((option) => !option.id.trim() || !option.label.trim())) {
    return "Every option needs an ID and label.";
  }
  if (new Set(options.map((option) => option.id)).size !== options.length) {
    return "Option IDs must be unique.";
  }
  if (criteria.some((criterion) => !criterion.id.trim() || !criterion.label.trim())) {
    return "Every criterion needs an ID and label.";
  }
  if (new Set(criteria.map((criterion) => criterion.id)).size !== criteria.length) {
    return "Criterion IDs must be unique.";
  }
  const weights = criteria.map((criterion) => decimalUnits(criterion.weight));
  if (weights.some((weight) => weight === null)) {
    return "Use non-negative decimal criterion weights.";
  }
  const totalWeight = weights.reduce<bigint>(
    (total, weight) => total + (weight ?? 0n),
    0n,
  );
  if (totalWeight !== 100_000_000n) {
    return "Criterion weights must total exactly 1.0.";
  }
  for (const option of options) {
    for (const criterion of criteria) {
      const score = scores[scoreKey(option.id, criterion.id)] ?? EMPTY_SCORE;
      if (!validDecimal(score.value)) {
        return "Enter a non-negative score for every option and criterion.";
      }
    }
  }
  return null;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Decision analysis failed.";
}

export function DecisionAnalysis() {
  const [title, setTitle] = useState("");
  const [options, setOptions] = useState([newOption(1), newOption(2)]);
  const [criteria, setCriteria] = useState([newCriterion(1), newCriterion(2)]);
  const [scores, setScores] = useState<Record<string, ScoreDraft>>({});
  const [narrativeRequested, setNarrativeRequested] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [complete, setComplete] = useState(false);

  const validation = useMemo(
    () => validationMessage(title, options, criteria, scores),
    [criteria, options, scores, title],
  );

  const updateOption = (index: number, patch: Partial<DecisionAnalysisOption>) => {
    setOptions((current) =>
      current.map((option, optionIndex) =>
        optionIndex === index ? { ...option, ...patch } : option,
      ),
    );
  };
  const updateCriterion = (
    index: number,
    patch: Partial<DecisionAnalysisCriterion>,
  ) => {
    setCriteria((current) =>
      current.map((criterion, criterionIndex) =>
        criterionIndex === index ? { ...criterion, ...patch } : criterion,
      ),
    );
  };
  const updateScore = (key: string, patch: Partial<ScoreDraft>) => {
    setScores((current) => ({
      ...current,
      [key]: { ...(current[key] ?? EMPTY_SCORE), ...patch },
    }));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (validation || loading) return;
    const request: DecisionAnalysisRequest = {
      title: title.trim(),
      options,
      criteria,
      scores: options.flatMap((option) =>
        criteria.map((criterion) => {
          const score = scores[scoreKey(option.id, criterion.id)] ?? EMPTY_SCORE;
          return {
            option_id: option.id,
            criterion_id: criterion.id,
            value: score.value,
            provenance: score.provenance,
            rationale: score.rationale || null,
          };
        }),
      ),
      sensitivity: { range_percent: "0.2", sample_count: 5 },
      narrative_requested: narrativeRequested,
    };
    setError(null);
    setComplete(false);
    setLoading(true);
    try {
      await analyzeDecision(request);
      setComplete(true);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="decision-analysis-page" aria-labelledby="decision-analysis-title">
      <header className="decision-analysis-page__header">
        <p className="eyebrow">Deterministic trade-offs</p>
        <h1 id="decision-analysis-title">Decision analysis</h1>
        <p className="page-description">
          Compare options with explicit criteria and weights. The server calculates
          the ranking; assumptions remain visible.
        </p>
      </header>

      <form
        className="decision-analysis-form"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <label>
          <span>Decision title</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>

        <section aria-labelledby="options-title">
          <div className="decision-analysis-form__heading">
            <h2 id="options-title">Options</h2>
            <button
              type="button"
              onClick={() => setOptions((current) => [...current, newOption(current.length + 1)])}
            >
              Add option
            </button>
          </div>
          {options.map((option, index) => (
            <div className="decision-analysis-form__row" key={`${option.id}-${index}`}>
              <label>
                <span>Option {index + 1} ID</span>
                <input value={option.id} onChange={(event) => updateOption(index, { id: event.target.value })} />
              </label>
              <label>
                <span>Option {index + 1} label</span>
                <input value={option.label} onChange={(event) => updateOption(index, { label: event.target.value })} />
              </label>
              <button type="button" disabled={options.length <= 2} onClick={() => setOptions((current) => current.filter((_, rowIndex) => rowIndex !== index))}>
                Remove
              </button>
            </div>
          ))}
        </section>

        <section aria-labelledby="criteria-title">
          <div className="decision-analysis-form__heading">
            <h2 id="criteria-title">Criteria</h2>
            <button type="button" onClick={() => setCriteria((current) => [...current, newCriterion(current.length + 1)])}>
              Add criterion
            </button>
          </div>
          {criteria.map((criterion, index) => (
            <div className="decision-analysis-form__criteria-row" key={`${criterion.id}-${index}`}>
              <label><span>Criterion {index + 1} ID</span><input value={criterion.id} onChange={(event) => updateCriterion(index, { id: event.target.value })} /></label>
              <label><span>Criterion {index + 1} label</span><input value={criterion.label} onChange={(event) => updateCriterion(index, { label: event.target.value })} /></label>
              <label><span>Direction</span><select value={criterion.direction} onChange={(event) => updateCriterion(index, { direction: event.target.value as DecisionAnalysisCriterion["direction"] })}><option value="benefit">Benefit</option><option value="cost">Cost</option></select></label>
              <label><span>Weight</span><input inputMode="decimal" value={criterion.weight} onChange={(event) => updateCriterion(index, { weight: event.target.value })} /></label>
              <button type="button" disabled={criteria.length <= 1} onClick={() => setCriteria((current) => current.filter((_, rowIndex) => rowIndex !== index))}>Remove</button>
            </div>
          ))}
        </section>

        <section aria-labelledby="score-matrix-title">
          <h2 id="score-matrix-title">Score matrix</h2>
          <div className="decision-analysis-matrix__scroll">
            <table>
              <thead><tr><th scope="col">Option</th>{criteria.map((criterion) => <th key={criterion.id} scope="col">{criterion.label || criterion.id}</th>)}</tr></thead>
              <tbody>{options.map((option) => <tr key={option.id}><th scope="row">{option.label || option.id}</th>{criteria.map((criterion) => {
                const key = scoreKey(option.id, criterion.id);
                const score = scores[key] ?? EMPTY_SCORE;
                return <td key={key}><label><span className="visually-hidden">{option.label || option.id} {criterion.label || criterion.id} score</span><input inputMode="decimal" value={score.value} onChange={(event) => updateScore(key, { value: event.target.value })} /></label><select aria-label={`${option.label || option.id} ${criterion.label || criterion.id} provenance`} value={score.provenance} onChange={(event) => updateScore(key, { provenance: event.target.value as ScoreDraft["provenance"] })}><option value="user_provided">Assumption</option><option value="derived">Derived</option></select></td>;
              })}</tr>)}</tbody>
            </table>
          </div>
        </section>

        <label className="decision-analysis-form__checkbox"><input type="checkbox" checked={narrativeRequested} onChange={(event) => setNarrativeRequested(event.target.checked)} /> Request optional explanation</label>
        {validation && <p className="decision-analysis-form__hint">{validation}</p>}
        {error && <p className="decision-analysis-form__error" role="alert">{error}</p>}
        {complete && <p role="status">Analysis calculated. Result view arrives next.</p>}
        <button className="decision-analysis-form__submit" type="submit" disabled={Boolean(validation) || loading}>{loading ? "Analyzing…" : "Analyze decision"}</button>
      </form>
    </section>
  );
}
