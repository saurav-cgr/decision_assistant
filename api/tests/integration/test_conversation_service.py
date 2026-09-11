from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.conversation_service import (
    ConversationError,
    ConversationService,
)
from decision_assistant.answering.schemas import (
    AnswerState,
    ConfidenceCategory,
    ConversationContextTurn,
    QuestionRequest,
    QuestionResponse,
)
from decision_assistant.models import RetrievalTrace, Workspace
from decision_assistant.workspace.revision import bump_knowledge_revision


class StubAnswerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.calls = 0
        self.contexts: list[list[ConversationContextTurn]] = []

    async def answer(
        self,
        request: QuestionRequest,
        *,
        request_id: str,
        workspace_id: UUID | None = None,
        conversation_context: Sequence[ConversationContextTurn] = (),
    ) -> QuestionResponse:
        assert workspace_id is not None
        self.calls += 1
        self.contexts.append(list(conversation_context))
        trace = RetrievalTrace(
            workspace_id=workspace_id,
            request_id=f"{request_id}:{self.calls}",
            normalized_question=request.question.casefold(),
        )
        self.session.add(trace)
        await self.session.flush()
        return QuestionResponse(
            answer=f"Generated answer {self.calls}",
            state=AnswerState.ANSWERED,
            confidence=ConfidenceCategory.HIGH,
            trace_id=trace.id,
        )


async def create_workspace(session: AsyncSession, name: str) -> Workspace:
    workspace = Workspace(name=f"{name} {uuid4()}")
    session.add(workspace)
    await session.flush()
    return workspace


@pytest.mark.asyncio
async def test_conversations_persist_ordered_messages_and_resume(
    db_session: AsyncSession,
) -> None:
    workspace = await create_workspace(db_session, "Conversation workspace")
    answers = StubAnswerService(db_session)
    service = ConversationService(db_session)

    created = await service.create(
        QuestionRequest(question="Who changed authentication?"),
        answer_service=answers,
        request_id="first",
        workspace_id=workspace.id,
    )
    appended = await service.append(
        created.id,
        QuestionRequest(question="Why did this get changed?"),
        answer_service=answers,
        request_id="follow-up",
        workspace_id=workspace.id,
    )

    assert created.title == "Who changed authentication?"
    assert appended.turn_number == 2
    assert appended.response.answer == "Generated answer 2"
    assert answers.calls == 2
    assert answers.contexts[1] == [
        ConversationContextTurn(
            question="Who changed authentication?",
            answer="Generated answer 1",
        )
    ]

    resumed = await service.get(created.id, workspace_id=workspace.id)
    assert [message.question for message in resumed.messages] == [
        "Who changed authentication?",
        "Why did this get changed?",
    ]
    assert all(not message.stale for message in resumed.messages)
    assert [item.id for item in await service.list(workspace_id=workspace.id)] == [
        created.id
    ]


@pytest.mark.asyncio
async def test_conversations_are_workspace_scoped_and_marked_stale(
    db_session: AsyncSession,
) -> None:
    workspace = await create_workspace(db_session, "Conversation workspace")
    other_workspace = await create_workspace(db_session, "Other workspace")
    answers = StubAnswerService(db_session)
    service = ConversationService(db_session)
    created = await service.create(
        QuestionRequest(question="Who changed authentication?"),
        answer_service=answers,
        request_id="first",
        workspace_id=workspace.id,
    )

    await bump_knowledge_revision(db_session, workspace.id)
    resumed = await service.get(created.id, workspace_id=workspace.id)
    assert resumed.messages[0].stale is True

    with pytest.raises(ConversationError) as caught:
        await service.get(created.id, workspace_id=other_workspace.id)
    assert caught.value.status_code == 404
    ConversationContextTurn,
