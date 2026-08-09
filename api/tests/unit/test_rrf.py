import pytest

from decision_assistant.retrieval.rrf import reciprocal_rank_fusion


def test_rrf_merges_duplicates_and_preserves_rank_sources() -> None:
    fused = reciprocal_rank_fusion(
        {
            "semantic": ["p2", "p1"],
            "keyword": ["p1", "p3"],
        },
        k=60,
    )

    assert [item.id for item in fused] == ["p1", "p2", "p3"]
    assert fused[0].source_ranks == {"semantic": 2, "keyword": 1}
    assert fused[0].score == pytest.approx((1 / 62) + (1 / 61))
