# Feature Specification: Single-Tenant Local Production Readiness

**Feature Branch**: `002-production-readiness`

**Created**: 2026-09-24

**Status**: Draft

**Input**: User description: "Single-tenant, run-on-own-machine production readiness for the decision assistant. Drops horizontal scale, RBAC, SSO, rate limits, object storage, monitoring dashboards, and the CI benchmark gate. Prioritizes packaging/distribution, localhost-only binding, durable ingestion across restarts, upgrade-without-data-loss, backup/restore, generated secrets, single-user auth, privacy/offline mode, diagnosability, upload safety, CI, release process, failure-state UX, prompt-injection fixtures, and user docs."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Install and run without a dev environment (Priority: P1)

A user downloads the app, runs one install command and one start command, and gets a working
decision assistant without cloning source, running `npm install`, or installing a Python
toolchain.

**Why this priority**: nothing else in this feature matters if there is no distributable artifact
to install, back up, upgrade, or use offline.

**Independent Test**: on a clean machine with only the chosen runtime prerequisite installed, run
the documented install and start commands and reach a usable UI without any dev-server or
source-mount step.

**Acceptance Scenarios**:

1. **Given** a clean machine with Docker Desktop (or equivalent) installed, **When** the user runs
   the documented one-command install and start, **Then** the web UI and API become reachable
   using only published, version-pinned images with no source bind-mounts.
2. **Given** the app is installed, **When** the user inspects the running services, **Then** every
   published port is bound to localhost only and the database port is not exposed to the network.
3. **Given** the app is running, **When** the user checks the "about" or "settings" view, **Then**
   the current app version is shown.

---

### User Story 2 - Ingestion survives interruption (Priority: P1)

A user uploads a document, the machine sleeps, reboots, or the app is stopped mid-ingestion, and
when the app comes back the document finishes processing instead of staying stuck.

**Why this priority**: laptops sleep and reboot constantly; a silently stuck "processing" document
looks like data loss to the user and erodes trust in the tool.

**Independent Test**: start ingestion of a document, kill the API process before it completes,
restart the app, and confirm the document reaches a terminal state (ingested or a surfaced error)
without manual intervention.

**Acceptance Scenarios**:

1. **Given** a document mid-ingestion, **When** the app is stopped and restarted, **Then** the
   in-progress job is detected on startup and resumed or restarted automatically.
2. **Given** a job that fails after retries, **When** the user views the document list, **Then**
   the document shows a clear failed state with a retry action, not an indefinite "processing"
   state.
3. **Given** an evaluation run mid-flight, **When** the app restarts, **Then** the same recovery
   behavior applies to evaluation jobs.

---

### User Story 3 - Upgrade without losing decisions or history (Priority: P1)

A user upgrades to a new app version that changes the embedding, chunking, or parser profile, and
their existing decisions, conversations, and documents survive the upgrade; the corpus rebuilds
itself in the background instead of requiring the user to run manual reset commands.

**Why this priority**: this is the data-loss risk identified as the biggest gap; a local user has
no separate backup system to fall back on unless the app gives them one.

**Independent Test**: seed a workspace with decisions, conversations, and ingested documents,
upgrade to a build with a changed corpus profile, and confirm the app detects
`corpus_reset_required`, rebuilds retrieval data from preserved uploads automatically, and leaves
decisions and conversations intact throughout.

**Acceptance Scenarios**:

1. **Given** a running app with existing data, **When** the user starts an upgraded version,
   **Then** pending database migrations are applied automatically and a backup is taken first.
2. **Given** a version change that requires a corpus reset, **When** the app detects
   `corpus_reset_required` on startup, **Then** it automatically re-ingests from preserved
   uploads in the background and shows rebuild progress in the UI.
3. **Given** a corpus rebuild in progress, **When** the user opens an existing decision or
   conversation, **Then** that data is still present and readable, even though retrieval-backed
   answers may be degraded until the rebuild finishes.

---

### User Story 4 - Back up and restore user data (Priority: P2)

A user runs a single backup command before a risky change (upgrade, provider switch, uninstall)
and can restore from it if something goes wrong.

**Why this priority**: the automatic upgrade rebuild (User Story 3) reduces but does not eliminate
risk; users need a manual safety net they control.

**Independent Test**: run the backup command, delete the app's data volumes, run the restore
command, and confirm decisions, conversations, and documents are back.

**Acceptance Scenarios**:

1. **Given** a running app, **When** the user runs the backup command, **Then** it produces a
   database dump and an archive of uploaded documents, timestamped and stored outside the Docker
   volumes.
