import { type FormEvent, useEffect, useState } from "react";

import { correctDecision } from "../api/client";
import type {
  DecisionDetail,
  DecisionFieldName,
  DecisionCorrectionRequest,
} from "../api/types";

const editableFields: Array<{ value: DecisionFieldName; label: string }> = [
  { value: "statement", label: "Decision statement" },
  { value: "effective_date", label: "Effective date" },
  { value: "owner", label: "Owner" },
  { value: "status", label: "Status" },
  { value: "reasons", label: "Reasons" },
  { value: "alternatives", label: "Alternatives" },
  { value: "project", label: "Project" },
  { value: "topic", label: "Topic" },
];

type DecisionEditorProps = {
  decision: DecisionDetail;
  onSaved: (decision: DecisionDetail) => void;
};

function editableValue(decision: DecisionDetail, field: DecisionFieldName): string {
  const value = decision[field];
  if (Array.isArray(value)) return value.join("\n");
  return value === null ? "" : String(value);
}

function requestValue(field: DecisionFieldName, value: string): unknown {
  if (field === "reasons" || field === "alternatives") {
    return value
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  if (field === "effective_date" && !value.trim()) return null;
  return value.trim();
}

export function DecisionEditor({ decision, onSaved }: DecisionEditorProps) {
  const [field, setField] = useState<DecisionFieldName>("statement");
  const [value, setValue] = useState(() => editableValue(decision, "statement"));
  const [supportState, setSupportState] = useState<"supported" | "unsupported">(
    "supported",
  );
  const [selectedPassages, setSelectedPassages] = useState<string[]>([]);
  const [confirmingUnsupported, setConfirmingUnsupported] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValue(editableValue(decision, field));
    setSelectedPassages([]);
    setConfirmingUnsupported(false);
    setError(null);
  }, [decision, field]);

  const buildRequest = (): DecisionCorrectionRequest => ({
    changes: [
      {
        field_name: field,
        value: requestValue(field, value),
        support_state: supportState,
        evidence:
          supportState === "supported"
            ? decision.evidence
                .filter((evidence) => selectedPassages.includes(evidence.passage_id))
                .map((evidence) => ({
                  passage_id: evidence.passage_id,
                  start_offset: evidence.start_offset,
                  end_offset: evidence.end_offset,
                  content_hash: evidence.content_hash,
                }))
            : [],
      },
    ],
  });

  const save = async () => {
    if (supportState === "supported" && selectedPassages.length === 0) {
      setError("Select at least one supporting source passage.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onSaved(await correctDecision(decision.id, buildRequest()));
      setConfirmingUnsupported(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Correction could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (supportState === "unsupported") {
      setConfirmingUnsupported(true);
      return;
    }
    void save();
  };

  return (
    <section className="decision-editor" aria-labelledby="correction-title">
      <div className="section-heading">
        <p className="eyebrow">Human review</p>
        <h2 id="correction-title">Correct this decision</h2>
      </div>
      <form onSubmit={submit}>
        <label>
          Field to correct
          <select
            value={field}
            onChange={(event) => setField(event.target.value as DecisionFieldName)}
          >
            {editableFields.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          New value
          <textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            rows={field === "statement" || Array.isArray(decision[field]) ? 3 : 1}
          />
        </label>

        <fieldset>
          <legend>Evidence support</legend>
          <label>
            <input
              type="radio"
              name="support-state"
              checked={supportState === "supported"}
              onChange={() => setSupportState("supported")}
            />
            Supported by source evidence
          </label>
          <label>
            <input
              type="radio"
              name="support-state"
              checked={supportState === "unsupported"}
              onChange={() => {
                setSupportState("unsupported");
                setSelectedPassages([]);
              }}
            />
            Not supported by source evidence
          </label>
        </fieldset>

        {supportState === "supported" && (
          <fieldset>
            <legend>Select supporting passages</legend>
            {decision.evidence.map((evidence, index) => (
              <label key={evidence.passage_id}>
                <input
                  type="checkbox"
                  checked={selectedPassages.includes(evidence.passage_id)}
                  onChange={(event) =>
                    setSelectedPassages((current) =>
                      event.target.checked
                        ? [...current, evidence.passage_id]
                        : current.filter((id) => id !== evidence.passage_id),
                    )
                  }
                  aria-label={`Use evidence: ${evidence.quote}`}
                />
                <span>
                  Passage {index + 1} — {evidence.quote}
                </span>
              </label>
            ))}
          </fieldset>
        )}

        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={saving || !value.trim()}>
          {saving ? "Saving…" : "Save correction"}
        </button>
      </form>

      {confirmingUnsupported && (
        <div className="unsupported-confirmation" role="alert">
          <strong>No source evidence selected</strong>
          <p>
            This change will be stored as unsupported and clearly marked for review.
          </p>
          <div>
            <button type="button" onClick={() => void save()} disabled={saving}>
              Confirm unsupported correction
            </button>
            <button type="button" onClick={() => setConfirmingUnsupported(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
