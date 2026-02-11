# Отчет по задаче: транзакционный ledger экономики

## Что реализовано
- Добавлена новая ORM-модель `economy_transactions` для полного персистентного журнала изменений баланса.
- Добавлена миграция, создающая таблицу `economy_transactions` и индексы по `guild_id`, `user_id`, `type`, `created_at`.
- Вынесена логика экономики в сервис `EconomyService`:
  - универсальный метод `change_balance(...)` с проверкой на отрицательный баланс;
  - специализированные операции: `daily_reward`, `place_bet`, `bet_win`, `shop_purchase`, `admin_grant`, `admin_remove`, `tax`;
  - методы чтения: `get_user_transactions(...)`, `get_guild_transactions(...)`.
- Обновлены ключевые участки бизнес-логики, чтобы баланс-операции писались через сервис (daily, betting, gambling, shop, admin).
- Сохранена обратная совместимость: помимо новой таблицы, продолжает заполняться старая `economy_ledger` через сервис, поэтому существующая аналитика/API не ломаются.

## Какие файлы изменены
- `bot/database/models.py`
- `bot/database/migrations.py`
- `bot/database/operations.py`
- `bot/services/economy.py`
- `bot/services/__init__.py`
- `bot/cogs/economy.py`
- `bot/cogs/admin.py`
- `bot/cogs/shop.py`
- `bot/cogs/gambling.py`
- `bot/betting/service.py`

## Принятые допущения
- Для SQLAlchemy-совместимости поле `metadata` в Python-атрибуте названо `metadata_json`, но в БД сохраняется именно как колонка `metadata`.
- Старый `economy_ledger` сохранен и продолжает заполняться, чтобы не ломать текущие отчеты/аналитику и API, которые на него опираются.
- Для ставок в gambling учтен явный этап `bet_placement`; при выигрыше начисляется `bet_win`, налог проводится отдельной транзакцией `tax`.
