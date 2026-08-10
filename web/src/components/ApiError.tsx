import { Component, type ErrorInfo, type ReactNode } from "react";

import { ApiClientError } from "../api/client";

type ApiErrorMessageProps = {
  error: unknown;
};

export function ApiErrorMessage({ error }: ApiErrorMessageProps) {
  const apiError = error instanceof ApiClientError ? error : null;
  return (
    <section className="error-panel" role="alert">
      <p className="eyebrow">Request failed</p>
      <h1>{apiError?.message ?? "Something interrupted this view"}</h1>
      <p>
        {apiError?.retryable
          ? "Local service may be temporarily unavailable. Try again shortly."
          : "Review the request or return to the workspace."}
      </p>
      {apiError?.requestId ? (
        <p className="request-id">Request ID: {apiError.requestId}</p>
      ) : null}
      <a className="button-link" href="/">
        Return to workspace
      </a>
    </section>
  );
}

type BoundaryProps = { children: ReactNode };
type BoundaryState = { error: unknown | null };

export class ApiErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): BoundaryState {
    return { error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("Decision Assistant render failed", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return <ApiErrorMessage error={this.state.error} />;
    }
    return this.props.children;
  }
}
