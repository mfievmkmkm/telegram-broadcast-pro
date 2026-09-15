# Railway · Broadcast Pro Multi Account

## Обязательные Variables

```env
BOT_TOKEN=...
API_ID=...
API_HASH=...
DATABASE_URL=${{Postgres.DATABASE_URL}}
SESSION_SECRET=...
TIMEZONE=Asia/Yekaterinburg
SEND_DELAY_SECONDS=2.0
WORKER_POLL_SECONDS=5
MAX_ACCOUNTS_PER_USER=5
MAX_TARGETS_PER_CAMPAIGN=100
MIN_REPEAT_MINUTES=15
LOG_LEVEL=INFO
```

`USER_SESSION` больше не нужен: каждый пользователь подключает свой Telegram-аккаунт прямо внутри бота.

`OWNER_IDS` можно оставить, но публичный интерфейс не требует списка админов.

## Что нужно сделать после обновления кода

1. В Railway → сервис `telegram-broadcast-pro` → `Variables`.
2. Удалить `USER_SESSION`, если он остался от прошлой версии.
3. Оставить `BOT_TOKEN`, `API_ID`, `API_HASH`, `DATABASE_URL`.
4. Добавить `SESSION_SECRET` — длинную случайную строку, которую потом не менять.
5. Добавить или обновить остальные переменные из примера выше.
6. Нажать Redeploy.

После запуска бот больше не пытается авторизовать один глобальный userbot. Поэтому в логах не должно быть требования `USER_SESSION`.

## Как подключаются пользователи

`/start` → `👤 Аккаунты` → `➕ Подключить аккаунт`.

Доступны два способа:

- `▦ Войти по QR` — пользователь сканирует QR через Telegram → Настройки → Устройства → Подключить устройство.
- `📱 По номеру и коду` — номер вводится в боте, код набирается inline-клавиатурой, 2FA при необходимости вводится один раз и сразу удаляется.

После успешного входа Telegram-сессия шифруется и сохраняется в PostgreSQL.

## Важное

`API_ID` и `API_HASH` — общие credentials вашего Telegram-приложения с `my.telegram.org`. Их задаёт владелец сервиса один раз в Railway; обычным пользователям бота они не нужны.

Если поменять `SESSION_SECRET`, старые сохранённые сессии перестанут расшифровываться и пользователям придётся подключить аккаунты заново.
