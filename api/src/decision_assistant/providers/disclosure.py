"""Which provider is active and whether document text leaves this machine (T048, US6/FR-014).

The first-run disclosure screen and the upload guard (T049) both need this answer, and it must
come from configuration the app already validated at startup, not from a second source of truth.
"""

from decision_assistant.config import Settings

#: Providers that never send document content off the machine. Everything else counts as remote,
#: so an unfamiliar or newly added provider name fails toward disclosing more, not less.
OFFLINE_PROVIDERS = frozenset({"ollama"})


def active_provider(settings: Settings) -> str:
    """The provider name the disclosure UI shows.

    The generation provider, because that is what turns document text into answers; the embedding
    provider is reported separately through `sends_document_text_remotely` (a workspace can embed
    locally and still generate remotely).
    """
    return settings.generation_provider


def provider_is_remote(name: str) -> bool:
    """True when a single provider can send document text off this machine.

    Only names known to be offline count as offline; anything else fails toward disclosing more.
    """
    return name not in OFFLINE_PROVIDERS


def sends_document_text_remotely(settings: Settings) -> bool:
    """True when any configured provider can send document text off this machine."""
    return any(
        provider_is_remote(name)
        for name in (settings.generation_provider, settings.embedding_provider)
    )
