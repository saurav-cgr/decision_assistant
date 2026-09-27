"""Hybrid retrieval over passages: profiles, filters, capping and cache collapsing.

The decision-evidence and trace-API tests live in `test_hybrid_retrieval_decisions.py`, and the
shared corpus scaffolding in `tests/support/retrieval_fixtures.py` (DB53: AGENTS.md's 500-line cap).
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.ingestion.models import EmbeddingCache, Passage
from decision_assistant.providers.base import EmbeddingPurpose
from decision_assistant.providers.fakes import FakeEmbeddingProvider
from decision_assistant.retrieval.models import RetrievalTrace
from decision_assistant.retrieval.repository import RetrievalRepository
from decision_assistant.retrieval.schemas import RetrievalFilters, RetrievalSearchRequest
from decision_assistant.retrieval.service import HybridRetrievalService, RetrievalConfig
from decision_assistant.workspace.embedding_profile import (
    CorpusResetRequired,
    embedding_profile_fingerprint,
)
from tests.support.retrieval_fixtures import (
    EMBEDDING_PROFILE,
    create_passage,
    create_version,
    create_workspace,
)


@pytest.mark.asyncio
async def test_hybrid_retrieval_abstains_before_provider_call_when_reindex_required(
    db_session: AsyncSession,
) -> None:
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    workspace = await create_workspace(db_session)
    _, version = await create_version(db_session, workspace, name="legacy.md")
    passage = await create_passage(
        db_session,
        version,
        sequence_number=0,
        content="Legacy authentication decision.",
        embedding=[0.0] * 768,
    )
    passage.embedding_profile = {"provider": "legacy", "model": "old"}
    cache = await db_session.get(EmbeddingCache, passage.embedding_cache_id)
    assert cache is not None
    cache.embedding_profile_fingerprint = embedding_profile_fingerprint(
        passage.embedding_profile
    )
    await db_session.flush()

    with pytest.raises(CorpusResetRequired) as error:
        await HybridRetrievalService(
            session=db_session,
            embedding_provider=embedding_provider,
        ).search(
            RetrievalSearchRequest(question="authentication"),
            request_id="retrieval-needs-migration",
            workspace_id=workspace.id,
        )

    assert error.value.code == "corpus_reset_required"
    assert embedding_provider.purposes == []


@pytest.mark.asyncio
async def test_vector_query_filters_active_versions_by_configured_passage_profile(
    db_session: AsyncSession,
) -> None:
    workspace = await create_workspace(db_session)
    _, active_version = await create_version(
        db_session,
        workspace,
        name="profile-filter.md",
    )
    matching = await create_passage(
        db_session,
        active_version,
        sequence_number=0,
        content="Matching profile.",
        embedding=[1.0] + ([0.0] * 767),
    )
    mismatched = await create_passage(
        db_session,
        active_version,
        sequence_number=1,
        content="Mismatched profile.",
        embedding=[1.0] + ([0.0] * 767),
    )
    mismatched.embedding_profile = {
        **EMBEDDING_PROFILE,
        "adapter_config_version": "legacy-v0",
    }
    mismatched_cache = await db_session.get(
        EmbeddingCache,
        mismatched.embedding_cache_id,
    )
    assert mismatched_cache is not None
    mismatched_cache.embedding_profile_fingerprint = embedding_profile_fingerprint(
        mismatched.embedding_profile
    )
    _, retired_version = await create_version(
        db_session,
        workspace,
        name="retired-profile.md",
        state="retired",
    )
    retired = await create_passage(
        db_session,
        retired_version,
        sequence_number=0,
        content="Retired profile.",
        embedding=[1.0] + ([0.0] * 767),
    )
    await db_session.flush()

    results = await RetrievalRepository(db_session).semantic_search(
        [1.0] + ([0.0] * 767),
        RetrievalFilters(),
        embedding_profile=EMBEDDING_PROFILE,
        limit=10,
        workspace_id=workspace.id,
    )

    assert [result.passage.id for result in results] == [matching.id]
    assert mismatched.id not in {result.passage.id for result in results}
    assert retired.id not in {result.passage.id for result in results}


@pytest.mark.asyncio
async def test_hybrid_retrieval_caps_sources_and_excludes_retired_versions(
    db_session: AsyncSession,
) -> None:
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    query_vector = (
        await embedding_provider.embed(
            ["authentication"], purpose=EmbeddingPurpose.DOCUMENT
        )
    )[0]
    workspace = await create_workspace(db_session)
    _, active_version = await create_version(
        db_session,
        workspace,
        name="active.md",
        participants=["Maya"],
    )
    _, retired_version = await create_version(
        db_session,
        workspace,
        name="retired.md",
        state="retired",
        participants=["Maya"],
    )
    active_passages = [
        await create_passage(
            db_session,
            active_version,
            sequence_number=index,
            content=f"Authentication decision evidence number {index}.",
            embedding=query_vector,
        )
        for index in range(22)
    ]
    retired = await create_passage(
        db_session,
        retired_version,
        sequence_number=0,
        content="Authentication evidence from a retired version.",
        embedding=query_vector,
    )
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding_provider,
    )

    result = await service.search(
        RetrievalSearchRequest(question="authentication"),
        request_id="retrieval-1",
        workspace_id=workspace.id,
    )
    trace = await db_session.get(RetrievalTrace, result.trace_id)

    assert trace is not None
    assert len(trace.semantic_candidates) == 20
    assert len(trace.keyword_candidates) == 20
    assert retired.id not in {item.passage_id for item in result.results}
    assert str(retired.id) not in {
        candidate["passage_id"]
        for candidates in (
            trace.semantic_candidates,
            trace.keyword_candidates,
            trace.decision_candidates,
        )
        for candidate in candidates
    }
    active_ids = {str(passage.id) for passage in active_passages}
    assert set(trace.selected_passage_ids) <= active_ids
    assert len(trace.selected_passage_ids) == 5
    assert set(trace.timings) >= {
        "semantic_ms",
        "keyword_ms",
        "decision_ms",
        "fusion_ms",
        "total_ms",
    }
    assert trace.configuration == {
        "semantic_limit": 20,
        "keyword_limit": 20,
        "decision_limit": 20,
        "rrf_k": 60,
        "top_k": 5,
        "rerank_enabled": False,
        "rerank_candidate_limit": 12,
        "rerank_min_candidates": 6,
        "rerank_final_limit": 5,
        "strategy": "passage_hybrid",
    }


@pytest.mark.asyncio
async def test_retrieval_collapses_passages_sharing_an_embedding_cache_entry(
    db_session: AsyncSession,
) -> None:
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    vector = await embedding_provider.embed(
        ["authentication"], purpose=EmbeddingPurpose.DOCUMENT
    )
    workspace = await create_workspace(db_session)
    _, first_version = await create_version(db_session, workspace, name="a.md")
    _, second_version = await create_version(db_session, workspace, name="b.md")
    first = await create_passage(
        db_session,
        first_version,
        sequence_number=0,
        content="Authentication was postponed.",
        embedding=vector[0],
    )
    second = await create_passage(
        db_session,
        second_version,
        sequence_number=0,
        content=first.content,
        embedding=vector[0],
    )
    assert first.embedding_cache_id == second.embedding_cache_id

    results = await HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding_provider,
    ).search(
        RetrievalSearchRequest(question="authentication"),
        request_id="deduplicated-retrieval",
        workspace_id=workspace.id,
    )
    trace = await db_session.get(RetrievalTrace, results.trace_id)

    assert [item.passage_id for item in results.results] == [first.id]
    assert [item.passage_id for item in results.results[0].equivalent_sources] == [
        first.id,
        second.id,
    ]
    assert trace is not None
    assert len(trace.semantic_candidates) == 1
    assert len(trace.keyword_candidates) == 1
    assert trace.fused_results[0]["passage_id"] == str(first.id)
    selected_metadata = trace.selected_passage_metadata[0]
    assert selected_metadata["embedding_cache_id"] == str(first.embedding_cache_id)
    assert [
        item["passage_id"] for item in selected_metadata["equivalent_sources"]
    ] == [str(first.id), str(second.id)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy", "expected_kind"),
    [
        ("sentence_expanded", "sentence"),
        ("parent_child_merged", "parent"),
    ],
)
async def test_sentence_strategies_select_citation_valid_expanded_evidence(
    db_session: AsyncSession,
    strategy: str,
    expected_kind: str,
) -> None:
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    vector = (
        await embedding_provider.embed(["authentication"], purpose=EmbeddingPurpose.DOCUMENT)
    )[0]
    workspace = await create_workspace(db_session)
    _, version = await create_version(db_session, workspace, name=f"{strategy}.md")
    parent = await create_passage(
        db_session,
        version,
        sequence_number=0,
        content="Authentication was postponed. The import flow needed work. Security approved the plan.",
        embedding=vector,
        retrieval_unit_kind="parent",
    )
    children = [
        await create_passage(
            db_session,
            version,
            sequence_number=index + 1,
            content=content,
            embedding=vector,
            retrieval_unit_kind="sentence",
            parent_passage_id=parent.id,
        )
        for index, content in enumerate(
            [
                "Authentication was postponed.",
                "The import flow needed work.",
                "Security approved the plan.",
            ]
        )
    ]
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding_provider,
        config=RetrievalConfig(strategy=strategy),  # type: ignore[arg-type]
    )

    response = await service.search(
        RetrievalSearchRequest(question="authentication"),
        request_id=strategy,
        workspace_id=workspace.id,
    )
    trace = await db_session.get(RetrievalTrace, response.trace_id)

    assert trace is not None
    assert all(
        item.passage_id
        in ({parent.id} if expected_kind == "parent" else {child.id for child in children})
        for item in response.results
    )
    assert all(
        item["retrieval_strategy"] == strategy
        and item["retrieval_root_ids"]
        for item in trace.selected_passage_metadata
    )
    if strategy == "sentence_expanded":
        assert {item.passage_id for item in response.results} == {item.id for item in children}
    else:
        assert [item.passage_id for item in response.results] == [parent.id]


@pytest.mark.asyncio
async def test_explicit_metadata_filters_apply_before_ranking(
    db_session: AsyncSession,
) -> None:
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    query_vector = (
        await embedding_provider.embed(
            ["authentication"], purpose=EmbeddingPurpose.DOCUMENT
        )
    )[0]
    workspace = await create_workspace(db_session)
    variants = [
        ("match.md", "text/markdown", "Atlas", date(2026, 7, 15), ["Maya"]),
        ("wrong-project.md", "text/markdown", "Beta", date(2026, 7, 15), ["Maya"]),
        ("wrong-date.md", "text/markdown", "Atlas", date(2025, 7, 15), ["Maya"]),
        ("wrong-type.txt", "text/plain", "Atlas", date(2026, 7, 15), ["Maya"]),
        ("wrong-person.md", "text/markdown", "Atlas", date(2026, 7, 15), ["Ravi"]),
    ]
    passages: dict[str, Passage] = {}
    for name, media_type, project, document_date, participants in variants:
        _, version = await create_version(
            db_session,
            workspace,
            name=name,
            media_type=media_type,
            project=project,
            document_date=document_date,
            participants=participants,
        )
        passages[name] = await create_passage(
            db_session,
            version,
            sequence_number=0,
            content="Authentication was postponed.",
            embedding=query_vector,
        )
    service = HybridRetrievalService(
        session=db_session,
        embedding_provider=embedding_provider,
    )

    result = await service.search(
        RetrievalSearchRequest(
            question="authentication",
            filters=RetrievalFilters(
                person="Maya",
                date_from=date(2026, 7, 1),
                date_to=date(2026, 7, 31),
                project="Atlas",
                document_type="text/markdown",
            ),
        ),
        request_id="retrieval-filtered",
        workspace_id=workspace.id,
    )

    assert [item.passage_id for item in result.results] == [passages["match.md"].id]
    trace = await db_session.get(RetrievalTrace, result.trace_id)
    assert trace is not None
    assert trace.filters == {
        "person": "Maya",
        "date_from": "2026-07-01",
        "date_to": "2026-07-31",
        "project": "Atlas",
        "document_type": "text/markdown",
    }
