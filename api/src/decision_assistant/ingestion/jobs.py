from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.models import DocumentVersion, IngestionJob


async def recover_stale_jobs(session: AsyncSession) -> int:
    """Mark jobs left running by a stopped API process as interrupted."""
    jobs = list(
        await session.scalars(
            select(IngestionJob).where(IngestionJob.status == "running")
        )
    )
    finished_at = datetime.now(timezone.utc)
    for job in jobs:
        job.status = "failed"
        job.stage = "interrupted"
        job.error = {"code": "ingestion_interrupted"}
        job.finished_at = finished_at
        if job.document_version_id is not None:
            version = await session.get(DocumentVersion, job.document_version_id)
            if version is not None and version.state == "staging":
                version.state = "failed"
                version.error = {"code": "ingestion_interrupted"}
    await session.flush()
    return len(jobs)
