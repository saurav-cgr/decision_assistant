import { type FormEvent, useState } from "react";

import "./Timeline.css";

import { getTimeline } from "../api/client";
import type { TimelineResponse } from "../api/types";
import { TimelineEvent } from "../components/TimelineEvent";

export function Timeline() {
  const [topic, setTopic] = useState("");
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = topic.trim();
    if (!normalized || loading) return;
    setLoading(true);
    setError(null);
    setTimeline(null);
    try {
      const response = await getTimeline(normalized);
      setTimeline({
        ...response,
        entries: [...response.entries].sort((left, right) => {
          if (!left.display_date && !right.display_date) return 0;
          if (!left.display_date) return 1;
          if (!right.display_date) return -1;
          return left.display_date.localeCompare(right.display_date);
        }),
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Timeline could not be loaded.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="timeline-page" aria-labelledby="timeline-title">
      <header>
        <p className="eyebrow">Decision history</p>
        <h1 id="timeline-title">Follow a decision through time</h1>
        <p className="page-description">
          See proposals, accepted choices, revisions, and superseded decisions
          with source evidence for every authoritative event.
        </p>
      </header>

      <form className="timeline-form" onSubmit={submit}>
        <label>
          Timeline topic
          <input
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="Authentication"
          />
        </label>
        <button type="submit" disabled={loading || !topic.trim()}>
          {loading ? "Building…" : "Build timeline"}
        </button>
      </form>

      {error && <p className="answer-error" role="alert">{error}</p>}

      {timeline && (
        <section className="timeline-results" aria-labelledby="timeline-topic-title">
          <div className="section-heading">
            <p className="eyebrow">Chronological evidence</p>
            <h2 id="timeline-topic-title">{timeline.topic}</h2>
          </div>
          <div className="timeline-legend" aria-label="Timeline evidence legend">
            <span>
              <i className="timeline-legend__marker timeline-legend__marker--confirmed" aria-hidden="true" />
              Source-confirmed
            </span>
            <span>
              <i className="timeline-legend__marker timeline-legend__marker--inferred" aria-hidden="true" />
              Model-inferred link · review before relying
            </span>
          </div>
          {timeline.entries.length > 0 ? (
            <ol className="timeline-list" aria-label="Decision timeline">
              {timeline.entries.map((entry) => (
                <TimelineEvent key={entry.decision_id} entry={entry} />
              ))}
            </ol>
          ) : (
            <p>No supported decisions found for this topic.</p>
          )}
        </section>
      )}
    </section>
  );
}
