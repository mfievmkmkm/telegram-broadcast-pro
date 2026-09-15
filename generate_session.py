import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

print("Telegram USER_SESSION generator")
print("Код и пароль 2FA вводятся только здесь, локально. Никому их не отправляй.\n")
api_id = int(os.getenv("API_ID") or input("API_ID: ").strip())
api_hash = os.getenv("API_HASH") or input("API_HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    client.start()
    session = StringSession.save(client.session)
    me = client.get_me()
    print(f"\nАвторизован аккаунт: @{getattr(me, 'username', None) or me.id}")
    print("\nUSER_SESSION (сохрани в Railway как secret):")
    print(session)
