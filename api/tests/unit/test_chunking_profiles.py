import pytest
from pydantic import ValidationError

from decision_assistant.config import Settings
from decision_assistant.ingestion.profiles import (
    CHUNKING_PROFILE_PRESETS,
    CURRENT_CHUNKING_PROFILE,
    DEFAULT_CHUNKING_PROFILE_PRESET,
    resolve_chunking_profile,
)


def test_three_presets_are_all_structural_token_v2() -> None:
    assert set(CHUNKING_PROFILE_PRESETS) == {"baseline", "compact", "expanded"}
    for preset in CHUNKING_PROFILE_PRESETS.values():
        assert preset["algorithm"] == "structural-token-v2"
        assert preset["encoding"] == "cl100k_base"


def test_preset_token_budgets() -> None:
    assert CHUNKING_PROFILE_PRESETS["baseline"] == {
        "algorithm": "structural-token-v2",
        "encoding": "cl100k_base",
        "target_tokens": 450,
        "max_tokens": 600,
        "overlap_tokens": 60,
    }
    assert CHUNKING_PROFILE_PRESETS["compact"] == {
        "algorithm": "structural-token-v2",
        "encoding": "cl100k_base",
        "target_tokens": 250,
        "max_tokens": 350,
        "overlap_tokens": 40,
    }
    assert CHUNKING_PROFILE_PRESETS["expanded"] == {
        "algorithm": "structural-token-v2",
        "encoding": "cl100k_base",
        "target_tokens": 700,
        "max_tokens": 900,
        "overlap_tokens": 80,
    }


def test_default_preset_is_baseline() -> None:
    assert DEFAULT_CHUNKING_PROFILE_PRESET == "baseline"
    assert CURRENT_CHUNKING_PROFILE is CHUNKING_PROFILE_PRESETS["baseline"]
    assert CURRENT_CHUNKING_PROFILE["algorithm"] == "structural-token-v2"


@pytest.mark.parametrize("preset", ["baseline", "compact", "expanded"])
def test_resolver_returns_each_preset(preset: str) -> None:
    assert resolve_chunking_profile(preset) == CHUNKING_PROFILE_PRESETS[preset]


def test_resolver_rejects_unknown_preset() -> None:
    with pytest.raises(ValueError):
        resolve_chunking_profile("bogus")


def test_settings_default_is_baseline() -> None:
    settings = Settings()
    assert settings.chunking_profile_preset == "baseline"
    assert (
        resolve_chunking_profile(settings.chunking_profile_preset)["algorithm"]
        == "structural-token-v2"
    )


@pytest.mark.parametrize("preset", ["baseline", "compact", "expanded"])
def test_settings_accepts_valid_presets(preset: str) -> None:
    assert Settings(chunking_profile_preset=preset).chunking_profile_preset == preset


def test_settings_rejects_invalid_preset() -> None:
    with pytest.raises(ValidationError):
        Settings(chunking_profile_preset="bogus")
