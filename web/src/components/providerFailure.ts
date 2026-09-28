/**
 * T067 (FR-026): a clear, specific, actionable state for a provider failure — the two the task names
 * are a missing/invalid provider API key and an unreachable provider.
 *
 * One table, used wherever a provider call can fail (question answering, ingestion, the provider
 * switch), so the same failure reads the same way everywhere instead of surfacing a generic message
 * or a raw server string. The codes are the ones `providers/base.py` raises.
 */

type ProviderFailure = {
  title: string;
  guidance: string;
};

const PROVIDER_FAILURES: Record<string, ProviderFailure> = {
  provider_authentication_failed: {
    title: "The provider rejected this install's API key",
    guidance:
      "Set a valid GEMINI_API_KEY in .env and run `make start` so the API picks it up.",
  },
  provider_configuration_invalid: {
    title: "This provider is not configured",
    guidance:
      "Fill in the provider's key or base URL in .env and run `make start`, then try again.",
  },
  provider_unavailable: {
    title: "The model provider is unreachable",
    guidance:
      "If this install uses ollama, confirm the service is running and OLLAMA_BASE_URL points at it, then try again.",
  },
  provider_quota_exhausted: {
    title: "The provider account's quota is exhausted",
    guidance:
      "Restore the quota in the provider account; until then this install cannot index or answer.",
  },
  provider_rate_limited: {
    title: "The provider is rate limiting this install",
    guidance: "Wait a moment and try again.",
  },
  provider_response_invalid: {
    title: "The provider returned an unusable response",
    guidance:
      "Try again; if it keeps happening, download the diagnostics bundle from Account and check the logs.",
  },
  provider_schema_unsupported: {
    title: "The provider does not support the required response format",
    guidance:
      "Switch to a provider or model this install can constrain to the answer schema (see docs/providers.md).",
  },
  provider_input_too_large: {
    title: "The request was too large for the provider",
    guidance: "Try a shorter question, or reduce the amount of evidence in play.",
  },
  provider_switch_not_configured: {
    title: "That provider is not configured on this install",
    guidance:
      "Set its credentials in .env and run `make start` before switching to it (see docs/providers.md).",
  },
  corpus_rebuild_in_progress: {
    title: "A corpus rebuild is already running",
    guidance:
      "Wait for it to finish — or retry it if it failed — before switching providers.",
  },
};

/**
 * `"Title — guidance"` for a known provider failure code, or `null` when the code is not one.
 */
export function providerFailureText(code: string | null | undefined): string | null {
  if (!code) return null;
  const failure = PROVIDER_FAILURES[code];
  return failure ? `${failure.title} — ${failure.guidance}` : null;
}

/**
 * The same text for a thrown error, when that error carries a provider failure code.
 *
 * Reads `code` structurally rather than with `instanceof ApiClientError` on purpose: every API
 * failure the UI sees *is* an `ApiClientError`, but tests mock the API client module with a partial
 * factory, and an `instanceof` against an undefined binding throws instead of returning false.
 */
export function providerFailureMessage(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const code = (error as { code?: unknown }).code;
  return typeof code === "string" ? providerFailureText(code) : null;
}