2. **Given** a backup archive, **When** the user runs the restore command, **Then** the database
   and uploads are restored to the backed-up state.
3. **Given** the documented destructive commands, **When** the user reads the docs or runs a
   volume-affecting command, **Then** they see a prominent warning against commands that would
   delete volumes without a prior backup.

---

### User Story 5 - First-run setup with no shared secrets (Priority: P2)

A new user starts the app for the first time and gets unique, locally generated credentials
instead of shared defaults, plus a clear place to enter their model-provider API key.

**Why this priority**: shared default credentials on a localhost-bound service are still a
meaningful exposure risk on shared machines or misconfigured networks; generated secrets are cheap
to add.

**Independent Test**: run first-run setup on a clean install and confirm the JWT secret and
database password are freshly generated (not the repository defaults) and the app refuses to start
with placeholder secrets.

**Acceptance Scenarios**:

1. **Given** a first run with no existing config, **When** setup completes, **Then**
   `AUTH_JWT_SECRET` and the database password are freshly generated and unique to that
   installation.
2. **Given** first-run setup, **When** the user is prompted for a model-provider API key,
   **Then** it is stored locally, never logged, and never included in diagnostics output.
3. **Given** invalid or missing required configuration at startup, **When** the app starts,
   **Then** it fails with a clear, actionable message instead of running in a broken state.

---

### User Story 6 - Understand and consent to where documents go (Priority: P2)

A user is told, before uploading anything, whether their document text will leave the machine
(cloud provider) or stay local (offline provider), and can choose the offline mode if they want
one.

**Why this priority**: sending private documents to a cloud API by default without disclosure is a
privacy problem specific to a local, personal-data tool.

**Independent Test**: on first run, confirm the user sees a disclosure naming the active
provider and whether document text leaves the machine, and can select a fully offline provider
before ingesting anything.

**Acceptance Scenarios**:

1. **Given** a first run with the default cloud provider configured, **When** the user reaches
   the point of uploading a document, **Then** they have already seen a disclosure stating that
   document text is sent to that provider, and they have acknowledged it.
2. **Given** a user who wants no data to leave the machine, **When** they select the offline
   provider, **Then** the app documents its install steps and a basic hardware suitability check.
3. **Given** a user switches provider after ingesting documents, **When** the switch is
   confirmed, **Then** the app tells them this triggers a corpus rebuild (User Story 3) before
   they confirm.

---

### User Story 7 - Diagnose problems without built-in telemetry (Priority: P3)

A user hits a problem, and without any data leaving the machine by default, they can generate a
diagnostics bundle (logs, versions, sanitized config) to send to the app's maintainer manually.

**Why this priority**: without server-side telemetry, this is the only way a maintainer can debug
a remote user's problem; it matters once the app is out of the author's hands.

**Independent Test**: trigger an error, then use the "download diagnostics bundle" action and
confirm the resulting file contains logs and version/config info with no secrets present.

**Acceptance Scenarios**:

1. **Given** the app is running, **When** an error occurs, **Then** a structured log entry is
   written to a local rotating log file with any secret values scrubbed.
2. **Given** a user wants to report a problem, **When** they use the diagnostics bundle action,
   **Then** they get a downloadable file with logs, version info, and sanitized config, and no API
   keys or passwords.
3. **Given** default settings, **When** the app runs, **Then** no metrics or error reports are
   sent to any remote service unless the user has explicitly opted in.

---

### User Story 8 - Safe handling of untrusted uploads (Priority: P3)

A user uploads a malformed, oversized, or adversarial PDF, and the app rejects or safely bounds
the work instead of hanging or crashing the ingestion worker.

**Why this priority**: uploaded files are still an attack surface even on a single-user local
install; one bad file should not take down the whole app.

**Independent Test**: upload a file with a mismatched extension/content type, a file exceeding the
configured size or page limit, and a PDF crafted to trigger runaway processing; confirm each is
rejected or times out with a clear error and the worker recovers.

**Acceptance Scenarios**:

1. **Given** an uploaded file, **When** its content does not match its declared type (magic-byte
   check fails), **Then** the upload is rejected with a clear error before parsing begins.
2. **Given** an uploaded file exceeding configured size or page limits, **When** ingestion is
   attempted, **Then** it is rejected with a clear error stating the limit.
3. **Given** a document that would otherwise run indefinitely during parsing, **When** the
   configured timeout elapses, **Then** ingestion is aborted, the document is marked failed, and
   the worker remains available for the next job.
4. **Given** a document containing text crafted to instruct the model to ignore its task or
   reveal hidden instructions, **When** it is ingested and queried, **Then** the answer verifier
   and abstention behavior are unaffected by the injected instructions.

