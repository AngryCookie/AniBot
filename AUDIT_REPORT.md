# AniBot Production Audit (2026-03-07)

## Scope and method
- Reviewed bot, web API, betting/PvP/economy services, DB layer/migrations, scheduler, and tests.
- Ran full automated test suite (`pytest -q`) and repository-wide static scans (`rg`, targeted source inspections).

---

## Detailed issues

### 1) SQLite-specific migrations are not portable to PostgreSQL
- **Severity:** critical
- **Location:** `bot/database/migrations.py` (`_table_exists`, multiple migrations), approx. lines 16-21, 33, 113, 126, 189-200.
- **Problem:** Migration SQL is SQLite-specific (`sqlite_master`, `AUTOINCREMENT`, `PRAGMA`, `INSERT OR IGNORE`).
- **Why it matters:** The project advertises PostgreSQL support; production startup/migration can fail or behave inconsistently on Postgres.
- **Suggested fix:** Replace raw engine-specific SQL with Alembic migrations (dialect-aware), or branch SQL per dialect everywhere migrations touch metadata.

### 2) Migration runner is race-prone under concurrent startup
- **Severity:** high
- **Location:** `bot/database/db.py::Database.apply_migrations`, approx. lines 29-46.
- **Problem:** Reads max version and executes unapplied migrations without advisory locking/transaction-level serialization across app instances.
- **Why it matters:** Bot and web can start together and both run migrations, causing duplicate DDL attempts and partial startup failures.
- **Suggested fix:** Use a DB-level lock (e.g., PostgreSQL advisory lock) around migration execution; add PK/unique key to schema_versions and insert idempotently.

### 3) `get_or_create_user_locked` has upsert race windows
- **Severity:** high
- **Location:** `bot/services/economy.py::get_or_create_user_locked` lines ~20-37 and duplicate helper in `bot/database/operations.py` lines ~11-27.
- **Problem:** Select-then-insert path can collide under concurrent requests for a new user, raising integrity errors.
- **Why it matters:** Under load, balance operations may fail intermittently for first-time users.
- **Suggested fix:** Use DB-native upsert (`INSERT .. ON CONFLICT DO NOTHING RETURNING`) plus re-select; centralize in one shared helper.

### 4) External HTTP requests to Discord have no explicit timeouts
- **Severity:** high
- **Location:** `web/security.py::fetch_user`, `fetch_user_guilds` lines ~120-138; `web/main.py::auth_callback` lines ~350-354.
- **Problem:** `httpx.AsyncClient()` calls rely on defaults and do not define strict connect/read timeouts.
- **Why it matters:** Slow upstream/network stalls can tie up worker capacity and degrade API availability.
- **Suggested fix:** Configure global timeout/retries/circuit-breaker (e.g., `httpx.Timeout(5.0, connect=2.0)` + bounded retry policy).

### 5) Host allowlist only logs violations, does not block requests
- **Severity:** medium
- **Location:** `web/main.py::canonical_host_middleware`, lines ~237-241.
- **Problem:** Requests with unapproved Host header are accepted after warning.
- **Why it matters:** Weak host-header hardening can enable cache poisoning/proxy routing surprises in real deployments.
- **Suggested fix:** Return `400/421` for non-allowed hosts in non-test environments.

### 6) Insecure session-cookie default (`https_only=False`)
- **Severity:** high
- **Location:** `web/config.py`, line ~86; used by SessionMiddleware in `web/main.py` lines ~181-188.
- **Problem:** If env is misconfigured, session cookies can be sent over plain HTTP.
- **Why it matters:** Session theft risk in real networks/reverse-proxy misconfiguration scenarios.
- **Suggested fix:** Default `SESSION_HTTPS_ONLY=true`; fail startup in production if false.

### 7) Every guild-scoped API call triggers external guild fetch (no caching)
- **Severity:** medium
- **Location:** `web/main.py` repeated pattern in `_settings_dependency` and route handlers, e.g. lines ~811-812 and ~1229-1230.
- **Problem:** Permission checks fetch full guild list from Discord per request.
- **Why it matters:** High latency, Discord API rate-limit pressure, cascading failures when Discord is degraded.
- **Suggested fix:** Cache guild permissions in encrypted session with TTL (short), refresh asynchronously, and invalidate on auth refresh.

### 8) Unhandled exceptions return generic 500 without server-side logging
- **Severity:** medium
- **Location:** `web/main.py::unhandled_error_handler`, lines ~291-300.
- **Problem:** Exception object is ignored; handler does not log traceback.
- **Why it matters:** Incident triage becomes difficult; hidden production faults linger longer.
- **Suggested fix:** Add structured logging with traceback and request correlation ID before returning sanitized 500 payload.

