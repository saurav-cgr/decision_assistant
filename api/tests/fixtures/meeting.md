Architecture Sync
=================

Date: 2026-07-15
Participants: Maya, Ravi, Elena
Project: Atlas

## Authentication

The team proposed postponing authentication until the core import flow was stable.
Maya owned the decision because identity work depended on the API boundary.

## Storage

PostgreSQL with pgvector was accepted for keyword and semantic retrieval.
SQLite was considered, but rejected because the MVP needs vector search and full-text search in one database.
