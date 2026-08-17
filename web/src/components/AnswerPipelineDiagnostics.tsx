type AnswerPipelineDiagnosticsProps = {
  value: Record<string, unknown> | null;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.flatMap((item) => {
        const record = asRecord(item);
        return record ? [record] : [];
      })
    : [];
}

function label(value: unknown): string {
  return typeof value === "string"
    ? value.replaceAll("_", " ")
    : "not recorded";
}

function DiagnosticIssues({
  title,
  values,
}: {
  title: string;
  values: Record<string, unknown>[];
}) {
  if (values.length === 0) return null;
  return (
    <div className="evaluation-citation-diagnostics">
      <h5>{title}</h5>
      <ul>
        {values.map((item, index) => (
          <li key={`${String(item.code || item.reason || "issue")}-${index}`}>
            <strong>{label(item.code || item.reason)}</strong>
            {item.passage_id ? ` — passage ${String(item.passage_id)}` : ""}
            {item.message ? ` — ${String(item.message)}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

function CandidateDetails({
  label: summary,
  value,
}: {
  label: string;
  value: unknown;
}) {
  if (!asRecord(value)) return null;
  return (
    <details>
      <summary>{summary}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export function AnswerPipelineDiagnostics({
  value,
}: AnswerPipelineDiagnosticsProps) {
  if (!value) {
    return (
      <div className="evaluation-citation-diagnostics">
        <h4>Answer pipeline</h4>
        <p>Pipeline diagnostics were not stored for this run.</p>
      </div>
    );
  }

  const initialErrors = asRecords(value.verifier_errors);
  const repairErrors = asRecords(value.repair_verifier_errors);
  const dropped = asRecords(value.dropped_citations);
  const repairDropped = asRecords(value.repair_dropped_citations);

  return (
    <div className="evaluation-citation-diagnostics">
      <h4>Answer pipeline</h4>
      <dl>
        <div>
          <dt>Outcome reason</dt>
          <dd>{label(value.outcome_reason)}</dd>
        </div>
        <div>
          <dt>Generation attempts</dt>
          <dd>{String(value.generation_attempt_count ?? "not recorded")}</dd>
        </div>
        <div>
          <dt>Repair attempted</dt>
          <dd>{value.repair_attempted === true ? "yes" : "no"}</dd>
        </div>
        <div>
          <dt>Repair failure</dt>
          <dd>{label(value.repair_failure)}</dd>
        </div>
      </dl>
      <DiagnosticIssues title="Initial verifier errors" values={initialErrors} />
      <DiagnosticIssues title="Initial dropped citations" values={dropped} />
      <DiagnosticIssues title="Repair verifier errors" values={repairErrors} />
      <DiagnosticIssues title="Repair dropped citations" values={repairDropped} />
      <CandidateDetails label="Initial structured candidate" value={value.raw_candidate} />
      <CandidateDetails label="Repaired structured candidate" value={value.repair_candidate} />
    </div>
  );
}
