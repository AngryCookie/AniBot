# <div align="center">🤖 AniBot</div>

<div align="center">

**Discord-бот с web-панелью администрирования**

Инструмент для владельцев и администраторов Discord-серверов

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Discord.py](https://img.shields.io/badge/Discord.py-2.4.0-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![Status](https://img.shields.io/badge/Status-Active%20Development-57F287?style=flat-square)]()

[📋 ROADMAP 2026](./ROADMAP.md) • [🚀 Быстрый старт](#-быстрый-старт) • [📖 Документация](#-документация)

</div>

---

## 📚 Быстрое оглавление

- [Описание проекта](#-описание-проекта)
- [Возможности](#-возможности)
- [Быстрый старт](#-быстрый-старт)
- [Web-панель](#-web-панель)
- [База данных и миграции](#-база-данных-и-миграции)
- [Документация](#-документация)
- [Как протестировать ключевые сценарии](#-как-протестировать-ключевые-сценарии)
- [Troubleshooting](#-troubleshooting)

---

## 🎯 Описание проекта

**AniBot** — это Discord-бот + web-панель для управления внутриигровой экономикой, ставками, PvP, реферальной системой и аналитикой сервера.

Проект ориентирован на контролируемый игровой контур внутри Discord-сообществ: без реальных денег, с прозрачной логикой и управлением через вебку.

---

## ✨ Возможности

### 💰 Economy / Shop
- Балансы пользователей, операции и транзакции.
- Магазин ролей/предметов через web-панель.

### 🎲 Betting
- Матчи и ставки на победителя.
- Ведение статистики и интеграция с экономикой.

### ⚔️ PvP + Seasons
- PvP-дуэли с рейтингом.
- Сезоны с автозакрытием и таблицей результатов.

### 🎁 Promo / Referrals
- Реферальные коды и промо-кампании.
- Учёт атрибуции и наград.

### 📊 Reports
- Ежемесячные и ежегодные отчёты.
- Dry-run генерация отчётов через web API.

### 🧠 Word / Emoji Stats
- Сбор статистики слов, эмодзи и реакций.
- Периодический flush и retention-очистка.

### 🎯 Monthly Goals
- Цели месяца (классические и v2-механики).
- Закрытие месяца и выдача/снятие ролей.

---

## 🚀 Быстрый старт

### 1) Переменные окружения

Используйте шаблон из `.env.example`:

```bash
cp .env.example .env
```

Минимум для запуска:

```env
DISCORD_TOKEN=...
SESSION_SECRET=...
DATABASE_URL=sqlite+aiosqlite:///bot.db
```

> Полный пример см. в [`./.env.example`](./.env.example).

### 2) Локальный запуск (bot + web)

```bash
pip install -r requirements.txt
uvicorn web.main:app --reload --host 0.0.0.0 --port 8000
python -m bot.main
```

### 3) Запуск через Docker Compose

```bash
docker compose up --build
```

---

## 🌐 Web-панель

### Запуск

- Локально: `uvicorn web.main:app --reload --host 0.0.0.0 --port 8000`
- Через Docker: `docker compose up --build`

### Вход и сессии

- Используется OAuth Discord + серверная сессия.
- `SESSION_SECRET` обязателен для старта web-приложения.
- Не храните секреты в документации/репозитории.

---

## 🗄️ База данных и миграции

### Где хранится БД

- **Локально:** `bot.db` (корень проекта).
- **Docker:** `/data/bot.db` внутри volume-контейнера.

### Миграции

Проект применяет миграции автоматически при старте bot/web через `Database.apply_migrations(MIGRATIONS)`.

Практически это значит:
- запускаете `python -m bot.main` или `uvicorn web.main:app ...`
- недостающие миграции применяются автоматически.

---

## 📖 Документация

- Основной план развития: [`ROADMAP.md`](./ROADMAP.md)
- Отчёт по экономическому ledger: [`ECONOMY_LEDGER_REPORT_RU.md`](./ECONOMY_LEDGER_REPORT_RU.md)
- Отчёт по referral core: [`REFERRAL_CORE_REPORT_RU.md`](./REFERRAL_CORE_REPORT_RU.md)
- Краткий UX-референс: [`UX_STYLE_GUIDE.md`](./UX_STYLE_GUIDE.md)


## 🧪 Как протестировать ключевые сценарии

Быстрый smoke-набор для локального прогона:

1. **Bet flow**: создать матч в web → открыть ставки → сделать ставки из Discord.
2. **Resolve**: закрыть матч (ручной/авто) и проверить начисления payout в экономике.
3. **Schedule auto-create**: включить auto-apply расписания и дождаться auto-create матчей.
4. **Jobs**: вызвать `/work` и проверить cooldown + запись JobRun.
5. **Buff shop**: купить бафф, убедиться в применении модификатора и деактивации по истечению срока.
6. **Tavern**: покупка + проверка слотов attack/defense + PvP-дуэль с эффектами.
7. **Monthly goals**: создать цель, проверить накопление прогресса и закрытие месяца.
8. **Reports dry-run**: сделать dry-run monthly/quarterly/yearly wrapped в web API.

Для запуска автотестов:

```bash
pytest -q
```

---

## 🆘 Troubleshooting

1. **Web не стартует с ошибкой `SESSION_SECRET is required`**  
   Укажите `SESSION_SECRET` в `.env`.

2. **Бот не стартует (`DISCORD_TOKEN environment variable is required`)**  
   Проверьте `DISCORD_TOKEN` и перезапустите процесс.

3. **OAuth логин не работает**  
   Проверьте `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI`.

4. **Команды есть, но часть функций «молчит»**  
   Проверьте feature flags и guild-настройки в web-панели.

5. **Нет данных в word/emoji графиках**  
   Подождите flush-цикл (периодический), проверьте что сбор статистики включён в настройках.

---

## 🤝 Участие в проекте

PR и предложения по улучшению приветствуются. Перед изменениями сверяйтесь с ROADMAP и текущим набором фич.
