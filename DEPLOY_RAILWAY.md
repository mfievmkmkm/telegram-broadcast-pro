# Railway — деплой по шагам

1. Создай новый GitHub-репозиторий и загрузи в него содержимое этого проекта.
2. Railway → New Project → Deploy from GitHub Repo.
3. Добавь PostgreSQL-сервис в тот же Railway Project.
4. В сервисе бота добавь переменные:

```env
BOT_TOKEN=токен BotFather
OWNER_IDS=твой Telegram user_id
DATABASE_URL=${{Postgres.DATABASE_URL}}
TIMEZONE=Asia/Yekaterinburg
SEND_DELAY_SECONDS=1.1
WORKER_POLL_SECONDS=5
MAX_RECIPIENTS_PER_CAMPAIGN=500
MAX_RETRIES=2
LOG_LEVEL=INFO
```

Если PostgreSQL в Railway называется не `Postgres`, выбери его `DATABASE_URL` через интерфейс Railway Reference Variable вместо ручного ввода.

5. Railway автоматически увидит `Dockerfile` и запустит `python run.py`.
6. В логах должна появиться строка запуска polling без traceback.
7. Открой бота в Telegram и отправь `/start`.
8. Если не знаешь свой Telegram ID — отправь `/id`.

## Если без PostgreSQL

Можно оставить:

```env
DATABASE_URL=sqlite+aiosqlite:///data/bot.db
```

Но на Railway без persistent volume SQLite-файл может потеряться при пересоздании контейнера. Для продакшена лучше PostgreSQL.
