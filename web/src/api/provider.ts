import { ApiClientError, apiRequest, projectPath } from "./client";
import type { CorpusRebuildStatus } from "./types";

/**
 * The provider surface (T048/T050, US6): which provider is active, what it does with document text,
 * and the switch that can force a corpus rebuild.
 *
 * These types live here rather than in `types.ts` because that module is already at the repository's
 * 500-line source cap (AGENTS.md); this feature keeps one home instead of taxing a shared file.
 */

export type ProviderName = "gemini" | "ollama";

export type ProviderDisclosure = {
  /** The generation provider's name — what turns document text into answers. */
  provider: string;
  /** Which provider builds the search index, and which generates answers (named separately so a
   * mixed configuration can be disclosed accurately, V146). */
  generation_provider: string;
  embedding_provider: string;
  generation_sends_document_text_remotely: boolean;
  embedding_sends_document_text_remotely: boolean;
  /** True when *any* configured provider can send document text off this machine. */
  sends_document_text_remotely: boolean;
  acknowledged_at: string | null;
};

export type ProviderSwitchRequest = {
  generation_provider: ProviderName;
  embedding_provider: ProviderName;
  confirm_rebuild: boolean;
};

export type ProviderConfigResponse = {
  generation_provider: string;
  embedding_provider: string;
  embedding_profile_changed: boolean;
  documents_total: number;
  /** DB65: this switch started sending document text off the machine, so every workspace's
   * acknowledgement was cleared and uploads stay blocked until the user acknowledges again. */
  disclosure_acknowledgement_cleared: boolean;
  rebuild: CorpusRebuildStatus | null;
};

/** One workspace's contribution to the switch preview. */
export type ProviderWorkspaceCount = {
  name: string;
  documentsTotal: number;
};

/** What a 409 `provider_switch_requires_rebuild` says before the operator has confirmed. */
export type ProviderSwitchPreview = {
  documentsTotal: number | null;
  /** DB57: the provider choice is process-wide, so the preview names every workspace it re-ingests,
   * not only the addressed one. */
  workspaces: ProviderWorkspaceCount[];
  currentEmbeddingProfile: Record<string, unknown> | null;
  proposedEmbeddingProfile: Record<string, unknown> | null;
  /** DB65: this switch will clear the data-handling acknowledgement. */
  disclosureAcknowledgementWillBeCleared: boolean;
};

export function getProviderDisclosure(): Promise<ProviderDisclosure> {
  return apiRequest<ProviderDisclosure>(projectPath("/provider-disclosure"));
}

/** Records the disclosure ack the upload guard (T049) requires. Idempotent server-side. */
export function acknowledgeProviderDisclosure(): Promise<ProviderDisclosure> {
  return apiRequest<ProviderDisclosure>(projectPath("/provider-disclosure/ack"), {
    method: "POST",
  });
}

export function switchProvider(
  request: ProviderSwitchRequest,
): Promise<ProviderConfigResponse> {
  return apiRequest<ProviderConfigResponse>(projectPath("/provider"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  });
}

function asProfile(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * The pending-rebuild preview, or `null` when this error is not the confirmation gate. T052 renders
 * the dialog from this, so the two numbers it shows come from the server's own answer rather than a
 * second client-side guess about what the profile change means.
 */
export function providerSwitchPreview(error: unknown): ProviderSwitchPreview | null {
  if (!(error instanceof ApiClientError)) return null;
  if (error.code !== "provider_switch_requires_rebuild") return null;
  const details = asProfile(error.details);
  const documentsTotal = details?.documents_total;
  const rawWorkspaces = details?.workspaces;
  const workspaces: ProviderWorkspaceCount[] = Array.isArray(rawWorkspaces)
    ? rawWorkspaces.flatMap((item) => {
        const entry = asProfile(item);
        if (!entry || typeof entry.name !== "string") return [];
        return [
          {
            name: entry.name,
            documentsTotal:
              typeof entry.documents_total === "number" ? entry.documents_total : 0,
          },
        ];
      })
    : [];
  return {
    documentsTotal: typeof documentsTotal === "number" ? documentsTotal : null,
    workspaces,
    currentEmbeddingProfile: asProfile(details?.current_embedding_profile),
    proposedEmbeddingProfile: asProfile(details?.proposed_embedding_profile),
    disclosureAcknowledgementWillBeCleared:
      details?.disclosure_acknowledgement_will_be_cleared === true,
  };
}
