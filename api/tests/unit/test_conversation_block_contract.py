import json
from pathlib import Path

from decision_assistant.ingestion.parsers import ParsedBlock, SourceLocator

SLACK_FIXTURE = Path("tests/fixtures/conversations/slack_thread.json")
TEAMS_FIXTURE = Path("tests/fixtures/conversations/teams_thread.json")


def _assemble(source_blocks: list[tuple[object, ...]]) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    offset = 0
    for index, (text, block_type, group_path, boundary, attributes, locator) in enumerate(
        source_blocks
    ):
        if index:
            offset += 2
        start = offset
        offset += len(text)
        blocks.append(
            ParsedBlock(
                text=text,
                block_type=block_type,
                group_path=group_path,
                boundary_before=boundary,
                attributes=attributes,
                locator=locator,
                start_offset=start,
                end_offset=offset,
            )
        )
    return blocks


def adapt_slack(data: dict[str, object]) -> list[ParsedBlock]:
    group = (f"channel:{data['channel_id']}", f"thread:{data['thread_id']}")
    source_blocks: list[tuple[object, ...]] = []
    for message in sorted(data["messages"], key=lambda m: m["ts"]):  # type: ignore[arg-type]
        locator: SourceLocator = {
            "kind": "slack_message",
            "workspace_id": data["workspace_id"],
            "channel_id": data["channel_id"],
            "thread_id": data["thread_id"],
            "message_id": message["message_id"],
            "message_url": data["message_url"],
        }
        rendered = f"[{message['ts']}] {message['author']}: {message['text']}"
        source_blocks.append(
            (
                rendered,
                "message",
                group,
                "soft",
                {"author": message["author"], "ts": message["ts"]},
                locator,
            )
        )
        for attachment in message.get("attachments", []):
            attachment_text = (
                f"[{message['ts']}] {message['author']}: "
                f"[attachment: {attachment['name']}] {attachment['text']}"
            )
            source_blocks.append(
                (
                    attachment_text,
                    "attachment",
                    group,
                    "none",
                    {
                        "name": attachment["name"],
                        "mime_type": attachment["mime_type"],
                    },
                    {**locator, "attachment_name": attachment["name"]},
                )
            )
    return _assemble(source_blocks)


def adapt_teams(data: dict[str, object]) -> list[ParsedBlock]:
    group = (
        f"team:{data['team_id']}",
        f"channel:{data['channel_id']}",
        f"conversation:{data['conversation_id']}",
    )
    source_blocks: list[tuple[object, ...]] = []
    for message in sorted(data["messages"], key=lambda m: m["ts"]):  # type: ignore[arg-type]
        locator: SourceLocator = {
            "kind": "teams_message",
            "tenant_id": data["tenant_id"],
            "team_id": data["team_id"],
            "channel_id": data["channel_id"],
            "conversation_id": data["conversation_id"],
            "message_id": message["message_id"],
            "message_url": data["message_url"],
        }
        rendered = f"[{message['ts']}] {message['author']}: {message['text']}"
        source_blocks.append(
            (
                rendered,
                "message",
                group,
                "soft",
                {"author": message["author"], "ts": message["ts"]},
                locator,
            )
        )
        for attachment in message.get("attachments", []):
            attachment_text = (
                f"[{message['ts']}] {message['author']}: "
                f"[attachment: {attachment['name']}] {attachment['text']}"
            )
            source_blocks.append(
                (
                    attachment_text,
                    "attachment",
                    group,
                    "none",
                    {
                        "name": attachment["name"],
                        "mime_type": attachment["mime_type"],
                    },
                    {**locator, "attachment_name": attachment["name"]},
                )
            )
    return _assemble(source_blocks)


