"""Errors the document API raises.

Defined here rather than in `documents/service.py` (DB67) so the read model in
`documents/queries.py` can raise the same `404` without importing the service back. `service.py`
imports both names, so `from decision_assistant.documents.service import DocumentApiError` keeps
working.
"""

from decision_assistant.errors import ApplicationError


class DocumentApiError(ApplicationError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            retryable=False,
        )


class DisclosureNotAcknowledged(DocumentApiError):
    """FR-014: no upload before the user has acknowledged where document text goes."""

    def __init__(self) -> None:
        super().__init__(
            code="disclosure_not_acknowledged",
            message=(
                "Acknowledge the provider disclosure for this workspace before "
                "uploading documents"
            ),
            status_code=409,
        )
