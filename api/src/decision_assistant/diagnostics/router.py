"""Diagnostics endpoints (T058, US7/FR-018).

Host-level rather than workspace-scoped (the bundle describes this installation), but still
authenticated: it carries logs, and logs can quote document text.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi import status as http_status

from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.auth.models import User
from decision_assistant.diagnostics.bundle import build_bundle

router = APIRouter(prefix="/api/v1", tags=["diagnostics"])


@router.get("/diagnostics/bundle", status_code=http_status.HTTP_200_OK)
async def download_diagnostics_bundle(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Return the diagnostics bundle as a downloadable zip.

    Assembled in memory: the archive is a few megabytes (rotated logs plus a small config dump) and
    is written straight into the response, so no temporary file is left on the host.
    """
    bundle = await build_bundle(request.app.state.settings)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Response(
        content=bundle,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                "attachment; "
                f'filename="decision-assistant-diagnostics-{timestamp}.zip"'
            )
        },
    )
