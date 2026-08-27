import { type FormEvent, useEffect, useState } from "react";

import {
  answerQuestion,
  getQuestionHistoryItem,
  listQuestionHistory,
} from "../api/client";
import type {
  QuestionHistoryListResponse,
  QuestionHistorySummary,
  QuestionResponse,
} from "../api/types";
import { CitationList } from "../components/CitationList";
import { RetrievalTrace } from "../components/RetrievalTrace";
import "./Ask.css";

const HISTORY_PAGE_SIZE = 5;
const SEARCH_DEBOUNCE_MS = 250;

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
  const [loadingHistoryId, setLoadingHistoryId] = useState<string | null>(null);

  const [history, setHistory] = useState<QuestionHistoryListResponse | null>(null);
  const [historySearch, setHistorySearch] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyPage, setHistoryPage] = useState(1);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setHistoryPage(1);
      setHistoryQuery(historySearch.trim());
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [historySearch]);

  useEffect(() => {
    let ignore = false;
    setHistoryLoading(true);
    setHistoryError(false);
    void listQuestionHistory(historyQuery, historyPage, HISTORY_PAGE_SIZE)
      .then((response) => {
        if (!ignore) setHistory(response);
      })
      .catch(() => {
        if (!ignore) setHistoryError(true);
      })
      .finally(() => {
        if (!ignore) setHistoryLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [historyPage, historyQuery, historyRefresh]);

  const refreshHistory = () => {
    setHistorySearch("");
    setHistoryQuery("");
    setHistoryPage(1);
    setHistoryRefresh((value) => value + 1);
  };

  const ask = async (forceRefresh = false) => {
    const normalized = question.trim();
    if (!normalized || loading) return;

    setLoading(true);
    setResult(null);
    setError(null);
    try {
      setResult(await answerQuestion(normalized, forceRefresh));
      refreshHistory();
    } catch (caught) {
      setError(errorDetails(caught));
    } finally {
      setLoading(false);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void ask();
  };

  const restoreHistoryItem = async (item: QuestionHistorySummary) => {
    if (loadingHistoryId) return;
    setLoadingHistoryId(item.id);
    setError(null);
    try {
      const saved = await getQuestionHistoryItem(item.id);
      setQuestion(item.question);
      setResult(saved);
    } catch (caught) {
      setError(errorDetails(caught));
    } finally {
      setLoadingHistoryId(null);
    }
  };

  const citationNumbers = new Map(
    result?.citations.map(
      (citation, index) => [citation.passage_id, index + 1] as const,
    ),
  );
  const historyItems = history?.items ?? [];

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

          {(result.cached || result.stale) && (
            <div
              className={`cached-answer-status${
                result.stale ? " cached-answer-status--stale" : ""
              }`}
            >
              <span>
                {result.stale
                  ? "Corpus changed since this answer was generated."
                  : "Saved answer — no model tokens used."}
              </span>
              <button
                type="button"
                onClick={() => void ask(true)}
                disabled={loading}
              >
                {loading ? "Asking…" : "Ask again"}
              </button>
            </div>
          )}

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
                    {numbers.map((number) => (
                      <a
                        key={number}
                        href={`#citation-${number}`}
                        aria-label={`View citation ${number}`}
                      >
                        [{number}]
                      </a>
                    ))}
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

      {loading && (
        <div className="answer-loading" role="status" aria-live="polite">
          <strong>Searching workspace evidence…</strong>
          <span>Checking decisions, sources, and possible conflicts.</span>
          <span className="answer-loading__bar" aria-hidden="true" />
        </div>
      )}

      <section
        className="question-history question-history--secondary"
        aria-labelledby="question-history-title"
      >
        <div className="question-history__heading">
          <div>
            <p className="eyebrow">Saved in this workspace</p>
            <h2 id="question-history-title">Previous questions</h2>
          </div>
          <label>
            <span>Search previous questions</span>
            <input
              type="search"
              value={historySearch}
              onChange={(event) => setHistorySearch(event.target.value)}
              placeholder="Search questions"
            />
          </label>
        </div>

        {historyError ? (
          <div className="question-history__error" role="alert">
            <span>Previous questions could not be loaded.</span>
            <button
              type="button"
              onClick={() => setHistoryRefresh((value) => value + 1)}
            >
              Try again
            </button>
          </div>
        ) : historyLoading && history === null ? (
          <p className="question-history__empty" role="status">
            Loading previous questions…
          </p>
        ) : historyItems.length > 0 ? (
          <ol aria-label="Previous questions" aria-busy={historyLoading}>
            {historyItems.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  aria-label={item.question}
                  disabled={loadingHistoryId === item.id}
                  onClick={() => void restoreHistoryItem(item)}
                >
                  <span className="question-history__question">
                    <strong>{item.question}</strong>
                    <small>
                      {item.state ?? "unavailable"}
                      {item.confidence ? ` · ${item.confidence} confidence` : ""}
                      {item.stale ? " · corpus changed" : ""}
                    </small>
                  </span>
                  <time dateTime={item.last_asked_at}>
                    {new Date(item.last_asked_at).toLocaleString()}
                  </time>
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="question-history__empty">
            {historyQuery ? "No matching questions." : "No previous questions yet."}
          </p>
        )}

        {history && history.total_pages > 1 && (
          <nav
            className="question-history__pagination"
            aria-label="Question history pages"
          >
            <button
              type="button"
              disabled={historyLoading || history.page <= 1}
              onClick={() => setHistoryPage((page) => Math.max(1, page - 1))}
            >
              Previous page
            </button>
            <span>
              Page {history.page} of {history.total_pages}
            </span>
            <button
              type="button"
              disabled={historyLoading || history.page >= history.total_pages}
              onClick={() => setHistoryPage((page) => page + 1)}
            >
              Next page
            </button>
          </nav>
        )}
      </section>
    </section>
  );
}
