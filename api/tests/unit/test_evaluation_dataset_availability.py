"""DB32: the evaluation benchmark lives in the repo, not in the api image.

Human decision (2026-09-25): keep evaluation a **development-only** surface
rather than packaging the benchmark. An installed deployment therefore has no
dataset file, and the API must say so plainly — `dataset_invalid` would tell an
operator to repair a file that was never shipped.
"""

from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.evaluation.errors import FatalEvaluationError
from decision_assistant.evaluation.service import EvaluationService


def _service(dataset_path: Path) -> EvaluationService:
    # `_load_dataset` touches only `_dataset_path`, and `__init__` reads the
    # profile dicts off its collaborators with a `{}` default, so bare objects
    # are enough — no session, executor, or judge behaviour is exercised here.
    return EvaluationService(
        session=cast(AsyncSession, cast(Any, None)),
        dataset_path=dataset_path,
        executor=object(),
        judge=object(),
    )


def test_missing_dataset_reports_evaluation_unavailable(tmp_path: Path) -> None:
    with pytest.raises(FatalEvaluationError) as raised:
        _service(tmp_path / "questions.json")._load_dataset()

    assert raised.value.code == "evaluation_unavailable"
    assert raised.value.status_code == 503
    assert raised.value.retryable is False


def test_malformed_dataset_still_reports_dataset_invalid(tmp_path: Path) -> None:
    path = tmp_path / "questions.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(FatalEvaluationError) as raised:
        _service(path)._load_dataset()

    assert raised.value.code == "dataset_invalid"
    assert raised.value.status_code == 503
