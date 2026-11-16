# Alert registration framework implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build database-managed sources/sections/contracts, extensible detector scripts and anomaly catalog, registered notifications and configurable models; seed Tencent news/finance/tech.

**Architecture:** A registered source adapter produces transport-neutral observations and items. Independent manifest-discovered scripts return protocol-v1 issues identified by a central anomaly catalog; a database-backed runner persists checks/incidents and dispatches registered notification channels. Models remain separately configurable and are not called by collection/monitoring.

**Tech Stack:** Existing Python 3.12, Django, requests/BeautifulSoup, unittest/Django TestCase, SQLite tests; existing SMTP and optional g4f/OpenAI clients. No new runtime dependencies.

**Spec:** docs/superpowers/specs/2026-10-23-alert-framework-design.md

## Global Constraints

- Source/Section/Check/AnomalyType/CheckRun/Incident/Delivery and model/channel profiles are database managed.
- Contract violations and network/access failures are both persisted and notify configured administrators; first occurrence defaults to notifying, persistent incidents deduplicate, recovery is configurable.
- A new detector adds only its manifest/script/tests and a Check record; a new anomaly adds only its central catalog definition. No core type switch or migration per anomaly.
- Protocol v1 extension is guaranteed; extending protocol capabilities can require a framework version change.
- News title/order/count updates are normal; required schema/parse failures are contract issues.
- No automatic paid-model fallback, no model calls from monitoring, no actual mail during tests, no operational database migrations.
- New tests in cbok/test/; unrelated master changes untouched; set CBOK_CONF for this worktree.

## Review Focus

- A detector with a new anomaly code must execute and produce a database incident and notification without editing framework imports.
- A failing/blocked detector must not stop other checks; malformed JSON, timeout, unknown codes are visible execution failures.
- A manual dry run must never enqueue mail for later delivery; stale queued notifications are cancelled after recovery/config revision.
- A database lease must reject overlapping executions and stale workers must not overwrite a replacement worker's state.
- Only selected LLM backend initializes; logging and results must not expose credentials.

## Task 1: Shared registration and Tencent sources (independent adapter task)

**Files:** cbok/registry.py (shared/root); cbok/alert/sources/{__init__,base,tencent}.py; cbok/test/alert/test_sources.py and fixtures.

**Interfaces:**
- Shared `Registry(kind)`: `.register(name, value)` rejects duplicates, `.get(name)`, `.items()` stable sorted listing.
- `SourceItem(external_id, title='', url='', published_at=None, content='', metadata={})`, `.to_dict()`.
- `Observation(format, data, metadata={})`, `.to_dict()`; all fields JSON serializable.
- `SourceError(code, message, evidence=None)` preserves known central code string; source errors do not send notifications.
- `create_source(adapter: str, config: dict) -> SourceAdapter` via `register_source(name, factory)`.
- Adapter `.collect(section: dict, limit: int=12) -> list[SourceItem]`, `.read(item: dict) -> SourceItem`, `.observe(section: dict, kind: str) -> Observation`.
- Tencent section keys: `channel_key`, `channel_id`, `page_url`, `feed_kind` ('hot'/'pc'). Config optional `timeout`, `trust_env`.
- Tencent observation `data` is raw HTML text for page/article, raw JSON for feed. `metadata` holds status_code/content_type/url and parsed `channel_key`, `items` (item dictionaries) or `article` (item dictionary), as appropriate.

- [x] Write source parsing tests for page shell, finance/tech code=0 vs hot feed without code, nested sub_item, required fields, article canonical redirects and nonarticle items; verify failing tests.
- [x] Implement pure adapters with bounded HTTP timeouts/response sizes, normal TLS, no global proxy mutation, explicit access/network/contract SourceError codes; allow injectable HTTP session for fixtures.
- [x] Verify `python -m unittest cbok.test.alert.test_sources` and return precise fixture/live limitations.

