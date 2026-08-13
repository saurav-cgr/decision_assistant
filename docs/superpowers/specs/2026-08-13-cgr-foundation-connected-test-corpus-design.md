# CGR Foundation Connected Test Corpus Design

## Goal

Create a synthetic, connected corpus for exercising Decision Memory Assistant ingestion, extraction, retrieval, citation, conflict, abstention, and timeline behavior. The corpus will contain exactly 10 scenario documents based on concepts found in the local `foundation` application.

## Output

Place final artifacts in `test_corpus/cgr_foundation_connected/`.

- Exactly 10 ingestible documents: 3 Markdown, 3 plain text, 2 DOCX, and 2 PDF.
- One corpus guide outside the 10-document count. It will list expected decisions, conflicts, supersessions, and deliberately unsupported questions.
- One MD5 checksum manifest outside the 10-document count for file-integrity testing.
- Stable, descriptive filenames prefixed `01` through `10` so chronological order is visible.

The user's reference to "md5" is treated as Markdown plus a conventional `.md5` checksum manifest. The application itself accepts `.md`, `.txt`, `.docx`, and `.pdf`.

## Corpus Narrative

The fictional "Northstar Foundation Rollout" follows one organization configuring and piloting CGR Foundation over several months. Recurring people, teams, dates, module names, and project terms connect all documents. All personal and organization data is synthetic; no credentials, secrets, or production records will be copied.

The documents will use Foundation concepts evidenced by the codebase, while avoiding claims that require undocumented product guarantees. Covered areas include:

- Survey and Survey Response
- core module enablement and configuration
- workflows, states, transitions, and authorisers
- authentication providers, password login, SSO, and TOTP/MFA
- authorization, roles, teams, permission sets, and sensitivity/clearance
- risks, controls, audits, incidents, tasks, reports, forms, and CSV import/export

## Document Set

| # | Format | Working title | Primary scenario |
|---|---|---|---|
| 01 | Markdown | Rollout kickoff record | Initial module scope, owners, rollout principles |
| 02 | PDF | Authentication architecture proposal | Password vs SSO, provisional MFA decision, alternatives |
| 03 | DOCX | Survey pilot workshop | Anonymous vs identified responses, survey ownership |
| 04 | TXT | Workflow configuration notes | Risk approval states, authoriser roles, two-stage proposal |
| 05 | Markdown | Risk and control mapping | Links survey findings to risks, controls, tasks, reporting |
| 06 | PDF | Access incident retrospective | Permission-set error, excessive access, corrective actions |
| 07 | TXT | Internal audit findings | Evidence gaps, workflow weakness, auth control findings |
| 08 | DOCX | Steering committee decision record | Supersedes auth and workflow proposals; assigns owners |
| 09 | Markdown | Implementation and migration log | Module activation, CSV import, forms, task execution |
| 10 | TXT | Operations handover | Final operating model, open questions, unresolved evidence |

## Decision and Evidence Design

Each document will contain natural prose rather than a uniform synthetic template. Across the corpus, decisions will include dates, owners, status, rationale, alternatives, and explicit relationships when appropriate.

Three connected arcs provide cross-document reasoning:

1. **Authentication:** an early password-plus-SSO proposal is challenged after an access incident. A later steering decision makes SSO primary, restricts password use, and mandates TOTP/MFA for privileged users.
2. **Survey identity:** the pilot initially favors anonymous responses. Risk owners later require identified responses for high-risk follow-up, producing a scoped exception rather than a full reversal.
3. **Workflow approval:** an initial two-stage risk workflow is found insufficient by audit. The steering record supersedes it with a three-stage flow for high-rated risks while retaining two stages for lower-rated risks.

Supporting decisions will cover module rollout order, role ownership, control remediation, task tracking, reporting, and import validation.

## Retrieval Test Characteristics

The corpus will intentionally contain:

- repeated vocabulary across unrelated contexts to test ranking;
- paraphrases and abbreviations such as MFA/TOTP and SSO/identity provider;
- provisional decisions later superseded by explicit final decisions;
- genuine conflicts that remain unresolved;
- partial answers spread across multiple documents;
- at least three questions whose answers are absent, requiring abstention;
- clear source anchors through headings, dates, paragraph boundaries, and PDF pages;
- tables in DOCX files to exercise table-cell extraction without relying on complex layout.

No prompt-injection text, malware-like payloads, scanned pages, password protection, or deliberately corrupt files will be included because this corpus targets decision behavior rather than security-format rejection.

## Presentation

Documents will resemble varied workplace artifacts: meeting notes, proposals, workshop records, configuration notes, retrospectives, audit findings, formal decisions, implementation logs, and handover notes. DOCX and PDF outputs will use restrained business styling, readable headings, page numbers, consistent margins, and accessible tables.

## Verification

- Confirm exactly 10 ingestible files and the required 3/3/2/2 format distribution.
- Parse or extract text from every file and confirm non-empty content.
- Render every DOCX and PDF page to PNG and visually inspect for clipping, overlap, broken tables, missing glyphs, and page-number defects.
- Verify expected decision phrases and cross-document entities are present.
- Generate MD5 checksums after final artifacts stabilize, then independently verify them.
- Ensure the corpus guide distinguishes expected ground truth from document content and is not included in the 10 ingestible-document count.

## Success Criteria

The corpus is complete when Decision Memory Assistant can ingest all 10 documents, the files provide meaningful tests for decisions/conflicts/supersession/abstention, each rendered document is visually clean, and the checksum manifest validates every ingestible artifact.
