from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.history_models import QuestionAnswer
from decision_assistant.answering.schemas import (
    QuestionAnswerResponse,
    QuestionHistoryListResponse,
    QuestionHistorySummary,
    QuestionRequest,
    QuestionResponse,
)
from decision_assistant.errors import ApplicationError
from decision_assistant.models import Workspace

CURRENT_RESPONSE_SCHEMA_VERSION = 1


class AnswerGenerator(Protocol):
    async def answer(
        self,
        request: QuestionRequest,
        *,
        request_id: str,
        workspace_id: UUID | None = None,
    ) -> QuestionResponse: ...


class QuestionHistoryError(ApplicationError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            retryable=False,
        )


def normalize_question(question: str) -> str:
    return " ".join(question.split()).casefold()


class QuestionHistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def answer(
        self,
        request: QuestionRequest,
        *,
        answer_service: AnswerGenerator,
        request_id: str,
        workspace_id: UUID,
    ) -> QuestionAnswerResponse:
        normalized = normalize_question(request.question)
        revision = await self._current_revision(workspace_id)
        record = await self._session.scalar(
            select(QuestionAnswer).where(
                QuestionAnswer.workspace_id == workspace_id,
                QuestionAnswer.normalized_question == normalized,
            )
        )
        if record is not None and not request.force_refresh:
            cached = self._stored_response(record)
            if cached is not None and record.knowledge_revision == revision:
                record.last_asked_at = datetime.now(timezone.utc)
                await self._session.flush()
                return self._answer_response(
                    record,
                    cached,
                    cached=True,
                    current_revision=revision,
                )

        generated = await answer_service.answer(
            QuestionRequest(question=request.question),
            request_id=request_id,
            workspace_id=workspace_id,
        )
        now = datetime.now(timezone.utc)
        if record is None:
            record = QuestionAnswer(
                workspace_id=workspace_id,
                trace_id=generated.trace_id,
                question=request.question,
                normalized_question=normalized,
                response=generated.model_dump(mode="json"),
                response_schema_version=CURRENT_RESPONSE_SCHEMA_VERSION,
                knowledge_revision=revision,
                answered_at=now,
                last_asked_at=now,
            )
            self._session.add(record)
        else:
            record.trace_id = generated.trace_id
            record.question = request.question
            record.response = generated.model_dump(mode="json")
            record.response_schema_version = CURRENT_RESPONSE_SCHEMA_VERSION
            record.knowledge_revision = revision
            record.answered_at = now
            record.last_asked_at = now
        await self._session.flush()
        return self._answer_response(
            record,
            generated,
            cached=False,
            current_revision=revision,
        )

    async def list_history(
        self,
        *,
        workspace_id: UUID,
        query: str | None,
        page: int,
        page_size: int,
    ) -> QuestionHistoryListResponse:
        conditions = [QuestionAnswer.workspace_id == workspace_id]
        normalized_query = " ".join((query or "").split())
        if normalized_query:
            conditions.append(
                QuestionAnswer.question.icontains(normalized_query, autoescape=True)
            )

        total = await self._session.scalar(
            select(func.count(QuestionAnswer.id)).where(*conditions)
        )
        records = list(
            await self._session.scalars(
                select(QuestionAnswer)
                .where(*conditions)
                .order_by(
                    QuestionAnswer.last_asked_at.desc(),
                    QuestionAnswer.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        revision = await self._current_revision(workspace_id)
        return QuestionHistoryListResponse(
            items=[self._summary(record, revision) for record in records],
            page=page,
            page_size=page_size,
            total=total or 0,
            total_pages=((total or 0) + page_size - 1) // page_size,
        )

    async def get_history_item(
        self,
        history_id: UUID,
        *,
        workspace_id: UUID,
    ) -> QuestionAnswerResponse:
        record = await self._session.scalar(
            select(QuestionAnswer).where(
                QuestionAnswer.id == history_id,
                QuestionAnswer.workspace_id == workspace_id,
            )
        )
        if record is None:
            raise QuestionHistoryError(
                "question_history_not_found",
                "Saved question was not found",
                404,
            )
        stored = self._stored_response(record)
        if stored is None:
            raise QuestionHistoryError(
                "question_history_incompatible",
                "Saved answer must be regenerated",
                409,
            )
        revision = await self._current_revision(workspace_id)
        return self._answer_response(
            record,
            stored,
            cached=True,
            current_revision=revision,
        )

    async def _current_revision(self, workspace_id: UUID) -> int:
        revision = await self._session.scalar(
            select(Workspace.knowledge_revision).where(Workspace.id == workspace_id)
        )
        if revision is None:
            raise QuestionHistoryError(
                "workspace_not_found",
                "Workspace not found",
                404,
            )
        return revision

    @staticmethod
    def _stored_response(record: QuestionAnswer) -> QuestionResponse | None:
        if record.response_schema_version != CURRENT_RESPONSE_SCHEMA_VERSION:
            return None
        try:
            return QuestionResponse.model_validate(record.response)
        except ValidationError:
            return None

    def _summary(
        self,
        record: QuestionAnswer,
        current_revision: int,
    ) -> QuestionHistorySummary:
        stored = self._stored_response(record)
        return QuestionHistorySummary(
            id=record.id,
            question=record.question,
            state=stored.state if stored is not None else None,
            confidence=stored.confidence if stored is not None else None,
            answered_at=record.answered_at,
            last_asked_at=record.last_asked_at,
            stale=(
                stored is None or record.knowledge_revision != current_revision
            ),
        )

    @staticmethod
    def _answer_response(
        record: QuestionAnswer,
        response: QuestionResponse,
        *,
        cached: bool,
        current_revision: int,
    ) -> QuestionAnswerResponse:
        return QuestionAnswerResponse(
            **response.model_dump(),
            history_id=record.id,
            answered_at=record.answered_at,
            cached=cached,
            stale=record.knowledge_revision != current_revision,
        )
