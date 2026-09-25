from decision_assistant.errors import ApplicationError


class EvaluationApiError(ApplicationError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            retryable=False,
        )


class FatalEvaluationError(ApplicationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=503,
            retryable=False,
        )
