import { type FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import {
  createDecisionRelation,
  getDecision,
  listDecisions,
} from "../api/client";
import type {
  DecisionDetail as DecisionDetailType,
  DecisionRelation,
  DecisionSummary,
} from "../api/types";
import { DecisionEditor } from "../components/DecisionEditor";

function titleCase(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function revisionValue(value: unknown): string {
  if (value === null || value === undefined) return "Not set";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function DecisionDetail() {
  const { id } = useParams<{ id: string }>();
  const [decision, setDecision] = useState<DecisionDetailType | null>(null);
  const [targets, setTargets] = useState<DecisionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [targetId, setTargetId] = useState("");
  const [relationType, setRelationType] = useState<
    "supersedes" | "revises" | "relates_to"
  >("relates_to");
  const [rationale, setRationale] = useState("");
  const [savingRelation, setSavingRelation] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!id) return;
    Promise.all([getDecision(id), listDecisions()])
      .then(([loadedDecision, loadedDecisions]) => {
        if (cancelled) return;
        setDecision(loadedDecision);
        const available = loadedDecisions.items.filter((item) => item.id !== id);
        setTargets(available);
        setTargetId(available[0]?.id || "");
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Decision could not be loaded.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const submitRelationship = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!id || !targetId) return;
    setSavingRelation(true);
    setError(null);
    try {
      const relation = await createDecisionRelation(id, {
        target_decision_id: targetId,
        relation_type: relationType,
        rationale: rationale.trim() || null,
      });
      setDecision((current) =>
        current
          ? { ...current, relations: [...current.relations, relation] }
          : current,
      );
      setRationale("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Relationship could not be saved.");
    } finally {
      setSavingRelation(false);
    }
  };

  if (error && !decision) return <p role="alert">{error}</p>;
  if (!decision) return <p role="status">Loading decision…</p>;

  const confirmedRelations = decision.relations.filter(
    (relation) => relation.authority === "user_confirmed",
  );

  return (
    <section className="decision-detail-page" aria-labelledby="decision-title">
      <header className="decision-detail-header">
        <p className="eyebrow">Structured decision</p>
        <h1 id="decision-title">{decision.statement}</h1>
        <div className="decision-badges">
          <span>{titleCase(decision.status)}</span>
          <span>{titleCase(decision.review_state)}</span>
          <span>{titleCase(decision.provenance)}</span>
        </div>
      </header>

      {error && <p className="answer-error" role="alert">{error}</p>}

      <dl className="decision-fields">
        <div><dt>Date</dt><dd>{decision.effective_date || "Not set"}</dd></div>
        <div><dt>Owner</dt><dd>{decision.owner || "Not set"}</dd></div>
        <div><dt>Project</dt><dd>{decision.project || "Not set"}</dd></div>
        <div><dt>Topic</dt><dd>{decision.topic || "Not set"}</dd></div>
        <div><dt>Reasons</dt><dd>{decision.reasons.join(", ") || "None"}</dd></div>
        <div><dt>Alternatives</dt><dd>{decision.alternatives.join(", ") || "None"}</dd></div>
      </dl>

      <section className="source-evidence" aria-labelledby="source-evidence-title">
        <div className="section-heading">
          <p className="eyebrow">Immutable record</p>
          <h2 id="source-evidence-title">Source evidence</h2>
        </div>
        {decision.evidence.map((evidence) => (
          <blockquote key={evidence.passage_id}>{evidence.quote}</blockquote>
        ))}
      </section>

      <DecisionEditor decision={decision} onSaved={setDecision} />

      <section className="revision-section" aria-labelledby="revisions-title">
        <div className="section-heading">
          <p className="eyebrow">Audit trail</p>
          <h2 id="revisions-title">Revision history</h2>
        </div>
        <ol aria-label="Revision history">
          {decision.revisions.map((revision) => (
            <li key={revision.id}>
              <strong>{revision.field_name}</strong>
              <span>
                {revisionValue(revision.old_value)} → {revisionValue(revision.new_value)}
              </span>
              <small>{titleCase(revision.support_state)}</small>
            </li>
          ))}
        </ol>
      </section>

      <section className="relationship-section" aria-labelledby="relationships-title">
        <div className="section-heading">
          <p className="eyebrow">Domain input</p>
          <h2 id="relationships-title">Team-confirmed relationships</h2>
        </div>
        {confirmedRelations.length > 0 ? (
          <ul>
            {confirmedRelations.map((relation: DecisionRelation) => (
              <li key={relation.id}>
                <strong>{titleCase(relation.relation_type)}</strong>
                {relation.rationale && <span>{relation.rationale}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p>No team-confirmed relationships yet.</p>
        )}

        <form
          aria-label="Confirm decision relationship"
          onSubmit={submitRelationship}
        >
          <label>
            Target decision
            <select value={targetId} onChange={(event) => setTargetId(event.target.value)}>
              {targets.map((target) => (
                <option key={target.id} value={target.id}>{target.statement}</option>
              ))}
            </select>
          </label>
          <label>
            Relationship type
            <select
              value={relationType}
              onChange={(event) =>
                setRelationType(
                  event.target.value as "supersedes" | "revises" | "relates_to",
                )
              }
            >
              <option value="relates_to">Relates to</option>
              <option value="revises">Revises</option>
              <option value="supersedes">Supersedes</option>
            </select>
          </label>
          <label>
            Rationale
            <textarea
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
              rows={2}
            />
          </label>
          <button type="submit" disabled={savingRelation || !targetId}>
            {savingRelation ? "Confirming…" : "Confirm relationship"}
          </button>
        </form>
      </section>
    </section>
  );
}
