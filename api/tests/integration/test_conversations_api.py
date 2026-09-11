from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from decision_assistant.answering.conversation_service import ConversationService
from decision_assistant.answering.router import (
    get_answer_service,
    get_conversation_service,
)
from decision_assistant.answering.schemas import (
    AnswerState,
    ConfidenceCategory,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    QuestionRequest,
    QuestionResponse,
)
from decision_assistant.main import create_app
from decision_assistant.workspace.context import (
    WorkspaceContext,
    get_workspace_context,
)


TRACE_ID = UUID("33333333-3333-3333-3333-333333333333")
WORKSPACE_ID = UUID("44444444-4444-4444-8444-444444444444")
CONVERSATION_ID = UUID("55555555-5555-4555-8555-555555555555")
MESSAGE_ID = UUID("66666666-6666-4666-8666-666666666666")
ANSWERED_AT = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


def message(question: str, turn_number: int) -> ConversationMessage:
    return ConversationMessage(
        id=MESSAGE_ID,
        turn_number=turn_number,
        question=question,
        response=QuestionResponse(
            answer="Authentication changed after review.",
            state=AnswerState.ANSWERED,
            confidence=ConfidenceCategory.HIGH,
            trace_id=TRACE_ID,
        ),
        answered_at=ANSWERED_AT,
        stale=False,
    )


class StubConversationService:
    async def create(
        self,
        request: QuestionRequest,
        *,
        answer_service: object,
        request_id: str,
        workspace_id: UUID,
    ) -> ConversationDetail:
        assert request.question == "Who changed authentication?"
        assert request_id == "conversation-request"
        assert workspace_id == WORKSPACE_ID
        return ConversationDetail(
            id=CONVERSATION_ID,
            title=request.question,
            created_at=ANSWERED_AT,
            updated_at=ANSWERED_AT,
            messages=[message(request.question, 1)],
        )

    async def append(
        self,
        conversation_id: UUID,
        request: QuestionRequest,
        *,
        answer_service: object,
        request_id: str,
        workspace_id: UUID,
    ) -> ConversationMessage:
        assert conversation_id == CONVERSATION_ID
        assert request.question == "Why did this get changed?"
        assert request_id == "conversation-request"
        assert workspace_id == WORKSPACE_ID
        return message(request.question, 2)

    async def list(self, *, workspace_id: UUID) -> list[ConversationSummary]:
        assert workspace_id == WORKSPACE_ID
        return [
            ConversationSummary(
                id=CONVERSATION_ID,
                title="Who changed authentication?",
                created_at=ANSWERED_AT,
                updated_at=ANSWERED_AT,
            )
        ]

    async def get(
        self,
        conversation_id: UUID,
        *,
        workspace_id: UUID,
    ) -> ConversationDetail:
        assert conversation_id == CONVERSATION_ID
        assert workspace_id == WORKSPACE_ID
        return ConversationDetail(
            id=CONVERSATION_ID,
            title="Who changed authentication?",
            created_at=ANSWERED_AT,
            updated_at=ANSWERED_AT,
            messages=[message("Who changed authentication?", 1)],
        )


def test_conversations_api_creates_lists_reads_and_appends() -> None:
    app = create_app()
    app.dependency_overrides[get_answer_service] = lambda: object()
    app.dependency_overrides[get_conversation_service] = lambda: StubConversationService()
    app.dependency_overrides[get_workspace_context] = (
        lambda: WorkspaceContext(workspace_id=WORKSPACE_ID)
    )
    client = TestClient(app)
    base = f"/api/v1/workspaces/{WORKSPACE_ID}/conversations"

    created = client.post(
        base,
        headers={"x-request-id": "conversation-request"},
        json={"question": "Who changed authentication?"},
    )
    listed = client.get(base)
    resumed = client.get(f"{base}/{CONVERSATION_ID}")
    appended = client.post(
        f"{base}/{CONVERSATION_ID}/messages",
        headers={"x-request-id": "conversation-request"},
        json={"question": "Why did this get changed?"},
    )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert resumed.status_code == 200
    assert appended.status_code == 201
    assert created.json()["id"] == str(CONVERSATION_ID)
    assert listed.json()[0]["id"] == str(CONVERSATION_ID)
    assert resumed.json()["messages"][0]["turn_number"] == 1
    assert appended.json()["turn_number"] == 2
