import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from shutil import copyfile
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.errors import ApplicationError
from decision_assistant.ingestion.chunking import chunk_document
from decision_assistant.ingestion.decision_records import (
    persist_extracted_decisions,
    retire_previous_decisions,
)
from decision_assistant.ingestion.embedding_cache import resolve_embedding_cache
from decision_assistant.ingestion.errors import IngestionError
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.parse_runner import (
    ParseTimeoutError,
    run_parse_in_subprocess,
)
from decision_assistant.ingestion.parsers import (
    DocumentParseError,
    ParsedDocument,
    parse_document,
)
from decision_assistant.ingestion.retrieval_units import (
    RetrievalUnitStrategy,
    build_retrieval_units,
)
from decision_assistant.ingestion.validation import validate_document_content
from decision_assistant.ingestion.models import (
    Document,
    DocumentVersion,
    IngestionJob,
    Passage,
)
from decision_assistant.workspace.models import Workspace
from decision_assistant.providers.base import EmbeddingProvider
from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.config import get_settings
from decision_assistant.workspace.embedding_profile import (
    CorpusResetRequired,
    acquire_workspace_embedding_lock,
    get_corpus_state,
)
from decision_assistant.workspace.revision import bump_knowledge_revision

_logger = logging.getLogger("decision_assistant.ingestion")


@dataclass(frozen=True, slots=True)
class IngestionResult:
    document_id: UUID
    version_id: UUID
    job_id: UUID
    skipped: bool


async def _parse_for_ingestion(source_path: Path) -> ParsedDocument:
    settings = get_settings()
    # T063/T064 (FR-020/FR-021): the content-level checks run immediately before the parser, so a
    # mislabelled or over-long file fails with its own sanitized code instead of a Docling error.
    validate_document_content(source_path, max_pdf_pages=settings.max_pdf_pages)
    if source_path.suffix.lower() == ".pdf":
        # DB60 (checker V139): the PDF path runs in a child process the timeout can kill. The old
        # `wait_for(to_thread(...))` marked the job failed while the Docling thread kept a core and
        # gigabytes of RSS alive, so enough slow uploads OOM-killed the API and it stayed down until
        # a manual restart — the opposite of SC-009/FR-022. Text and docx stay in-process: they are
        # bounded by the upload size cap and produce no multi-gigabyte parser state.
        try:
            return await asyncio.to_thread(
                run_parse_in_subprocess,
                source_path,
                timeout_seconds=settings.pdf_parse_timeout_seconds,
                concurrency_limit=settings.pdf_parse_concurrency,
            )
        except ParseTimeoutError as exc:
            raise DocumentParseError(
                "pdf_parse_timeout",
                "PDF parsing timed out",
            ) from exc
    return parse_document(source_path)


