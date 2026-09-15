from __future__ import annotations

import logging
from dataclasses import dataclass

from telethon import TelegramClient, utils
from telethon.sessions import StringSession
from telethon.tl.types import User

from ..config import settings

log = logging.getLogger("userbot")


@dataclass
class ResolvedTarget:
    chat_id: int
    title: str
    chat_type: str
    username: str | None


class UserSender:
    def __init__(self):
        self.client: TelegramClient | None = None
        self.me = None

    @property
    def ready(self) -> bool:
        return bool(self.client and self.me)

    async def start(self):
        if not settings.api_id or not settings.api_hash or not settings.user_session:
            raise RuntimeError("API_ID, API_HASH and USER_SESSION are required for user-account sending")
        self.client = TelegramClient(
            StringSession(settings.user_session),
            settings.api_id,
            settings.api_hash,
            connection_retries=5,
            request_retries=3,
        )
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError("USER_SESSION is not authorized. Generate a new session locally.")
        self.me = await self.client.get_me()
        # Prime the entity cache so numeric -100... IDs from existing dialogs resolve reliably.
        await self.client.get_dialogs(limit=200)
        log.info("User sender authorized as id=%s username=%s", self.me.id, getattr(self.me, "username", None))

    async def stop(self):
        if self.client:
            await self.client.disconnect()

    def _need_client(self) -> TelegramClient:
        if not self.client or not self.me:
            raise RuntimeError("User sender is not connected")
        return self.client

    async def resolve_target(self, ref: int | str) -> ResolvedTarget:
        client = self._need_client()
        entity = await client.get_entity(ref)
        if isinstance(entity, User):
            raise ValueError("Личные пользователи не поддерживаются: добавляй только группы/супергруппы/каналы")
        peer_id = utils.get_peer_id(entity)
        title = utils.get_display_name(entity) or str(peer_id)
        username = getattr(entity, "username", None)
        chat_type = "channel" if getattr(entity, "broadcast", False) else "supergroup" if getattr(entity, "megagroup", False) else "group"
        return ResolvedTarget(peer_id, title, chat_type, username)

    async def check_target(self, ref: int | str) -> tuple[bool, str]:
        try:
            target = await self.resolve_target(ref)
            return True, f"доступен от аккаунта · {target.chat_type}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    async def latest_saved_bundle(self, limit: int = 30) -> tuple[list[int], str]:
        client = self._need_client()
        messages = await client.get_messages("me", limit=limit)
        first = next((m for m in messages if m and (m.message or m.media)), None)
        if not first:
            raise RuntimeError("В Избранном нет подходящих сообщений")
        if first.grouped_id:
            bundle = [m for m in messages if m.grouped_id == first.grouped_id]
        else:
            bundle = [first]
        bundle = sorted(bundle, key=lambda m: m.id)
        ids = [m.id for m in bundle]
        preview = next((m.raw_text for m in bundle if m.raw_text), "[медиа]")
        return ids, preview[:500]

    async def resend_saved_bundle(self, target_ref: int | str, message_ids: list[int], extra_link: tuple[str, str] | None = None):
        client = self._need_client()
        entity = "me" if target_ref == "me" else await client.get_entity(target_ref)
        messages = await client.get_messages("me", ids=message_ids)
        if not isinstance(messages, list):
            messages = [messages]
        messages = [m for m in messages if m]
        messages.sort(key=lambda m: m.id)
        if not messages:
            raise RuntimeError("Исходные сообщения в Избранном не найдены")

        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.grouped_id:
                group = [m for m in messages[i:] if m.grouped_id == msg.grouped_id]
                files = [m.media for m in group if m.media]
                captions = [m.raw_text or "" for m in group if m.media]
                if files:
                    await client.send_file(entity, files, caption=captions)
                else:
                    for m in group:
                        await client.send_message(entity, m)
                i += len(group)
            else:
                await client.send_message(entity, msg)
                i += 1

        if extra_link:
            text, url = extra_link
            await client.send_message(entity, f"{text}: {url}")

    async def sender_label(self) -> str:
        if not self.me:
            return "не подключён"
        username = getattr(self.me, "username", None)
        return f"@{username}" if username else str(self.me.id)


user_sender = UserSender()
