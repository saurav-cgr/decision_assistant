"""Offline, deterministic token counting for chunk budgeting.

``cl100k_base`` is a budgeting approximation, not a claim to reproduce any
provider's private tokenizer. The counter must return stable counts offline;
network ``count_tokens`` calls are never used during chunking.
"""

from functools import lru_cache
from typing import Protocol

import tiktoken

DEFAULT_ENCODING = "cl100k_base"


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class TiktokenCounter:
    def __init__(self, encoding: str = DEFAULT_ENCODING) -> None:
        self._encoding = tiktoken.get_encoding(encoding)

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))


@lru_cache(maxsize=1)
def get_token_counter() -> TokenCounter:
    return TiktokenCounter()