class IngestionService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        decision_extractor: DecisionExtractor,
        metadata_extractor: MetadataExtractor,
        upload_directory: Path,
        chunking_profile: dict[str, object] | None = None,
        retrieval_unit_strategy: RetrievalUnitStrategy = "passage_hybrid",
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider
        self._decision_extractor = decision_extractor
        self._metadata_extractor = metadata_extractor
        self._upload_directory = upload_directory
        self._chunking_profile = (
            chunking_profile if chunking_profile is not None else CURRENT_CHUNKING_PROFILE
        )
        self._retrieval_unit_strategy = retrieval_unit_strategy

    async def ingest(
        self,
        document_id: UUID,
        source_path: Path,
        *,
        request_id: str,
        job_id: UUID | None = None,
        extract_decisions: bool = True,
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
            version.chunking_profile = self._chunking_profile
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
                chunking_profile=self._chunking_profile,
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

        # Captured before the savepoint so the failure log below can name the version: rolling the
        # savepoint back expires these instances, and reading an expired attribute would attempt IO
        # outside the greenlet (MissingGreenlet) and mask the original error.
        version_id = version.id

        try:
            async with self._session.begin_nested():
                await self._process_and_activate(
                    document=document,
                    previous_version=active_version,
                    version=version,
                    job=job,
                    stored_path=stored_path,
                    extract_decisions=extract_decisions,
                )
        except Exception as exc:
            error_code = exc.code if isinstance(exc, ApplicationError) else "ingestion_failed"
            # DB61: nothing used to be logged here, so the diagnostics bundle carried almost no
            # ingestion signal. Only the code, the ids and the exception *type* go in: an exception
            # message can quote document text, and the bundle is a file users attach to bug reports.
            _logger.warning(
                "ingestion failed: document=%s version=%s code=%s error=%s",
                document_id,
                version_id,
                error_code,
                type(exc).__name__,
            )
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
        extract_decisions: bool = True,
    ) -> None:
        job.stage = "parsing"
        job.progress = 15
        parsed = await _parse_for_ingestion(stored_path)
        metadata = await self._metadata_extractor.extract(parsed)
        version.title = metadata.title
        version.document_date = metadata.document_date
        version.participants = metadata.participants
        version.source_type = metadata.source_type
        version.project = metadata.project
        version.normalized_content = parsed.content

        job.stage = "embedding"
        job.progress = 40
        drafts = chunk_document(
            parsed,
            target_tokens=int(self._chunking_profile["target_tokens"]),
            max_tokens=int(self._chunking_profile["max_tokens"]),
            overlap_tokens=int(self._chunking_profile["overlap_tokens"]),
        )
        unit_drafts = build_retrieval_units(
            drafts,
            strategy=self._retrieval_unit_strategy,
        )
        await acquire_workspace_embedding_lock(self._session, document.workspace_id)
        embedding_cache = await resolve_embedding_cache(
            self._session,
            embedding_provider=self._embedding_provider,
            workspace_id=document.workspace_id,
            unit_drafts=unit_drafts,
        )
        parent_rows: dict[int, Passage] = {}
        passage_rows: list[Passage] = []
        for storage_sequence, unit in enumerate(unit_drafts):
            if unit.kind == "sentence":
                continue
            draft = unit.draft
            row = Passage(
                document_version_id=version.id,
                sequence_number=storage_sequence,
                content=draft.content,
                start_offset=draft.start_offset,
                end_offset=draft.end_offset,
                content_hash=draft.content_hash,
                locator=draft.locator,
                structural_metadata=draft.structural_metadata,
                retrieval_unit_kind=unit.kind,
                embedding_cache_id=embedding_cache[draft.content_hash].id,
            )
            passage_rows.append(row)
            if unit.kind == "parent" and unit.parent_index is None:
                parent_rows[len(parent_rows)] = row
        self._session.add_all(passage_rows)
        await self._session.flush()

        sentence_rows = [
            Passage(
                document_version_id=version.id,
                sequence_number=storage_sequence,
                content=unit.draft.content,
                start_offset=unit.draft.start_offset,
                end_offset=unit.draft.end_offset,
                content_hash=unit.draft.content_hash,
                locator=unit.draft.locator,
                structural_metadata=unit.draft.structural_metadata,
                retrieval_unit_kind="sentence",
                parent_passage_id=parent_rows[unit.parent_index].id,
                embedding_cache_id=embedding_cache[unit.draft.content_hash].id,
            )
            for storage_sequence, unit in enumerate(unit_drafts)
            if unit.kind == "sentence"
        ]
        passage_rows.extend(sentence_rows)
        self._session.add_all(sentence_rows)
        await self._session.flush()

        if extract_decisions:
            job.stage = "extracting_decisions"
            job.progress = 70
            await persist_extracted_decisions(
                self._session,
                workspace_id=document.workspace_id,
                document_version_id=version.id,
                passages=passage_rows,
                decision_extractor=self._decision_extractor,
                retrieval_unit_strategy=self._retrieval_unit_strategy,
            )

        job.stage = "activating"
        job.progress = 90
        corpus_state = await get_corpus_state(
            self._session,
            document.workspace_id,
            self._embedding_provider.profile,
            self._chunking_profile,
        )
        if corpus_state.active_passage_count == 0:
            workspace = await self._session.get(Workspace, document.workspace_id)
            if workspace is None:
                raise IngestionError("Workspace not found", code="workspace_not_found")
            workspace.embedding_profile = self._embedding_provider.profile.as_dict()
        elif corpus_state.corpus_reset_required:
            raise CorpusResetRequired()
        if previous_version is not None:
            previous_version.state = "retired"
            await self._session.flush([previous_version])
            await retire_previous_decisions(self._session, previous_version.id)

        version.state = "active"
        version.activated_at = datetime.now(timezone.utc)
        document.active_version_id = version.id
        await bump_knowledge_revision(self._session, document.workspace_id)
        job.stage = "completed"
        job.status = "completed"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        await self._session.flush()