def message_range_locator(
    data: dict[str, object],
    *,
    blocks: list[ParsedBlock],
) -> SourceLocator:
    source = data["kind"]
    message_blocks = [block for block in blocks if block.block_type == "message"]
    return {
        "kind": "message_range",
        "source": source,
        "first_message_id": message_blocks[0].locator["message_id"],
        "last_message_id": message_blocks[-1].locator["message_id"],
        "message_urls": [block.locator["message_url"] for block in message_blocks],
    }


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_slack_blocks_are_chronological_and_canonical() -> None:
    blocks = adapt_slack(_load(SLACK_FIXTURE))

    message_blocks = [block for block in blocks if block.block_type == "message"]
    assert [block.locator["message_id"] for block in message_blocks] == [
        "1712345678.000001",
        "1712345680.000002",
    ]
    assert message_blocks[0].text.startswith(
        "[2026-08-15T10:20:00Z] Alice: We should postpone authentication"
    )
    assert message_blocks[1].text == (
        "[2026-08-15T10:22:00Z] Bob: Agreed. Maya will own the rollout."
    )
    for block in message_blocks:
        assert block.group_path == (
            "channel:C0123ABC",
            "thread:1712345678.000001",
        )
        assert block.locator["kind"] == "slack_message"
        assert block.locator["workspace_id"] == "T01234567"
        assert block.locator["channel_id"] == "C0123ABC"
        assert block.locator["thread_id"] == "1712345678.000001"
        assert block.locator["message_url"] == (
            "https://acme.slack.com/archives/C0123ABC/p1712345678000001"
        )


def test_slack_excludes_tokens_payload_and_reactions() -> None:
    blocks = adapt_slack(_load(SLACK_FIXTURE))
    for block in blocks:
        serialized = json.dumps(block.locator) + json.dumps(block.attributes)
        assert "token" not in serialized.lower()
        assert "reactions" not in serialized.lower()
        assert "full raw payload" not in serialized.lower()


def test_slack_attachment_is_adjacent_block_with_bounded_attributes() -> None:
    blocks = adapt_slack(_load(SLACK_FIXTURE))

    attachment = blocks[1]
    assert attachment.block_type == "attachment"
    assert attachment.boundary_before == "none"
    assert attachment.attributes == {
        "name": "roadmap.pdf",
        "mime_type": "application/pdf",
    }
    assert attachment.locator["attachment_name"] == "roadmap.pdf"
    assert attachment.text.startswith(
        "[2026-08-15T10:20:00Z] Alice: [attachment: roadmap.pdf]"
    )
    assert attachment.group_path == blocks[0].group_path


def test_slack_message_range_locator_aggregates_group() -> None:
    data = _load(SLACK_FIXTURE)
    blocks = adapt_slack(data)

    locator = message_range_locator(data, blocks=blocks)

    assert locator["kind"] == "message_range"
    assert locator["source"] == "slack"
    assert locator["first_message_id"] == "1712345678.000001"
    assert locator["last_message_id"] == "1712345680.000002"
    assert len(locator["message_urls"]) == 2


def test_teams_blocks_conform_to_discriminator_contract() -> None:
    blocks = adapt_teams(_load(TEAMS_FIXTURE))

    message_blocks = [block for block in blocks if block.block_type == "message"]
    assert [block.text for block in message_blocks] == [
        "[2026-08-15T11:00:00Z] Carol: The beta stays employee-only.",
        "[2026-08-15T11:05:00Z] Dave: Confirmed. Jonah approves security.",
    ]
    assert message_blocks[0].group_path == (
        "team:team-123",
        "channel:channel-456",
        "conversation:thread-789",
    )
    for block in message_blocks:
        assert block.locator["kind"] == "teams_message"
        assert block.locator["tenant_id"] == "tenant-abc"
        assert block.locator["team_id"] == "team-123"
        assert block.locator["channel_id"] == "channel-456"
        assert block.locator["conversation_id"] == "thread-789"
        assert block.locator["message_url"] == (
            "https://teams.microsoft.com/l/message/channel-456/thread-789"
        )

    attachments = [block for block in blocks if block.block_type == "attachment"]
    assert [block.attributes["name"] for block in attachments] == ["notes.txt"]


def test_teams_message_range_locator_reports_source_and_ids() -> None:
    data = _load(TEAMS_FIXTURE)
    blocks = adapt_teams(data)

    locator = message_range_locator(data, blocks=blocks)

    assert locator["kind"] == "message_range"
    assert locator["source"] == "teams"
    assert locator["first_message_id"] == "msg-0001"
    assert locator["last_message_id"] == "msg-0002"