## Task 2: Registered models (independent backend task)

**Files:** cbok/alert/llm.py; cbok/alert/model_backends/ if helpful; cbok/test/alert/test_llm.py.

**Interfaces:**
- `create_client(config: Mapping) -> LLMClient` accepts backend, model, provider(optional), base_url(optional), api_key_env(optional), timeout(default30), options(optional).
- `register_backend(name, factory)`, `list_backends()`; no Django/SDK initialization on import.
- Client `.ask(messages: list[dict]) -> str` preserves old call shape; structured return validation by caller.
- Builtins `g4f`, `deepseek`, `openai_compatible`; backend registry supports a fake custom backend for extensibility tests.
- Preserve explicit `G4F(...)`/`Deepseek(...)` imports and no-argument legacy Deepseek credential lookup only upon explicitly constructing Deepseek.
- Root integration selects a DB ModelProfile and passes its dict to create_client; no DB access in the backend module.

- [x] Tests fail for profile selection, custom registration, lazy SDK imports, unselected credential independence, requested model/provider/base_url/timeout, empty/invalid responses and no paid fallback.
- [x] Implement factories/adapters, credentials from named environment variables, explicit failures, JSON request support, no network retries beyond configured backend behavior.
- [x] Run isolated model tests with mocked SDK transport only; no real model calls.

## Task 3: Registered notification channels (independent channel task)

**Files:** cbok/notification/channels.py (or small package); cbok/test/alert/test_channels.py.

**Interfaces:**
- `NotificationMessage(subject: str, body: str, metadata: dict={})` immutable-or-safe message value.
- `register_channel(name, factory)`, `list_channels()`, `send_notification(kind: str, config: dict, message: NotificationMessage) -> None` raises if not confirmed delivered.
- Builtin `email` config `to: list[str]`; use existing DjangoEmailService, validated recipients, plain text body, no hardcoded recipient.
- No event lifecycle/outbox persistence here; root monitor service owns it.

- [x] Tests fail for custom registration and delivery, locmem email subject/body/recipients, invalid recipient config, unknown channel and sender failures; importing has no sends.
- [x] Implement channel dispatch and email adapter reusing existing backend; do not modify old email API unnecessarily.
- [x] Run only local tests; no SMTP calls.

## Task 4: DB catalog, detector protocol, state machine and integration (root)

