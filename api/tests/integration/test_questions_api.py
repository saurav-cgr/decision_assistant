from uuid import UUID

from fastapi.testclient import TestClient

from decision_assistant.answering.router import get_answer_service
from decision_assistant.answering.schemas import (
    AnswerState,
    ConfidenceCategory,
    QuestionRequest,
    QuestionResponse,
)
from decision_assistant.main import create_app
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)


TRACE_ID = UUID("33333333-3333-3333-3333-333333333333")
WORKSPACE_ID = UUID("44444444-4444-4444-4444-444444444444")


class StubAnswerService:
    async def answer(
        self,
        request: QuestionRequest,
        *,
        request_id: str,
        workspace_id: UUID | None = None,
    ) -> QuestionResponse:
        assert request.question == "Why was authentication postponed?"
        assert request_id == "question-request"
        return QuestionResponse(
            answer="Insufficient evidence to answer that question.",
            state=AnswerState.ABSTAINED,
            confidence=ConfidenceCategory.NONE,
            claims=[],
            citations=[],
            conflicts=[],
            unsupported_facets=["why authentication was postponed"],
            trace_id=TRACE_ID,
        )


def test_questions_api_returns_explicit_abstention_and_trace_id() -> None:
    app = create_app()
    app.dependency_overrides[get_answer_service] = lambda: StubAnswerService()
    app.dependency_overrides[get_workspace_context] = (
        lambda: WorkspaceContext(workspace_id=WORKSPACE_ID)
    )

    response = TestClient(app).post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/questions",
        headers={"x-request-id": "question-request"},
        json={"question": "Why was authentication postponed?"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Insufficient evidence to answer that question.",
        "state": "abstained",
        "confidence": "none",
        "claims": [],
        "citations": [],
        "conflicts": [],
        "unsupported_facets": ["why authentication was postponed"],
        "trace_id": str(TRACE_ID),
    }
