from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.conversation_models import (
    Conversation,
    ConversationMessage as ConversationMessageRecord,
)
from decision_assistant.answering.schemas import (
    ConversationContextTurn,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    QuestionRequest,
    QuestionResponse,
)
from decision_assistant.errors import ApplicationError
from decision_assistant.workspace.models import Workspace

CURRENT_RESPONSE_SCHEMA_VERSION = 1
MAX_CONTEXT_TURNS = 6
CONTEXT_ANSWER_MAX_CHARACTERS = 2_000


class AnswerGenerator(Protocol):
    async def answer(
        self,
        request: QuestionRequest,
        *,
        request_id: str,
        workspace_id: UUID | None = None,
        conversation_context: Sequence[ConversationContextTurn] = (),
    ) -> QuestionResponse: ...


class ConversationError(ApplicationError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            retryable=False,
        )


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        request: QuestionRequest,
        *,
        answer_service: AnswerGenerator,
        request_id: str,
        workspace_id: UUID,
    ) -> ConversationDetail:
        revision = await self._current_revision(workspace_id)
        generated = await answer_service.answer(
            request,
            request_id=request_id,
            workspace_id=workspace_id,
        )
        now = datetime.now(timezone.utc)
        conversation = Conversation(
            workspace_id=workspace_id,
            title=request.question[:200],
            created_at=now,
            updated_at=now,
        )
        self._session.add(conversation)
        await self._session.flush()
        message = self._message_record(
            conversation_id=conversation.id,
            turn_number=1,
            request=request,
            response=generated,
            revision=revision,
            answered_at=now,
        )
        self._session.add(message)
        await self._session.flush()
        return self._detail(conversation, [message], revision)

    async def append(
        self,
        conversation_id: UUID,
        request: QuestionRequest,
        *,
        answer_service: AnswerGenerator,
        request_id: str,
        workspace_id: UUID,
    ) -> ConversationMessage:
        conversation = await self._conversation(
            conversation_id,
            workspace_id=workspace_id,
            lock=True,
        )
        revision = await self._current_revision(workspace_id)
        recent_messages = list(
            await self._session.scalars(
                select(ConversationMessageRecord)
                .where(ConversationMessageRecord.conversation_id == conversation.id)
                .order_by(ConversationMessageRecord.turn_number.desc())
                .limit(MAX_CONTEXT_TURNS)
            )
        )
        context = [
            self._context_turn(message) for message in reversed(recent_messages)
        ]
        # ponytail: holds one thread lock during generation; split allocation from
        # append only if provider latency makes concurrent sends a real problem.
        generated = await answer_service.answer(
            request,
            request_id=request_id,
            workspace_id=workspace_id,
            conversation_context=context,
        )
        now = datetime.now(timezone.utc)
        message = self._message_record(
            conversation_id=conversation.id,
            turn_number=(recent_messages[0].turn_number + 1)
            if recent_messages
            else 1,
            request=request,
            response=generated,
            revision=revision,
            answered_at=now,
        )
        conversation.updated_at = now
        self._session.add(message)
        await self._session.flush()
        return self._message(message, revision)

    async def list(self, *, workspace_id: UUID) -> list[ConversationSummary]:
        conversations = list(
            await self._session.scalars(
                select(Conversation)
                .where(Conversation.workspace_id == workspace_id)
                .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            )
        )
        return [self._summary(conversation) for conversation in conversations]

    async def get(
        self,
        conversation_id: UUID,
        *,
        workspace_id: UUID,
    ) -> ConversationDetail:
        conversation = await self._conversation(
            conversation_id,
            workspace_id=workspace_id,
        )
        revision = await self._current_revision(workspace_id)
        messages = list(
            await self._session.scalars(
                select(ConversationMessageRecord)
                .where(ConversationMessageRecord.conversation_id == conversation.id)
                .order_by(ConversationMessageRecord.turn_number)
            )
        )
        return self._detail(conversation, messages, revision)

    async def _conversation(
        self,
        conversation_id: UUID,
        *,
        workspace_id: UUID,
        lock: bool = False,
    ) -> Conversation:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace_id,
        )
        if lock:
            statement = statement.with_for_update()
        conversation = await self._session.scalar(statement)
        if conversation is None:
            raise ConversationError(
                "conversation_not_found",
                "Conversation was not found",
                404,
            )
        return conversation

    async def _current_revision(self, workspace_id: UUID) -> int:
        revision = await self._session.scalar(
            select(Workspace.knowledge_revision).where(Workspace.id == workspace_id)
        )
        if revision is None:
            raise ConversationError("workspace_not_found", "Workspace not found", 404)
        return revision

    @staticmethod
    def _message_record(
        *,
        conversation_id: UUID,
        turn_number: int,
        request: QuestionRequest,
        response: QuestionResponse,
        revision: int,
        answered_at: datetime,
    ) -> ConversationMessageRecord:
        return ConversationMessageRecord(
            conversation_id=conversation_id,
            trace_id=response.trace_id,
            turn_number=turn_number,
            question=request.question,
            response=response.model_dump(mode="json"),
            response_schema_version=CURRENT_RESPONSE_SCHEMA_VERSION,
            knowledge_revision=revision,
            created_at=answered_at,
        )

    @staticmethod
    def _summary(conversation: Conversation) -> ConversationSummary:
        return ConversationSummary(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )

    def _detail(
        self,
        conversation: Conversation,
        messages: list[ConversationMessageRecord],
        revision: int,
    ) -> ConversationDetail:
        return ConversationDetail(
            **self._summary(conversation).model_dump(),
            messages=[self._message(message, revision) for message in messages],
        )

    @staticmethod
    def _message(
        message: ConversationMessageRecord,
        revision: int,
    ) -> ConversationMessage:
        response = ConversationService._stored_response(message)
        return ConversationMessage(
            id=message.id,
            turn_number=message.turn_number,
            question=message.question,
            response=response,
            answered_at=message.created_at,
            stale=message.knowledge_revision != revision,
        )

    @staticmethod
    def _context_turn(
        message: ConversationMessageRecord,
    ) -> ConversationContextTurn:
        response = ConversationService._stored_response(message)
        # ponytail: only six prior turns and 2,000 answer characters each; add
        # deterministic summaries if real conversations need a larger context.
        return ConversationContextTurn(
            question=message.question,
            answer=response.answer[:CONTEXT_ANSWER_MAX_CHARACTERS],
        )

    @staticmethod
    def _stored_response(
        message: ConversationMessageRecord,
    ) -> QuestionResponse:
        if message.response_schema_version != CURRENT_RESPONSE_SCHEMA_VERSION:
            raise ConversationError(
                "conversation_message_incompatible",
                "Saved conversation message must be regenerated",
                409,
            )
        try:
            return QuestionResponse.model_validate(message.response)
        except ValidationError as error:
            raise ConversationError(
                "conversation_message_incompatible",
                "Saved conversation message must be regenerated",
                409,
            ) from error
