from collections.abc import Mapping
from typing import Any


def _pdf_bbox(locator: Mapping[str, Any]) -> list[float] | None:
    box = locator.get("bbox")
    if (
        not isinstance(box, list)
        or len(box) != 4
        or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in box
        )
    ):
        return None
    return [float(value) for value in box]


def _source_kind_from_media_type(media_type: str | None) -> str:
    media_type = (media_type or "").lower()
    if media_type == "text/markdown":
        return "markdown"
    if media_type == "text/plain":
        return "text"
    if media_type == "application/pdf":
        return "pdf"
    if "wordprocessingml" in media_type:
        return "docx"
    return "text"