---

### Edge Cases

- What happens if the user runs the backup command while ingestion or a corpus rebuild is in
  progress? The backup must reflect a consistent state or clearly warn that it does not.
- What happens if the automatic corpus rebuild (User Story 3) itself fails partway (for example,
  the provider is unreachable)? The UI must show a stalled/failed rebuild state with a retry
  action, not a silently stuck progress bar.
- What happens if a user restores a backup taken on an older app version? The restore path must
  either upgrade the restored data automatically (reusing the User Story 3 rebuild flow) or state
  plainly that it cannot.
- What happens if two upgrade-triggered corpus rebuilds are pending at once (for example, the user
  restarts the app repeatedly during a rebuild)? Only one rebuild job must run at a time.
- What happens if the configured model-provider API key is missing, expired, or invalid? Ingestion
  and querying must fail with a clear, specific UI message rather than a generic error.
- What happens when disk space runs out during backup, restore, or ingestion? The operation must
  fail cleanly with a clear message rather than leaving a corrupted partial state.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The app MUST be installable and runnable from versioned, published container images
  via Docker Compose, with no source bind-mounts and no requirement to run `npm install`,
  `npm run dev`, or an editable Python install. End users are expected to have Docker Desktop (or
  equivalent) installed; no bundled desktop wrapper is in scope for this feature.
- **FR-002**: The system MUST bind every network-facing port to localhost only and MUST NOT
  publish the database port to any interface.
- **FR-003**: The system MUST detect and recover in-progress ingestion and evaluation jobs left
  incomplete by a stop, crash, or restart, without requiring the user to manually resubmit them.
- **FR-004**: The system MUST surface a terminal failed state (with a retry action) for any job
  that cannot complete after recovery, rather than leaving it indefinitely "processing."
- **FR-005**: The system MUST apply pending database migrations automatically on startup and MUST
  take a database backup before applying them.
- **FR-006**: When a version change makes the current corpus invalid (`corpus_reset_required`),
  the system MUST automatically rebuild the corpus from preserved uploaded documents in the
  background, without deleting decisions or conversations, and MUST show rebuild progress in the
  UI.
- **FR-007**: The system MUST keep decisions and conversation history available for reading
  throughout a corpus rebuild.
- **FR-008**: The system MUST provide a backup command that captures a database dump and an
  archive of uploaded documents, and a restore command that reverses it, both documented for an
  end user to run.
- **FR-009**: The system MUST warn users, prominently and in the documentation, against running
  any command that deletes the app's data volumes without taking a backup first.
- **FR-010**: On first run, the system MUST generate a unique JWT signing secret and database
  password for that installation rather than using shared or example defaults, and MUST refuse to
  start if a required secret is missing or left as a known placeholder.
- **FR-011**: The system MUST provide a way for the user to enter and update their model-provider
  API key exactly once per provider, store it locally, and MUST NOT log it or include it in any
  diagnostics output.
- **FR-012**: The system MUST validate required configuration at startup and fail with a specific,
  actionable error message when configuration is missing or invalid.
- **FR-013**: The system MUST require a locally-set password before granting access to a fresh
  installation, via a first-run "create password" step, and MUST provide a password reset path
  that does not depend on a remote service.
- **FR-014**: Before a user first uploads a document, the system MUST disclose which provider is
  active and whether document text is sent to a remote service, and MUST require the user to
  acknowledge this disclosure.
- **FR-015**: The system MUST support a fully local ("offline") model-provider mode with no
  outbound calls for document content, and MUST document its setup and minimum hardware
  expectations.
- **FR-016**: When the user changes the active model provider after documents have already been
  ingested, the system MUST inform them this triggers a corpus rebuild (FR-006) and require
  confirmation before proceeding.
- **FR-017**: The system MUST write structured application logs to a local rotating file, with any
  secret values scrubbed before they are written.
- **FR-018**: The system MUST provide a user-triggered action that produces a downloadable
  diagnostics bundle containing logs, version information, and sanitized configuration, with no
  secret values included.
- **FR-019**: The system MUST NOT transmit metrics, error reports, or diagnostics to any remote
  service unless the user has explicitly opted in.
- **FR-020**: The system MUST validate that uploaded file content matches its declared type before
  parsing, and MUST reject files that fail this check.
- **FR-021**: The system MUST enforce configurable maximum file size and page count on uploads and
  reject files exceeding them with a clear error naming the limit.
- **FR-022**: The system MUST enforce a timeout on document parsing such that one file cannot
  block ingestion indefinitely, and MUST leave the ingestion worker able to process the next job
  after a timeout.
