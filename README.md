# AniBot (Discord bot)

Полностью модульный Discord-бот на `discord.py` с экономикой, модерацией, левелингом, магазином и гемблингом.
Проект использует только Python-реализацию; старая Node.js версия удалена.

## Очистка устаревшей Node.js версии
- Удалены `bot.js`, `package.json` и `Procfile`.
- Удалена директория `node_modules`.

## Возможности
- Модерация: предупреждения, муты, кики, баны, очистка сообщений, логирование
- Левелинг и награды
- Экономика с курсом валюты
- Магазин (роли/доступы/действия)
- Гемблинг (coinflip/dice/roulette)
- Онбординг: welcome/goodbye, autorole, реакционные роли, verify
- Кастомные команды и теги

## Структура проекта
```
/bot
  /cogs
    moderation.py
    leveling.py
    economy.py
    shop.py
    gambling.py
    roles.py
    admin.py
    utils.py
  /database
    models.py
    db.py
  config.py
  main.py
requirements.txt
README.md
```

## Установка
1. Установите Python 3.10+
2. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
3. Укажите токен Discord:
   ```bash
   export DISCORD_TOKEN="your_token_here"
   ```

## Запуск
```bash
python -m bot.main
```

## Примечания
- SQLite база создается автоматически (`bot.db`).
- Для работы команд нужны соответствующие права на сервере.

## Web Admin Dashboard (Version 2)

### Запуск web backend
1. Установите зависимости (добавлены FastAPI + HTTP-клиент):
   ```bash
   pip install -r requirements.txt
   ```
2. Укажите переменные окружения для OAuth и сессий:
   ```bash
   export DISCORD_CLIENT_ID="your_client_id"
   export DISCORD_CLIENT_SECRET="your_client_secret"
   export DISCORD_REDIRECT_URI="http://localhost:8000/auth/callback"
   export SESSION_SECRET="your_session_secret"
   export SESSION_ENCRYPTION_KEY="your_fernet_key_or_passphrase"
   export DATABASE_URL="sqlite+aiosqlite:///bot.db"
   ```
   > `SESSION_ENCRYPTION_KEY` используется для шифрования токенов в сессии.
3. Запустите сервер:
   ```bash
   uvicorn web.main:app --reload --host 0.0.0.0 --port 8000
   ```
4. Откройте в браузере: `http://localhost:8000/login.html`.

### Структура API
- `GET /api/me` — профиль пользователя Discord.
- `GET /api/guilds` — список серверов с правами admin/manage_guild.
- `GET /api/guilds/{guild_id}/overview` — статистика сервера.
- `GET/PUT /api/guilds/{guild_id}/settings` — общие настройки сервера.
- `GET/PUT /api/guilds/{guild_id}/leveling` — настройки левелинга.
- `GET/PUT /api/guilds/{guild_id}/economy` — настройки экономики.
- `GET/PUT /api/guilds/{guild_id}/gambling` — настройки гемблинга.
- `GET/PUT /api/guilds/{guild_id}/shop` — настройки магазина.
- `GET/PUT /api/guilds/{guild_id}/logs` — настройки логов.
- `POST /api/guilds/{guild_id}/{category}/reset` — сброс категории (`leveling`, `economy`, `gambling`, `shop`, `logs`).
- `GET/POST/PUT/DELETE /api/guilds/{guild_id}/shop/items` — управление товарами магазина.

### Примеры запросов
```bash
curl -H "Cookie: session=..." \
  http://localhost:8000/api/guilds/123456789/overview
```

```bash
curl -X PUT -H "Content-Type: application/json" \
  -d '{"enabled": true, "xp_per_message": 20, "xp_cooldown_seconds": 30, "announce_level_up": true}' \
  http://localhost:8000/api/guilds/123456789/leveling
```

### Примечания по безопасности
- OAuth-токены шифруются перед сохранением в сессии.
- Доступ к API проверяется по правам Discord (admin/manage_guild).
