# ROADMAP AniBot (v2)

Краткая цель: довести AniBot до стабильной, предсказуемой и масштабируемой платформы Discord-автоматизации с акцентом на экономику, вовлечение и аналитические отчёты.

---

## Current status

Сейчас в проекте уже реализованы:

- ✅ Базовая экономика, магазин и транзакции.
- ✅ Betting-механики и web-управление матчами/ставками.
- ✅ PvP-дуэли, рейтинги и сезонная логика.
- ✅ Growth/referral/promo подсистема.
- ✅ Ежемесячные и ежегодные отчёты (preview/dry-run/post).
- ✅ Word/emoji/reaction статистика + flush/retention.
- ✅ Monthly goals (классические + v2).
- ✅ Планировщик периодических задач и миграционная база.

---

## Phase 1 — Core stability (completed)

**Goal:** заложить фундамент bot/web/db.

### Deliverables
- [x] ✅ Асинхронный SQLAlchemy слой и единая схема.
- [x] ✅ Discord bot c cogs-архитектурой.
- [x] ✅ FastAPI web-панель с guild-настройками.
- [x] ✅ Базовая observability (JSON-логи).

### Dependencies
- Python runtime
- Discord API

### Definition of done
- Проект запускается локально и через Docker.
- Базовые команды и web-endpoints доступны.

---

## Phase 2 — Economy + Betting (completed)

**Goal:** дать серверу управляемую игровую экономику.

### Deliverables
- [x] ✅ Балансы, транзакции, операции начисления/списания.
- [x] ✅ Shop-модуль.
- [x] ✅ Betting-контур и интеграция с economy.

### Dependencies
- Phase 1

### Definition of done
- Можно провести полный цикл: пополнение → ставка → расчёт.

---

## Phase 3 — PvP + Seasons (completed)

**Goal:** добавить соревновательный слой с ротацией сезонов.

### Deliverables
- [x] ✅ PvP дуэли и рейтинг.
- [x] ✅ Сезоны PvP и таблица результатов.
- [x] ✅ Настройки сезона из web-панели.

### Dependencies
- Phase 2

### Definition of done
- Сезон создаётся/закрывается без ручного вмешательства.

---

## Phase 4 — Growth/Referral (completed)

**Goal:** повысить органический рост сервера.

### Deliverables
- [x] ✅ Referral codes/usage/rewards.
- [x] ✅ Promo campaigns и атрибуция.
- [x] ✅ Growth-аналитика в web.

### Dependencies
- Phase 2

### Definition of done
- Видно источник привлечения и выданные награды.

---

## Phase 5 — Reports + Engagement analytics (completed)

**Goal:** автоматизировать обзор активности сервера.

### Deliverables
- [x] ✅ Monthly report generation.
- [x] ✅ Yearly report generation.
- [x] ✅ Dry-run/preview API и posting.
- [x] ✅ Word/emoji/reaction daily stats.

### Dependencies
- Phase 1–4

### Definition of done
- Отчёт собирается за период, постится и хранится в БД.

---

## Phase 6 — Monthly Goals v2 (completed)

**Goal:** добавить долгосрочную вовлечённость сообщества.

### Deliverables
- [x] ✅ Шаблоны целей и активная цель месяца.
- [x] ✅ Расчёт прогресса/вкладов.
- [x] ✅ Закрытие цели и ротация ролей.

### Dependencies
- Phase 5

### Definition of done
- Цель автоматически закрывается и корректно выдаёт награды.

---

## Phase 7 — Final audit hardening (in progress)

**Goal:** стабилизация прод-качества перед финальным выходом.

### Deliverables
- [x] ✅ Retention cleanup для word/emoji/reaction таблиц.
- [x] ✅ Batch delete и логирование времени/объёмов очистки.
- [x] ✅ Scheduler overlap guard (lock per task).
- [x] ✅ Единый формат web API ошибок `{error_code, message, details}`.
- [x] ✅ Санитизация логов от секретов.
- [x] ✅ Проверка обязательных env vars при старте.
- [ ] Дополнительный SQL-профайлинг hot endpoints на production data.
- [ ] Финальный перф-аудит сложных web-вкладок под высокой нагрузкой.

### Dependencies
- Phase 1–6

### Definition of done
- Периодические джобы идемпотентны и безопасны к повторному запуску.
- Ошибки и в bot, и в web стандартизированы и понятны.
- Нет утечек токенов/секретов в логах.

---

## Phase 8 — Hosting / Production rollout (deferred, LAST)

**Goal:** подготовить и выполнить финальный production rollout.

> ⚠️ Эта фаза **отложена** и должна выполняться **в самом конце**, после полного завершения технического аудита.

### Deliverables
- [ ] Инфраструктура окружения (hosting/VPS/cloud).
- [ ] CI/CD и секреты окружения.
- [ ] Мониторинг, алерты, бэкапы.
- [ ] Disaster recovery runbook.

### Dependencies
- Обязательное завершение Phase 7.

### Definition of done
- Система стабильно работает в production-режиме.
- Есть регламент обновлений, откатов и мониторинга.
