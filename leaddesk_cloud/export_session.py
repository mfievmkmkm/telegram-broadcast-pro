# Generates a cloud session ONLY on your own computer. Never upload or commit it.
import asyncio
import getpass
from telethon import TelegramClient
from telethon.sessions import StringSession

async def main():
    print("Only on YOUR PC. Login code and 2FA are never sent to the developer.")
    api_id=int(input("API ID: ").strip())
    api_hash=getpass.getpass("API HASH: ").strip()
    client=TelegramClient(StringSession(),api_id,api_hash)
    try:
        await client.start()
        me=await client.get_me()
        print("Authorized:",me.username or me.id)
        print("\nCopy the NEXT LINE as TG_STRING_SESSION in Railway Variables.")
        print("Treat it like a PASSWORD. Never share it in chat or GitHub.")
        print(client.session.save())
    finally:
        await client.disconnect()

if __name__=="__main__":
    asyncio.run(main())
