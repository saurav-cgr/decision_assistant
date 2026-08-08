from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from shutil import copyfile
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.decisions.schemas import ExtractionPassage
from decision_assistant.errors import ApplicationError
from decision_assistant.ingestion.chunking import chunk_document
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.parsers import parse_document
from decision_assistant.models import (
    Decision,
    DecisionEvidence,
    DecisionRelation,
    Document,
    DocumentVersion,
    IngestionJob,
    Passage,
)
from decision_assistant.providers.base import EmbeddingProvider


class IngestionError(ApplicationError):
    def __init__(self, message: str, *, code: str = "ingestion_failed") -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=422,
            retryable=False,
        )


@dataclass(frozen=True, slots=True)
class IngestionResult:
    document_id: UUID
    version_id: UUID
    job_id: UUID
    skipped: bool


class IngestionService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        decision_extractor: DecisionExtractor,
        metadata_extractor: MetadataExtractor,
        upload_directory: Path,
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider
        self._decision_extractor = decision_extractor
        self._metadata_extractor = metadata_extractor
        self._upload_directory = upload_directory

    async def ingest(
        self,
        document_id: UUID,
        source_path: Path,
        *,
        request_id: str,
        job_id: UUID | None = None,
    ) -> IngestionResult:
        document = await self._session.get(Document, document_id)
        if document is None:
            raise IngestionError("Document not found", code="document_not_found")

        source_path = Path(source_path)
        source_bytes = source_path.read_bytes()
        checksum = sha256(source_bytes).hexdigest()
        active_version = (
            await self._session.get(DocumentVersion, document.active_version_id)
            if document.active_version_id is not None
            else None
        )
        if job_id is None and active_version is not None and active_version.checksum == checksum:
            job = IngestionJob(
                document_id=document.id,
                document_version_id=active_version.id,
                stage="unchanged",
                status="completed",
                progress=100,
                attempt_count=1,
                request_id=request_id,
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
            self._session.add(job)
            await self._session.flush()
            return IngestionResult(document.id, active_version.id, job.id, True)

        if job_id is not None:
            job = await self._session.get(IngestionJob, job_id)
            if job is None or job.document_id != document.id:
                raise IngestionError("Ingestion job not found", code="job_not_found")
            if job.document_version_id is None:
                raise IngestionError("Ingestion job has no version", code="job_invalid")
            version = await self._session.get(DocumentVersion, job.document_version_id)
            if version is None:
                raise IngestionError("Document version not found", code="version_not_found")
            version.state = "staging"
            version.error = None
            job.stage = "staging"
            job.status = "running"
            job.progress = 5
            job.attempt_count = max(job.attempt_count, 1)
            job.started_at = datetime.now(timezone.utc)
            job.error = None
            stored_path = source_path
            await self._session.flush()
        else:
            version_number = (
                await self._session.scalar(
                    select(
                        func.coalesce(func.max(DocumentVersion.version_number), 0)
                    ).where(DocumentVersion.document_id == document.id)
                )
            ) + 1
            stored_path = self._store_source(
                document.id,
                version_number,
                checksum,
                source_path,
            )
            version = DocumentVersion(
                document_id=document.id,
                version_number=version_number,
                checksum=checksum,
                storage_path=str(stored_path),
                state="staging",
            )
            job = IngestionJob(
                document_id=document.id,
                stage="staging",
                status="running",
                progress=5,
                attempt_count=1,
                request_id=request_id,
                started_at=datetime.now(timezone.utc),
            )
            self._session.add_all([version, job])
            await self._session.flush()
            job.document_version_id = version.id
            await self._session.flush()

        try:
            async with self._session.begin_nested():
                await self._process_and_activate(
                    document=document,
                    previous_version=active_version,
                    version=version,
                    job=job,
                    stored_path=stored_path,
                )
        except Exception as exc:
            error_code = exc.code if isinstance(exc, ApplicationError) else "ingestion_failed"
            version.state = "failed"
            version.error = {"code": error_code}
            job.stage = "failed"
            job.status = "failed"
            job.error = {"code": error_code}
            job.finished_at = datetime.now(timezone.utc)
            await self._session.flush()
            raise

        return IngestionResult(document.id, version.id, job.id, False)

    async def get_document(self, document_id: UUID) -> Document | None:
        return await self._session.get(Document, document_id)

    def _store_source(
        self,
        document_id: UUID,
        version_number: int,
        checksum: str,
        source_path: Path,
    ) -> Path:
        destination_directory = self._upload_directory / str(document_id)
        destination_directory.mkdir(parents=True, exist_ok=True)
        destination = destination_directory / (
            f"v{version_number}-{checksum[:12]}{source_path.suffix.lower()}"
        )
        copyfile(source_path, destination)
        return destination

    async def _process_and_activate(
        self,
        *,
        document: Document,
        previous_version: DocumentVersion | None,
        version: DocumentVersion,
        job: IngestionJob,
        stored_path: Path,
    ) -> None:
        job.stage = "parsing"
        job.progress = 15
        parsed = parse_document(stored_path)
        metadata = await self._metadata_extractor.extract(parsed)
        version.title = metadata.title
        version.document_date = metadata.document_date
        version.participants = metadata.participants
        version.source_type = metadata.source_type
        version.project = metadata.project
        version.normalized_content = parsed.content

        job.stage = "embedding"
        job.progress = 40
        drafts = chunk_document(parsed)
        embeddings = await self._embedding_provider.embed(
            [draft.content for draft in drafts]
        )
        if len(embeddings) != len(drafts):
            raise IngestionError(
                "Embedding provider returned wrong result count",
                code="embedding_count_mismatch",
            )

        passage_rows = [
            Passage(
                document_version_id=version.id,
                sequence_number=draft.sequence_number,
                content=draft.content,
                start_offset=draft.start_offset,
                end_offset=draft.end_offset,
                content_hash=draft.content_hash,
                locator=draft.locator,
                embedding=embedding,
            )
            for draft, embedding in zip(drafts, embeddings, strict=True)
        ]
        self._session.add_all(passage_rows)
        await self._session.flush()

        job.stage = "extracting_decisions"
        job.progress = 70
        extracted_decisions = await self._decision_extractor.extract(
            [
                ExtractionPassage(
                    passage_id=passage.id,
                    content=passage.content,
                    content_hash=passage.content_hash,
                )
                for passage in passage_rows
            ]
        )
        passage_by_id = {passage.id: passage for passage in passage_rows}
        decisions_with_relations: list[tuple[Decision, object | None]] = []
        for extracted in extracted_decisions:
            decision = Decision(
                document_version_id=version.id,
                statement=extracted.statement,
                effective_date=extracted.effective_date,
                owner=extracted.owner,
                status=extracted.status.value,
                reasons=extracted.reasons,
                alternatives=extracted.alternatives,
                project=extracted.project,
                topic=extracted.topic,
                extraction_confidence=extracted.extraction_confidence,
                provenance="extracted",
                review_state="supported",
                user_edited=False,
                retired=False,
            )
            self._session.add(decision)
            await self._session.flush()
            evidence = extracted.evidence
            passage = passage_by_id[evidence.passage_id]
            self._session.add(
                DecisionEvidence(
                    decision_id=decision.id,
                    passage_id=passage.id,
                    field_name=None,
                    start_offset=evidence.start_offset,
                    end_offset=evidence.end_offset,
                    support_state="supported",
                    is_primary=True,
                    content_hash=evidence.content_hash,
                )
            )
            decisions_with_relations.append((decision, extracted.relation))

        for decision, relation in decisions_with_relations:
            if relation is None:
                continue
            target = await self._session.get(Decision, relation.target_decision_id)
            if target is not None:
                self._session.add(
                    DecisionRelation(
                        source_decision_id=decision.id,
                        target_decision_id=target.id,
                        relation_type=relation.relation_type.value,
                        authority="model_inferred",
                        confidence=relation.confidence.value,
                        rationale=relation.rationale,
                    )
                )

        job.stage = "activating"
        job.progress = 90
        if previous_version is not None:
            previous_version.state = "retired"
            await self._session.flush([previous_version])
            await self._retire_previous_decisions(previous_version.id)

        version.state = "active"
        version.activated_at = datetime.now(timezone.utc)
        document.active_version_id = version.id
        job.stage = "completed"
        job.status = "completed"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def _retire_previous_decisions(self, version_id: UUID) -> None:
        corrected = or_(
            Decision.user_edited.is_(True),
            Decision.provenance == "user_corrected",
        )
        await self._session.execute(
            update(Decision)
            .where(Decision.document_version_id == version_id, corrected)
            .values(review_state="needs_review")
        )
        await self._session.execute(
            update(Decision)
            .where(Decision.document_version_id == version_id, ~corrected)
            .values(retired=True)
        )