**Files:** cbok/alert/models.py; monitoring/{catalog,plugins,protocol,runner,service,bootstrap}.py; monitoring/catalog/anomalies.toml; monitoring/detectors/*/{manifest.toml,check.py}; cbok/alert/gate.py; cbok/batch.py; cbok/cmd/alert.py; cbok/cmd/main.py; tracked alert migration(s); cbok/test/alert/{settings,test_registry,test_protocol,test_monitoring,test_commands,test_batch}.py.

**DB models:** Source(key,kind,adapter,config,enabled,notification_channels); Section(source,key,name,config,enabled); DetectorCheck(section,key,detector,config,interval_seconds,enabled,next_run_at,lease_token,lease_until,last_result,revision); AnomalyType(code,label,description,policy); CheckRun(check,status,result,revision,started_at,finished_at); Incident(check,anomaly_type,fingerprint,revision,status,first_seen,last_seen,occurrences); NotificationChannel(key,kind,config,enabled); NotificationDelivery(incident,channel,event_kind,status,attempts,next_attempt_at,sent_at,payload,last_error); CollectedItem(source,external_id,payload,first_seen,last_seen); ModelProfile(key,backend,model,provider,base_url,api_key_env,timeout,options,enabled). Constraint keys and leases tested using actual SQLite database.

**Script v1 protocol:** JSON input `{protocol_version:1, run_id, source:{key,adapter,config}, section:{key,config}, check:{key,config}}`. JSON output `{protocol_version:1, status:'pass'|'fail'|'unknown', issues:[{code,rule_id,message,expected?,observed?,evidence?}]}`. Pass requires no issues; nonpass requires issues. Reserved execution/config anomaly catalog keys are present. Scripts never access application DB or mail. Registered declarative default rules are interpreted by detector scripts, not core service.

**Interfaces:**
- `load_catalog(path=None) -> mapping[code, descriptor]`; no hardcoded business-code branching.
- `discover_detectors(paths=None) -> mapping[name, descriptor]`; entry script must remain in its manifest directory, names unique, version/timeout validated.
- `run_detector(descriptor, context, catalog) -> dict` enforces bounded subprocess runtime/output and JSON/issues validation.
- `run_check(check_id, apply=False, notify=False, detector_paths=None, catalog_path=None) -> CheckRun/result`; dry run never mutates formal incident/count/due state or enqueues deliveries.
- `run_due_checks(now=None, limit=100) -> list` leases independently due checks, catches item failures, does not enable monitoring during import/CLI help.
- `deliver_pending(limit=100) -> result` uses registered channels with per-delivery claim/retry and cancels stale events.
- `bootstrap_defaults(...)` syncs central catalog and seeds 1 Tencent Source/3 Sections/per-section page+feed+sample article checks, idempotently preserving administrator configuration; channels/model profiles explicitly supplied later.

- [x] Write and fail registry/protocol tests: custom script+catalog addition succeeds unchanged core; timeout/bad output/unknown code/nonzero exit, directory escape, duplicate names, invalid issue/pass consistency.
- [x] Implement Registry, anomaly catalog loading, manifest discovery, bounded subprocess runner; demonstrate red→green without a database.
- [x] Write/fail DB integration tests for persisted source/section/check enumeration, new issue type→Incident→email locmem, immediate record, threshold/ongoing dedupe/recovery, network preservation of prior contract incidents, dry-run isolation, cancelled stale deliveries, failed send retries, overlapping leases and config revision.
- [x] Add models + migration, bootstrap, state service and Tencent detector scripts using Task1 source adapter; tests use Django's isolated SQLite database and import no production credentials.
- [x] Write/fail two-task BatchProcessor regression, implement binding fix and one monitor gate (enabled only via explicit alert setting).
- [x] Add `cbok alert` enumerate/bootstrap/collect/check/run/model-check commands following BaseCommand/args/output.fail; integrate explicit DB model selection into legacy AlertManager without coupling Tencent checks to legacy initialization.
- [x] Run focused Django suite plus relevant existing configuration/command tests, `makemigrations --check --dry-run`, CLI --help and limited live Tencent checks in a disposable SQLite DB with notification disabled. No operational migrations or actual email/model calls.
- [x] Independent task reviews + integrated whole-branch review; fix material findings with reproducing tests. Save a concise user-facing completion/usage report under projectless outputs; do not push/create PR unless requested.


## Verification record

Implementation: 547bc9f; integrated review fixes: f4865bb. Final scoped review recorded in the task delivery report.

- Isolated Django Alert suite: 140 tests passed.
- Whole project under the same standalone settings: 386 tests, 2 failures (`test_zsv_check_404`, `test_zsv_upgrade_404`), both reproduced on unchanged base 4c0fa99. Unrelated ZSV files untouched.
- Real SQLite migrations 0001 → 0002 → 0003 verified in disposable databases; existing runs/items/Incident preserved, recovery authorization defaults false.
- Tencent news/finance/tech page/feed/article: 9/9 live checks passed; 2 items collected per section; no queued notifications or model calls.
- Runtime boundaries covered: full per-item lease, malformed-plugin isolation and diagnostics, in-flight acknowledgment/recovery/supersession, silent apply, finite SMTP connection timeout and continued processing.
- SMTP timeout bounds individual socket operations, not a hard total deadline. Production DB concurrency, actual SMTP delivery, external model availability and operational migration remain unverified.

No push, PR, merge, operational database migration or persistent worker was performed. Code remains on the local feature branch.
