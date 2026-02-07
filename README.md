# AniBot (Discord bot)

Полностью модульный Discord-бот на `discord.py` с экономикой, модерацией, левелингом, магазином и гемблингом.

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
