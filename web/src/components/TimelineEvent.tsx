import { documentDetailUrl } from "../api/client";
import type { TimelineEntry } from "../api/types";

type TimelineEventProps = {
  entry: TimelineEntry;
};

function label(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function TimelineEvent({ entry }: TimelineEventProps) {
  return (
    <li className="timeline-event">
      <article aria-labelledby={`timeline-${entry.decision_id}`}>
        <div className="timeline-marker" aria-hidden="true" />
        <div className="timeline-event__body">
          <div className="timeline-event__meta">
            <time dateTime={entry.display_date || undefined}>
              {entry.display_date || "Date unknown"}
            </time>
            {entry.date_is_fallback && <span>Document date</span>}
            <strong className={`timeline-status timeline-status--${entry.display_status}`}>
              {label(entry.display_status)}
            </strong>
          </div>
          <h2 id={`timeline-${entry.decision_id}`}>{entry.statement}</h2>
          <p>
            {entry.owner || "Owner unknown"}
            {entry.project ? ` · ${entry.project}` : ""}
          </p>

          {entry.relationships.map((relationship, index) => (
            <div
              className={`timeline-relation timeline-relation--${relationship.authority}`}
              key={`${relationship.source_decision_id}-${relationship.target_decision_id}-${index}`}
            >
              <strong>
                {relationship.label === "possible_revision"
                  ? "Possible revision"
                  : label(relationship.label)}
              </strong>
              {relationship.confidence && (
                <span>{relationship.confidence} confidence</span>
              )}
              {relationship.authority === "user_confirmed" && (
                <span>Team confirmed</span>
              )}
              {relationship.rationale && <p>{relationship.rationale}</p>}
            </div>
          ))}

          <div className="timeline-evidence">
            {entry.evidence.map((evidence) => (
              <a
                key={evidence.passage_id}
                href={documentDetailUrl(evidence.document_id)}
                target="_blank"
                rel="noreferrer"
                aria-label="View source evidence"
              >
                View source evidence
              </a>
            ))}
          </div>
        </div>
      </article>
    </li>
  );
}
