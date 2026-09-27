"""DB68: two provider switches confirmed at the same time must serialise.

`POST /workspaces/{id}/provider` refuses to switch while a rebuild is in flight, but that guard is a
plain read and the unique partial index on `corpus_rebuilds` is per workspace. Two switches arriving
together on *different* workspaces could therefore both see no active rebuild, both persist
`app_settings` and both dispatch a rebuild, with the last write winning — DB57's process-wide
divergence reached through a race. `acquire_provider_switch_lock` closes it with a transaction-scoped
advisory lock taken before the guard is read.

These tests need two real, independent transactions, so they open their own engine/sessions instead
of the shared `db_session` fixture — that fixture binds everything in a test to one session, which
would make the lock re-entrant and the race untestable. Nothing is written, so there are no rows to
clean up.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from decision_assistant.db import create_engine
from decision_assistant.workspace.provider_config import acquire_provider_switch_lock

#: How long to let a switch that should be blocked stay blocked before asserting it did.
BLOCKED_OBSERVATION_SECONDS = 0.2
#: Upper bound for a lock acquisition that must succeed once the holder has released.
UNBLOCKED_TIMEOUT_SECONDS = 10.0


@pytest.mark.asyncio
async def test_second_provider_switch_waits_for_the_first_transaction() -> None:
    engine = create_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    first: AsyncSession = factory()
    second: AsyncSession = factory()
    third: AsyncSession = factory()
    try:
        # The first switch's transaction holds the lock but has not ended.
        await acquire_provider_switch_lock(first)

        waiter = asyncio.create_task(acquire_provider_switch_lock(second))
        await asyncio.sleep(BLOCKED_OBSERVATION_SECONDS)
        assert not waiter.done(), (
            "the second switch was not blocked by the first one's advisory lock, so two "
            "switches on different workspaces could both pass the rebuild guard (DB68)"
        )

        # Ending the first transaction releases the lock and the waiting switch proceeds.
        await first.rollback()
        await asyncio.wait_for(waiter, timeout=UNBLOCKED_TIMEOUT_SECONDS)

        # The waiter really holds the lock now: a third switch must block behind it.
        blocked_again = asyncio.create_task(acquire_provider_switch_lock(third))
        await asyncio.sleep(BLOCKED_OBSERVATION_SECONDS)
        assert not blocked_again.done(), (
            "the lock was released to the first waiter but not re-acquired, so it is not "
            "actually serialising switches"
        )

        await second.rollback()
        await asyncio.wait_for(blocked_again, timeout=UNBLOCKED_TIMEOUT_SECONDS)
    finally:
        await third.rollback()
        await second.rollback()
        await first.rollback()
        await third.close()
        await second.close()
        await first.close()
        await engine.dispose()
