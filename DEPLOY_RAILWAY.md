# Railway · Broadcast Pro User Mode

## Обязательные Variables

```env
BOT_TOKEN=...
OWNER_IDS=123456789
API_ID=...
API_HASH=...
USER_SESSION=...
DATABASE_URL=${{Postgres.DATABASE_URL}}
TIMEZONE=Asia/Yekaterinburg
SEND_DELAY_SECONDS=1.1
WORKER_POLL_SECONDS=5
MAX_RECIPIENTS_PER_CAMPAIGN=500
MAX_RETRIES=2
LOG_LEVEL=INFO
```

## Что изменилось

Теперь управляющий Telegram-бот не отправляет сообщения сам. Он только управляет кампаниями. Реальная отправка идёт через подключённый пользовательский аккаунт (Telethon / MTProto).

До добавления `API_ID`, `API_HASH` и `USER_SESSION` новый deploy будет завершаться ошибкой — это ожидаемо.

## Как получить USER_SESSION

На своём ПК скачайте/клонируйте проект и выполните:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install "Telethon>=1.45,<2"
.venv\Scripts\python.exe generate_session.py
```

Введите API ID/Hash, телефон, код Telegram и 2FA только в локальном терминале. Полученную строку `USER_SESSION` добавьте в Railway как secret variable.

После добавления всех трёх MTProto-переменных сделайте Redeploy.

В нормальном логе появится строка вида:

```text
User sender authorized as id=... username=...
```

После этого запускается aiogram polling управляющего бота.
