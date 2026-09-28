import logging
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.db import get_session, session_factory
from decision_assistant.auth.models import User
from decision_assistant.providers.base import ProviderConfigurationInvalid
from decision_assistant.providers.factory import (
    CachedProviderBundleFactory,
    configured_embedding_profile,
    validate_selected_provider_configuration,
)
from decision_assistant.providers.disclosure import (
    active_provider,
    provider_is_remote,
    sends_document_text_remotely,
)
from decision_assistant.workspace.provider_config import (
    acquire_provider_switch_lock,
    active_rebuild_workspace_ids,
    apply_stored_provider_config,
    store_provider_config,
)
from decision_assistant.workspace.rebuild.dispatch import dispatch_pending_rebuild
from decision_assistant.workspace.rebuild_models import CorpusRebuild
from decision_assistant.workspace.schemas import (
    CorpusRebuildStatus,
    ProviderConfigResponse,
    ProviderDisclosureResponse,
    ProviderSwitchRequest,
    WorkspaceCreate,
    WorkspaceDetail,
    WorkspaceListResponse,
    WorkspaceRename,
    WorkspaceSummary,
)
from decision_assistant.workspace.service import (
    CorpusRebuildInProgress,
    CorpusRebuildNotFound,
    CorpusRebuildNotRetryable,
    ProviderSwitchNotConfigured,
    ProviderSwitchRequiresRebuild,
    WorkspaceService,
)

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])
_logger = logging.getLogger("uvicorn.error")


def get_workspace_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkspaceService:
    return WorkspaceService(session)


async def _summarize(
    service: WorkspaceService,
    workspace,
) -> WorkspaceSummary:
    return WorkspaceSummary(
        id=workspace.id,
        name=workspace.name,
        status=workspace.status,
        is_active=workspace.is_active,
        document_count=await service.document_count(workspace.id),
        created_at=workspace.created_at,
    )


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceListResponse:
    workspaces = await service.list(owner_user_id=user.id)
    items = [await _summarize(service, w) for w in workspaces]
    return WorkspaceListResponse(items=items)