- **FR-023**: The system MUST maintain its existing answer-verification and abstention behavior
  when processing documents containing adversarial or instruction-like text, and this MUST be
  covered by adversarial test fixtures.
- **FR-024**: The system MUST display its current version in the UI.
- **FR-025**: Releases MUST use semantic versioning and MUST be accompanied by a changelog entry
  that states whether the release triggers a corpus rebuild on upgrade.
- **FR-026**: The system MUST present a clear, specific UI state (not a generic error) for each of:
  missing/invalid provider API key, provider unreachable, document parse failure with a retry
  action, and an in-progress corpus rebuild.
- **FR-027**: User-facing documentation MUST cover install, upgrade, backup and restore, switching
  providers, uninstall, and troubleshooting.
- **FR-028**: Continuous integration MUST run lint, type-check, API tests, web tests, a migration
  check against a fresh database, and image builds, and MUST run a secret scan on release tags.

### Key Entities

- **Ingestion Job**: a unit of document-processing work (ingest or evaluation) with a durable
  status (`queued`, `processing`, `succeeded`, `failed`) that survives an app restart and is
  recoverable by a startup sweep.
- **Corpus Rebuild**: a background process, triggered by a detected `corpus_reset_required`
  state, that re-ingests preserved uploaded documents into a fresh corpus while leaving decisions
  and conversations untouched; has a visible progress state and can fail/retry.
- **Backup Archive**: a timestamped bundle containing a database dump and an uploads archive,
  produced by the backup command and consumable by the restore command.
- **Installation Secrets**: locally generated, non-shared values (JWT signing secret, database
  password) created on first run and never checked into source or logs.
- **Diagnostics Bundle**: a generated, downloadable file containing logs, version, and sanitized
  configuration, explicitly excluding secret values.
- **Provider Disclosure Acknowledgment**: a recorded first-run confirmation that the user
  understands which model provider is active and whether document text leaves the machine.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user on a clean machine can go from "nothing installed" to a usable UI in under 15
  minutes using only the documented install and start commands, with no manual source setup.
- **SC-002**: 100% of an app's published network ports are reachable only from the local machine
  in a default installation.
- **SC-003**: A document whose ingestion is interrupted by an app restart reaches a terminal state
  (succeeded or clearly failed) automatically in 100% of tested interruption scenarios, with no
  manual resubmission required.
- **SC-004**: After a version upgrade that changes the corpus profile, 100% of pre-existing
  decisions and conversations remain readable throughout the automatic rebuild, and the rebuild
  completes without user intervention beyond starting the upgraded version.
- **SC-005**: A user can restore a full working state (decisions, conversations, documents) from a
  backup archive in under 10 minutes using only the documented restore command.
- **SC-006**: 0 installations ship with the repository's example/default JWT secret or database
  password after first-run setup completes.
- **SC-007**: 100% of first-time users see the data-handling disclosure before their first
  document upload.
- **SC-008**: A generated diagnostics bundle contains 0 occurrences of any configured secret value,
  verified by automated scan before the bundle is offered for download.
- **SC-009**: Malformed, oversized, or slow-to-parse uploads are rejected or bounded in 100% of
  tested cases without requiring an app restart to recover ingestion capability.
- **SC-010**: Adversarial-fixture ingestion produces the same verifier/abstention outcome as the
  equivalent clean-text fixture in 100% of the adversarial test set.

## Assumptions

- Distribution target is Docker Compose with published, version-pinned images; end users install
  Docker Desktop (or equivalent) as a prerequisite. A bundled desktop wrapper is out of scope.
- Single-user auth is kept: first-run "create password" replaces env-based credentials, plus a
  local password reset path.
- "Single-tenant" means one workspace, one local user account, accessed only from the machine it
  runs on; multi-machine or multi-user access is explicitly out of scope for this feature.
- The default model provider remains a cloud API (Gemini); a fully local provider (Ollama) is
  offered as an alternative mode, not a replacement default.
- The database backup taken before automatic migrations (FR-005) is a local file the app manages
  itself, distinct from the user-triggered Backup Archive (FR-008), though both may share
  underlying tooling.
- "Uninstall" documentation describes stopping and removing the app's containers/services; it does
  not need to guarantee removal of user-created backup files stored outside the app's volumes.
- Rate limiting, TLS/security headers, RBAC, SSO, multi-user sharing, object storage, horizontal
  scaling, blue/green deploys, remote SLO dashboards, GDPR tooling, and the CI benchmark gate are
  out of scope, per explicit product direction for a single-tenant local deployment.
