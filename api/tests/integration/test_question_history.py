from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.history_models import QuestionAnswer
from decision_assistant.answering.history_service import (
    QuestionHistoryError,
    QuestionHistoryService,
)
from decision_assistant.answering.schemas import (
    AnswerState,
    ConfidenceCategory,
    QuestionRequest,
    QuestionResponse,
)
from decision_assistant.models import RetrievalTrace, Workspace
from decision_assistant.workspace.revision import bump_knowledge_revision


class StubAnswerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.calls = 0

    async def answer(
        self,
        request: QuestionRequest,
        *,
        request_id: str,
        workspace_id: UUID | None = None,
    ) -> QuestionResponse:
        assert workspace_id is not None
        self.calls += 1
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
async def test_exact_repeat_reuses_answer_and_force_refresh_replaces_it(
    db_session: AsyncSession,
) -> None:
    workspace = await create_workspace(db_session, "Cache workspace")
    generator = StubAnswerService(db_session)
    history = QuestionHistoryService(db_session)

    first = await history.answer(
        QuestionRequest(question="Why was authentication postponed?"),
        answer_service=generator,
        request_id="first",
        workspace_id=workspace.id,
    )
    repeated = await history.answer(
        QuestionRequest(question="  WHY was   authentication postponed?  "),
        answer_service=generator,
        request_id="repeat",
        workspace_id=workspace.id,
    )

    assert first.cached is False
    assert repeated.cached is True
    assert repeated.history_id == first.history_id
    assert repeated.answer == "Generated answer 1"
    assert generator.calls == 1

    refreshed = await history.answer(
        QuestionRequest(
            question="Why was authentication postponed?",
            force_refresh=True,
        ),
        answer_service=generator,
        request_id="refresh",
        workspace_id=workspace.id,
    )

    assert refreshed.cached is False
    assert refreshed.history_id == first.history_id
    assert refreshed.answer == "Generated answer 2"
    assert generator.calls == 2
    assert await db_session.scalar(select(func.count(QuestionAnswer.id))) == 1


@pytest.mark.asyncio
async def test_knowledge_revision_makes_repeat_stale_and_regenerates(
    db_session: AsyncSession,
) -> None:
    workspace = await create_workspace(db_session, "Revision workspace")
    generator = StubAnswerService(db_session)
    history = QuestionHistoryService(db_session)
    request = QuestionRequest(question="Who owns authentication?")

    first = await history.answer(
        request,
        answer_service=generator,
        request_id="before-revision",
        workspace_id=workspace.id,
    )
    await bump_knowledge_revision(db_session, workspace.id)

    saved = await history.get_history_item(
        first.history_id,
        workspace_id=workspace.id,
    )
    regenerated = await history.answer(
        request,
        answer_service=generator,
        request_id="after-revision",
        workspace_id=workspace.id,
    )

    assert saved.cached is True
    assert saved.stale is True
    assert regenerated.cached is False
    assert regenerated.stale is False
    assert regenerated.answer == "Generated answer 2"
    assert generator.calls == 2


@pytest.mark.asyncio
async def test_history_search_paginates_and_isolates_workspaces(
    db_session: AsyncSession,
) -> None:
    workspace = await create_workspace(db_session, "List workspace")
    other_workspace = await create_workspace(db_session, "Other workspace")
    generator = StubAnswerService(db_session)
    history = QuestionHistoryService(db_session)

    questions = [
        "Authentication owner",
        "Authentication timing",
        "Authentication alternatives",
        "Billing owner",
        "Is rollout 100% complete?",
    ]
    saved_ids = []
    for index, question in enumerate(questions):
        saved = await history.answer(
            QuestionRequest(question=question),
            answer_service=generator,
            request_id=f"list-{index}",
            workspace_id=workspace.id,
        )
        saved_ids.append(saved.history_id)
    await history.answer(
        QuestionRequest(question="Authentication in another workspace"),
        answer_service=generator,
        request_id="other",
        workspace_id=other_workspace.id,
    )

    first_page = await history.list_history(
        workspace_id=workspace.id,
        query="authentication",
        page=1,
        page_size=2,
    )
    second_page = await history.list_history(
        workspace_id=workspace.id,
        query="authentication",
        page=2,
        page_size=2,
    )
    literal_wildcard = await history.list_history(
        workspace_id=workspace.id,
        query="%",
        page=1,
        page_size=10,
    )

    assert first_page.total == 3
    assert first_page.total_pages == 2
    assert len(first_page.items) == 2
    assert len(second_page.items) == 1
    assert {item.id for item in first_page.items}.isdisjoint(
        item.id for item in second_page.items
    )
    assert [item.question for item in literal_wildcard.items] == [
        "Is rollout 100% complete?"
    ]

    with pytest.raises(QuestionHistoryError) as caught:
        await history.get_history_item(
            saved_ids[0],
            workspace_id=other_workspace.id,
        )
    assert caught.value.status_code == 404
