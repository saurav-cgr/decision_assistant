"""Errors the ingestion layer raises.

`IngestionError` used to be defined in `ingestion/service.py`. It moved here so the modules
`IngestionService` delegates to — the embedding cache and decision persistence — can raise it
without importing the service back (DB67). `ingestion.service` imports the name, so
`from decision_assistant.ingestion.service import IngestionError` keeps working.
"""

from decision_assistant.errors import ApplicationError


class IngestionError(ApplicationError):
    def __init__(self, message: str, *, code: str = "ingestion_failed") -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=422,
            retryable=False,
        )