### 9) In-memory readonly API rate limiting is process-local and non-distributed
- **Severity:** medium
- **Location:** `web/main.py::_require_readonly_access`, lines ~825-835.
- **Problem:** Rate limit state is in a module-level dict keyed by client IP.
- **Why it matters:** Ineffective across multiple app instances/pods; easy to bypass and uneven throttling behind load balancers.
- **Suggested fix:** Move limit counters to Redis or DB-backed token bucket and trust forwarded client identity safely.

### 10) Broad exception swallowing hides operational failures
- **Severity:** low
- **Location:** `bot/services/pvp.py::_emit_analytics_event` lines ~536-544; `bot/betting/service.py` announcement helpers lines ~407-410, ~435-439, ~457-461.
- **Problem:** Catches `Exception` and silently returns.
- **Why it matters:** Analytics and announcement failures become invisible; silent data/notification loss.
- **Suggested fix:** Log at warning/error with context; optionally emit retryable tasks.

### 11) Monolithic web module harms maintainability and testability
- **Severity:** medium
- **Location:** `web/main.py` (single file with routing/business logic/settings/persistence orchestration).
- **Problem:** High coupling and very large module surface.
- **Why it matters:** Increases regression risk and slows feature delivery.
- **Suggested fix:** Split by domain routers (`web/routes/*`), services, repositories, auth middleware/dependencies.

### 12) Duplicate settings merge logic across layers increases drift risk
- **Severity:** medium
- **Location:** `bot/betting/service.py` settings merge helpers and repeated in `web/betting.py` endpoints.
- **Problem:** Same config composition logic exists in multiple places.
- **Why it matters:** Behavior divergence appears when one path changes and another does not.
- **Suggested fix:** Introduce a shared `BettingSettingsService` used by both bot and web.

---

## Overall architecture evaluation
- **Strengths:** clear domain areas (economy, betting, PvP, referral), good async stack usage, broad test coverage (52 passing tests), and explicit DB models.
- **Weaknesses:** migration strategy not production-grade for multi-DB support, web layer too centralized, repeated permission/network checks in request path, and mixed concerns (routing + business + persistence) in single modules.

## Top 10 most dangerous problems
1. SQLite-only migration SQL while claiming PostgreSQL support.
2. Race-prone migration execution across concurrent starters.
3. Upsert races in user creation during balance operations.
4. Missing strict HTTP timeouts for Discord calls.
5. Insecure default for secure session cookies.
6. External permission fetch on nearly every request (rate-limit/latency risk).
7. Missing exception traceback logging in global handler.
8. Host allowlist not enforced.
9. Process-local readonly limiter (non-scalable security control).
10. Silent exception swallowing in analytics/announce paths.

## Refactoring recommendations
- Introduce **layered architecture**:
  - `web/routes` (FastAPI routers)
  - `web/services` (business rules)
  - `web/repositories` (DB access)
  - `web/auth` (session/token/cache/policies)
- Replace custom migration runner with **Alembic** and dialect-specific migration policies.
- Extract shared settings composition into a single service object reused by bot/web.
- Add typed domain DTOs for cross-module contracts (betting/pvp/report payloads).

## Maintainability improvements
- Enforce module size limits (e.g., <=500 LOC for route modules).
- Replace duplicated helpers (`get_or_create_user_locked`) with one canonical implementation.
- Add architectural tests/checks (import boundaries) to prevent layer leakage.
- Add richer structured logging and error taxonomy.

## Performance improvements
- Cache Discord guild permissions per session with short TTL.
- Add HTTP client pooling and explicit timeouts/retries.
- Audit indexes for top analytics/report queries; validate with explain plans on PostgreSQL.
- Consider background task queue for heavy report generation and automation side effects.

## Reliability improvements
- Add distributed locks for singleton jobs/migrations.
- Add idempotency keys for critical write endpoints where retries are likely.
- Add healthchecks for Discord dependency and graceful degradation modes.
- Add SLO-oriented observability: error-rate, latency, queue lag, scheduler lag.

## Production readiness verdict
- **Is the project production-ready?** **Not yet.**
- **Weakest parts:** database migration strategy, web authorization/performance path (Discord calls per request), and operational resiliency (timeouts, logging, distributed controls).

## Proposed target project structure
```
AniBot/
  bot/
    domain/
      economy/
      betting/
      pvp/
      referral/
    services/
    adapters/
      discord/
      db/
      analytics/
  web/
    routes/
      auth.py
      settings.py
      betting.py
      analytics.py
      goals.py
    services/
    repositories/
    middleware/
    schemas/
  migrations/        # Alembic
  tests/
    unit/
    integration/
    contract/
```
