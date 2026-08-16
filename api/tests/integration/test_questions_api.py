from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from decision_assistant.answering.router import (
    get_answer_service,
    get_question_history_service,
)
from decision_assistant.answering.schemas import (
    AnswerState,
    ConfidenceCategory,
    QuestionAnswerResponse,
    QuestionHistoryListResponse,
    QuestionHistorySummary,
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
HISTORY_ID = UUID("55555555-5555-4555-8555-555555555555")
ANSWERED_AT = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


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


class StubQuestionHistoryService:
    async def answer(
        self,
        request: QuestionRequest,
        *,
        answer_service: StubAnswerService,
        request_id: str,
        workspace_id: UUID,
    ) -> QuestionAnswerResponse:
        assert request.question == "Why was authentication postponed?"
        assert request.force_refresh is True
        assert isinstance(answer_service, StubAnswerService)
        assert request_id == "question-request"
        assert workspace_id == WORKSPACE_ID
        return QuestionAnswerResponse(
            answer="Insufficient evidence to answer that question.",
            state=AnswerState.ABSTAINED,
            confidence=ConfidenceCategory.NONE,
            unsupported_facets=["why authentication was postponed"],
            trace_id=TRACE_ID,
            history_id=HISTORY_ID,
            answered_at=ANSWERED_AT,
            cached=False,
            stale=False,
        )

    async def list_history(
        self,
        *,
        workspace_id: UUID,
        query: str | None,
        page: int,
        page_size: int,
    ) -> QuestionHistoryListResponse:
        assert workspace_id == WORKSPACE_ID
        assert query == "authentication"
        assert page == 2
        assert page_size == 5
        return QuestionHistoryListResponse(
            items=[
                QuestionHistorySummary(
                    id=HISTORY_ID,
                    question="Why was authentication postponed?",
                    state=AnswerState.ABSTAINED,
                    confidence=ConfidenceCategory.NONE,
                    answered_at=ANSWERED_AT,
                    last_asked_at=ANSWERED_AT,
                    stale=False,
                )
            ],
            page=2,
            page_size=5,
            total=6,
            total_pages=2,
        )

    async def get_history_item(
        self,
        history_id: UUID,
        *,
        workspace_id: UUID,
    ) -> QuestionAnswerResponse:
        assert history_id == HISTORY_ID
        assert workspace_id == WORKSPACE_ID
        return QuestionAnswerResponse(
            answer="Insufficient evidence to answer that question.",
            state=AnswerState.ABSTAINED,
            confidence=ConfidenceCategory.NONE,
            unsupported_facets=["why authentication was postponed"],
            trace_id=TRACE_ID,
            history_id=HISTORY_ID,
            answered_at=ANSWERED_AT,
            cached=True,
            stale=True,
        )


def test_questions_api_returns_explicit_abstention_and_trace_id() -> None:
    app = create_app()
    app.dependency_overrides[get_answer_service] = lambda: StubAnswerService()
    app.dependency_overrides[get_question_history_service] = (
        lambda: StubQuestionHistoryService()
    )
    app.dependency_overrides[get_workspace_context] = (
        lambda: WorkspaceContext(workspace_id=WORKSPACE_ID)
    )

    response = TestClient(app).post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/questions",
        headers={"x-request-id": "question-request"},
        json={
            "question": "Why was authentication postponed?",
            "force_refresh": True,
        },
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
        "history_id": str(HISTORY_ID),
        "answered_at": "2026-08-16T10:00:00Z",
        "cached": False,
        "stale": False,
    }


def test_questions_history_api_returns_page_metadata() -> None:
    app = create_app()
    app.dependency_overrides[get_question_history_service] = (
        lambda: StubQuestionHistoryService()
    )
    app.dependency_overrides[get_workspace_context] = (
        lambda: WorkspaceContext(workspace_id=WORKSPACE_ID)
    )

    response = TestClient(app).get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/questions/history",
        params={"query": "authentication", "page": 2, "page_size": 5},
    )

    assert response.status_code == 200
    assert response.json()["page"] == 2
    assert response.json()["page_size"] == 5
    assert response.json()["total"] == 6
    assert response.json()["total_pages"] == 2
    assert response.json()["items"][0]["id"] == str(HISTORY_ID)


def test_question_history_detail_returns_saved_answer() -> None:
    app = create_app()
    app.dependency_overrides[get_question_history_service] = (
        lambda: StubQuestionHistoryService()
    )
    app.dependency_overrides[get_workspace_context] = (
        lambda: WorkspaceContext(workspace_id=WORKSPACE_ID)
    )

    response = TestClient(app).get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/questions/history/{HISTORY_ID}"
    )

    assert response.status_code == 200
    assert response.json()["history_id"] == str(HISTORY_ID)
    assert response.json()["cached"] is True
    assert response.json()["stale"] is True
