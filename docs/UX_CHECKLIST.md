# UX Checklist — Discord Style Preset B

## Команды и паттерны
- `/help` (user/admin split сохранен):
  - заголовок `🎮 ...`, единый footer, короткие секции с эмодзи.
  - кнопки разделов работают 60с.
- economy: `/balance`, `/daily`, `/transfer`:
  - embed через `EmbedFactory`.
  - подтверждения через `ConfirmView`.
  - ошибки через `reply_error`.
- shop: `/shop list`, `/shop info`, `/shop buy`:
  - страницы через `PaginationView`.
  - покупка с подтверждением через `ConfirmView`.
  - все ошибки в формате `❌` + `💡` при необходимости.
- betting: `/bets`, `/bet`:
  - список матчей и подтверждение ставки в едином стиле.
  - ошибки только через `reply_error`.
- pvp: `/pvp`, `/pvp-stats`, `/pvp-top`:
  - вызов и подтверждение дуэли в едином стиле.
  - ошибки RU и actionable.

## Timeout / disable
- На таймауте (60с) кнопки в `ConfirmView`, `PaginationView`, `HelpView`, `ShopBuyView`, `BetTeamView`, `PvpChallengeView` блокируются.
- Проверить визуально, что `view` обновляется и кнопки становятся disabled.

## Ошибки
- Формат: `❌ <message>`.
- При наличии подсказки: новая строка `💡 <hint>`.
- Проверить кейсы:
  - команда вне сервера,
  - недостаточно средств,
  - не найден товар/матч,
  - доступ к чужому интерактивному окну.