@router.post("", response_model=WorkspaceDetail, status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceDetail:
    workspace = await service.create(owner_user_id=user.id, name=payload.name)
    return WorkspaceDetail(
        **_summary_fields(await _summarize(service, workspace)),
        embedding_profile=workspace.embedding_profile,
        disclosure_acknowledged_at=workspace.disclosure_acknowledged_at,
    )


@router.get("/{workspace_id}", response_model=WorkspaceDetail)
async def get_workspace(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceDetail:
    workspace = await service.get(workspace_id, owner_user_id=user.id)
    return WorkspaceDetail(
        **_summary_fields(await _summarize(service, workspace)),
        embedding_profile=workspace.embedding_profile,
        disclosure_acknowledged_at=workspace.disclosure_acknowledged_at,
    )


@router.patch("/{workspace_id}", response_model=WorkspaceDetail)
async def rename_workspace(
    workspace_id: UUID,
    payload: WorkspaceRename,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceDetail:
    workspace = await service.rename(
        workspace_id,
        owner_user_id=user.id,
        name=payload.name,
    )
    return WorkspaceDetail(
        **_summary_fields(await _summarize(service, workspace)),
        embedding_profile=workspace.embedding_profile,
        disclosure_acknowledged_at=workspace.disclosure_acknowledged_at,
    )


@router.post("/{workspace_id}/activate", response_model=WorkspaceDetail)
async def activate_workspace(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceDetail:
    workspace = await service.activate(workspace_id, owner_user_id=user.id)
    return WorkspaceDetail(
        **_summary_fields(await _summarize(service, workspace)),
        embedding_profile=workspace.embedding_profile,
        disclosure_acknowledged_at=workspace.disclosure_acknowledged_at,
    )


@router.post("/{workspace_id}/archive", response_model=WorkspaceDetail)
async def archive_workspace(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceDetail:
    workspace = await service.archive(workspace_id, owner_user_id=user.id)
    return WorkspaceDetail(
        **_summary_fields(await _summarize(service, workspace)),
        embedding_profile=workspace.embedding_profile,
        disclosure_acknowledged_at=workspace.disclosure_acknowledged_at,
    )


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> None:
    await service.delete_archived(workspace_id, owner_user_id=user.id)


def _summary_fields(summary: WorkspaceSummary) -> dict:
    return summary.model_dump()


def _corpus_rebuild_status(rebuild: CorpusRebuild) -> CorpusRebuildStatus:
    return CorpusRebuildStatus(
        status=rebuild.status,
        reason=rebuild.reason,
        documents_total=rebuild.documents_total,
        documents_completed=rebuild.documents_completed,
        started_at=rebuild.started_at,
        finished_at=rebuild.finished_at,
        error=rebuild.error,
    )


async def _latest_rebuild(
    session: AsyncSession, workspace_id: UUID
) -> CorpusRebuild | None:
    return await session.scalar(
        select(CorpusRebuild)
        .where(CorpusRebuild.workspace_id == workspace_id)
        .order_by(CorpusRebuild.created_at.desc())
        .limit(1)
    )


async def _require_failed_rebuild(
    session: AsyncSession, workspace_id: UUID
) -> CorpusRebuild:
    """Return the workspace's latest rebuild, or raise its documented 404/409.

    The retry route calls this twice: once before the provider-switch lock and once under it, so
    the checks and their error codes cannot drift apart.
    """
    latest = await _latest_rebuild(session, workspace_id)
    if latest is None:
        raise CorpusRebuildNotFound()
    if latest.status != "failed":
        raise CorpusRebuildNotRetryable(latest.status)
    return latest


@router.get(
    "/{workspace_id}/corpus-rebuild",
    response_model=CorpusRebuildStatus,
)
async def get_corpus_rebuild(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> CorpusRebuildStatus:
    await service.get(workspace_id, owner_user_id=user.id)
    rebuild = await _latest_rebuild(session, workspace_id)
    if rebuild is None:
        raise CorpusRebuildNotFound()
    return _corpus_rebuild_status(rebuild)


@router.post(
    "/{workspace_id}/corpus-rebuild/retry",
    response_model=CorpusRebuildStatus,
    status_code=202,
)
async def retry_corpus_rebuild(
    workspace_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> CorpusRebuildStatus:
    await service.get(workspace_id, owner_user_id=user.id)
    await _require_failed_rebuild(session, workspace_id)

    # DB72(a): the same process-wide lock the switch route takes, before this route inserts its
    # `pending` row. Without it a manual retry and a confirmed switch on another workspace could
    # both pass: the switch's `active_rebuild_workspace_ids` read would not see this still-unwritten
    # rebuild, and the retry would then finish under the provider bundle it resolved at request
    # start while `app_settings` already reports the new configuration (DB57's divergence, narrower
    # trigger). Taking the lock makes the second request wait for the first transaction to commit.
    await acquire_provider_switch_lock(session)

    # DB73: the check above ran before the lock, so it describes a world this request may no longer
    # be in — a concurrent retry that held the lock first has already inserted its `pending` row.
    # Re-reading under the lock turns that case into the documented 409 instead of letting the
    # insert hit the single-active-rebuild unique index (an unmapped IntegrityError, i.e. a 500).
    await _require_failed_rebuild(session, workspace_id)

    rebuild = CorpusRebuild(
        workspace_id=workspace_id,
        status="pending",
        reason="manual_retry",
        documents_total=0,
        documents_completed=0,
    )
    session.add(rebuild)
    await session.flush()

    # DB72(a)/V173: the factory is resolved *after* the lock, exactly as the switch route resolves
    # it, because a switch that held the lock first has already replaced the cached factory. Reading
    # the request-time dependency (resolved before this body ran) would dispatch the rebuild with the
    # bundle the switch just superseded and closed, under settings that already describe the new
    # provider (DB57's divergence again, this time for the switch-first order).
    settings = request.app.state.settings
    background_tasks.add_task(
        dispatch_pending_rebuild,
        session_factory,
        rebuild_id=rebuild.id,
        settings=settings,
        providers=request.app.state.provider_bundle_factory(),
        request_id=str(uuid4()),
        logger=_logger,
    )
    return _corpus_rebuild_status(rebuild)


def _provider_disclosure(workspace, settings) -> ProviderDisclosureResponse:
    generation = settings.generation_provider
    embedding = settings.embedding_provider
    return ProviderDisclosureResponse(
        provider=active_provider(settings),
        generation_provider=generation,
        embedding_provider=embedding,
        generation_sends_document_text_remotely=provider_is_remote(generation),
        embedding_sends_document_text_remotely=provider_is_remote(embedding),
        sends_document_text_remotely=sends_document_text_remotely(settings),
        acknowledged_at=workspace.disclosure_acknowledged_at,
    )


# T048 (US6/FR-014): the app must disclose where document text goes before the first upload.
# GET is what the disclosure screen reads; POST is the acknowledgement the upload guard (T049)
# will require. Both are owner-scoped like every other workspace route, so one user cannot read or
# acknowledge another user's workspace.
@router.get(
    "/{workspace_id}/provider-disclosure",
    response_model=ProviderDisclosureResponse,
)
async def get_provider_disclosure(
    workspace_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> ProviderDisclosureResponse:
    workspace = await service.get(workspace_id, owner_user_id=user.id)
    return _provider_disclosure(workspace, request.app.state.settings)


@router.post(
    "/{workspace_id}/provider-disclosure/ack",
    response_model=ProviderDisclosureResponse,
)
async def acknowledge_provider_disclosure(
    workspace_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> ProviderDisclosureResponse:
    workspace = await service.acknowledge_provider_disclosure(
        workspace_id, owner_user_id=user.id
    )
    return _provider_disclosure(workspace, request.app.state.settings)


# T050 (US6/FR-016): a switch that changes the embedding profile re-ingests every document, so it
# needs explicit confirmation, and a confirmed switch dispatches the rebuild (US3/T028) immediately.
# 200 when nothing profile-affecting changed, 202 when a rebuild was dispatched, 409 with a preview
# when confirmation is missing.
@router.post("/{workspace_id}/provider", response_model=ProviderConfigResponse)
async def switch_workspace_provider(
    workspace_id: UUID,
    payload: ProviderSwitchRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> ProviderConfigResponse:
    workspace = await service.get(workspace_id, owner_user_id=user.id)
    settings = request.app.state.settings

    proposed_settings = settings.model_copy(
        update={
            "generation_provider": payload.generation_provider,
            "embedding_provider": payload.embedding_provider,
        }
    )
    try:
        # Refuse a switch whose credentials are missing rather than persisting a configuration the
        # process cannot call; the rebuild would otherwise abort after doing real work (DB43).
        validate_selected_provider_configuration(proposed_settings)
        proposed_profile = configured_embedding_profile(proposed_settings)
    except ProviderConfigurationInvalid as exc:
        raise ProviderSwitchNotConfigured(
            payload.generation_provider, payload.embedding_provider
        ) from exc

    current_profile = configured_embedding_profile(settings)
    profile_changed = proposed_profile != current_profile

    # DB68: the switch is serialised for the rest of this transaction, so two switches that arrive
    # together cannot both pass the rebuild guard below and both dispatch a rebuild.
    await acquire_provider_switch_lock(session)

    # DB57: the provider choice is one process-wide row, so the switch must not race any workspace's
    # rebuild. A per-workspace check would allow a switch to be confirmed while another workspace is
    # rebuilding, and that rebuild would then finish under the profile it captured at dispatch time
    # while `app_settings` already reports the new one.
    if await active_rebuild_workspace_ids(session):
        raise CorpusRebuildInProgress()

    # DB57: the preview is per workspace, because the stored configuration is global and an operator
    # confirming a switch should see every workspace it re-ingests, not only the addressed one. The
    # breakdown is scoped to the caller's own workspaces so it cannot disclose another user's names.
    workspace_counts = await service.document_counts_by_workspace(owner_user_id=user.id)
    documents_total = next(
        (count for item, count in workspace_counts if item.id == workspace.id), 0
    )

    # DB65: an acknowledgement made while every provider was local must not outlive a switch that
    # starts sending document text off the machine.
    disclosure_will_be_cleared = (
        not sends_document_text_remotely(settings)
    ) and sends_document_text_remotely(proposed_settings)

    if profile_changed and not payload.confirm_rebuild:
        raise ProviderSwitchRequiresRebuild(
            details={
                "documents_total": documents_total,
                "workspaces": [
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "documents_total": count,
                    }
                    for item, count in workspace_counts
                ],
                "current_embedding_profile": current_profile.as_dict(),
                "proposed_embedding_profile": proposed_profile.as_dict(),
                "disclosure_acknowledgement_will_be_cleared": disclosure_will_be_cleared,
            }
        )

    stored = await store_provider_config(
        session,
        generation_provider=payload.generation_provider,
        embedding_provider=payload.embedding_provider,
    )
    apply_stored_provider_config(settings, stored)

    # DB65: clearing lives after the switch is applied, so it reflects the configuration that is
    # actually in force. Every workspace's ack goes, because the setting is process-wide.
    acknowledgement_cleared = False
    if disclosure_will_be_cleared:
        await service.clear_provider_disclosure_acknowledgements()
        acknowledgement_cleared = True

    rebuild_status: CorpusRebuildStatus | None = None
    if profile_changed:
        rebuild = CorpusRebuild(
            workspace_id=workspace.id,
            status="pending",
            reason="provider_switch",
            documents_total=0,
            documents_completed=0,
        )
        session.add(rebuild)
        await session.flush()
        # The cached bundle was built from the old provider configuration, so it is replaced before
        # the rebuild is dispatched; the superseded one is closed once this response is sent. A
        # concurrent request could still hold the old bundle, which is the price of not closing a
        # client out from under an in-flight call (see the iteration record's risks).
        previous_factory = request.app.state.provider_bundle_factory
        request.app.state.provider_bundle_factory = CachedProviderBundleFactory(settings)
        background_tasks.add_task(
            dispatch_pending_rebuild,
            session_factory,
            rebuild_id=rebuild.id,
            settings=settings,
            providers=request.app.state.provider_bundle_factory(),
            request_id=str(uuid4()),
            logger=_logger,
        )
        background_tasks.add_task(previous_factory.aclose)
        response.status_code = status.HTTP_202_ACCEPTED
        rebuild_status = _corpus_rebuild_status(rebuild)

    return ProviderConfigResponse(
        generation_provider=settings.generation_provider,
        embedding_provider=settings.embedding_provider,
        embedding_profile_changed=profile_changed,
        documents_total=documents_total,
        disclosure_acknowledgement_cleared=acknowledgement_cleared,
        rebuild=rebuild_status,
    )
