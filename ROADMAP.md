# ROADMAP AniBot (strict phases 0–9)

Цель: довести AniBot до максимально стабильного состояния продукта (bot + web + аналитика), а выход в production/hosting выполнять только отдельной командой.

---

## Легенда статусов

- ✅ завершено
- 🟡 в работе сейчас
- ⏳ запланировано
- ⛔ отложено (deferred)

---

## Phase 0 — Foundation / Repo bootstrap ✅

- Базовая структура репозитория (bot/web/tests/docs).
- Первичный конфиг окружения и запуск в локальной среде.
- Начальные модели БД и слой доступа.

## Phase 1 — Core platform (Bot + Web + DB) ✅

- Discord bot на `discord.py` с cogs.
- FastAPI web-панель и базовая авторизация.
- Асинхронный SQLAlchemy и единый DB lifecycle.
- Базовые миграции и авто-применение миграций на старте.

## Phase 2 — Economy baseline ✅

- Балансы, списания/начисления, журнал транзакций.
- Магазин и экономические операции из bot/web.
- Экономические настройки по guild.

## Phase 3 — Betting v1 + Scheduling + Automation ✅

- Команды ставок и управление матчами.
- Планирование матчей, auto-create horizon.
- Автоматизация announce/open/close/resolve.
- Power drift и аналитика ставок.

## Phase 4 — Jobs + Buff Shop v2 + Recommendations ✅

- `/work` и Job definitions/cooldowns/history.
- Баффы v2, применение/истечение/чистка.
- Экономические рекомендации и аналитика поведения.

## Phase 5 — Monthly goals + Rituals + Wrapped reports ✅

- Goals (classic + v2), прогресс и закрытие периода.
- Ритуалы (daily/monthly) и плановые тикеры.
- Monthly/Quarterly/Yearly wrapped отчёты + dry-run.

## Phase 6 — Discord/Web UX consolidation ✅

- Unified Discord UX preset B (Gaming/Tatsu-like).
- EmbedFactory + Views и консистентные ответы.
- Web UX baseline по основным разделам.

## Phase 7 — PvP + Tavern v1 + Analytics ✅

- PvP контур и сезонная логика.
- Tavern v1 (2 слота: attack/defense).
- Метрики и аналитические представления по PvP/Tavern.

## Phase 8 — Final Stability Pass + Documentation refresh 🟡

**Текущая фаза проекта.**

- Retention/cleanup jobs (batched, safe, idempotent).
- DB index/performance audit + устранение hot-path узких мест.
- Scheduler safety hardening (locks, timing logs, idempotency).
- Единообразная обработка ошибок (bot/web), валидации, graceful fail.
- Security hygiene (env, startup checks, secret-safe logs).
- Обновление документации (`README.md`, `ROADMAP.md`, UX ссылки, smoke-checklists).

## Phase 9 — Production/Hosting rollout ⛔ DEFERRED

**Явно отложено до отдельной команды пользователя.**

- Hosting/VPS/Cloud окружение.
- CI/CD, секреты и ротация ключей.
- Monitoring/alerting/backup/disaster recovery.
- Runbooks и эксплуатационные регламенты.

> ⛔ Любые работы по production/hosting **не выполняются**, пока не поступит отдельная прямая команда.
