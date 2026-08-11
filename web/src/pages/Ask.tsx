import { type FormEvent, useState } from "react";

import { answerQuestion } from "../api/client";
import type { QuestionResponse } from "../api/types";
import { CitationList } from "../components/CitationList";
import { RetrievalTrace } from "../components/RetrievalTrace";

type DisplayError = {
  message: string;
  requestId: string | null;
};

function errorDetails(error: unknown): DisplayError {
  if (error instanceof Error) {
    const requestId =
      "requestId" in error && typeof error.requestId === "string"
        ? error.requestId
        : null;
    return { message: error.message, requestId };
  }
  return { message: "Question could not be answered.", requestId: null };
}

export function Ask() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<QuestionResponse | null>(null);
  const [error, setError] = useState<DisplayError | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = question.trim();
    if (!normalized || loading) return;

    setLoading(true);
    setResult(null);
    setError(null);
    try {
      setResult(await answerQuestion(normalized));
    } catch (caught) {
      setError(errorDetails(caught));
    } finally {
      setLoading(false);
    }
  };

  const citationNumbers = new Map(
    result?.citations.map(
      (citation, index) => [citation.passage_id, index + 1] as const,
    ),
  );

  return (
    <section className="ask-page" aria-labelledby="ask-title">
      <header className="ask-header">
        <p className="eyebrow">Evidence-backed answers</p>
        <h1 id="ask-title">Ask your project memory</h1>
        <p className="page-description">
          Ask what changed, why it changed, who owned the call, and whether later
          evidence superseded it.
        </p>
      </header>

      <form className="question-form" onSubmit={submit}>
        <label htmlFor="project-question">Ask about project decisions</label>
        <div>
          <textarea
            id="project-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Why was authentication postponed, and was it later changed?"
            rows={3}
            maxLength={2_000}
          />
          <button type="submit" disabled={loading || !question.trim()}>
            {loading ? "Asking…" : "Ask"}
          </button>
        </div>
      </form>

      {error && (
        <div className="answer-error" role="alert">
          <strong>{error.message}</strong>
          {error.requestId && <span>Request ID: {error.requestId}</span>}
        </div>
      )}

      {result && (
        <article className="answer-card" aria-labelledby="answer-title">
          <div className="answer-card__heading">
            <div>
              <p className="eyebrow">Response</p>
              <h2 id="answer-title">Answer</h2>
            </div>
            <div className="answer-state">
              <strong className={`answer-state--${result.state}`}>{result.state}</strong>
              <span>{result.confidence} confidence</span>
            </div>
          </div>

          <p className="answer-text">{result.answer}</p>

          {result.claims.length > 0 && (
            <ol className="answer-claims" aria-label="Answer claims">
              {result.claims.map((claim, index) => {
                const numbers = claim.passage_ids
                  .map((passageId) => citationNumbers.get(passageId))
                  .filter((number): number is number => number !== undefined);
                return (
                  <li key={`${claim.text}-${index}`}>
                    {claim.text}{" "}
                    {numbers.map((number) => `[${number}]`).join("")}
                  </li>
                );
              })}
            </ol>
          )}

          {result.conflicts.length > 0 && (
            <div className="conflict-warning" role="alert">
              <strong>Conflicting evidence</strong>
              <span>
                Sources disagree about:{" "}
                {result.conflicts.map((conflict) => conflict.facet).join(", ")}.
              </span>
            </div>
          )}

          {result.unsupported_facets.length > 0 && (
            <aside className="unsupported-facets">
              <strong>Unsupported by current evidence</strong>
              <ul>
                {result.unsupported_facets.map((facet) => (
                  <li key={facet}>{facet}</li>
                ))}
              </ul>
            </aside>
          )}

          <CitationList citations={result.citations} />
          <RetrievalTrace traceId={result.trace_id} />
        </article>
      )}
    </section>
  );
}
