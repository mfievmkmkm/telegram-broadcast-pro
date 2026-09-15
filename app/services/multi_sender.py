from __future__ import annotations

from dataclasses import dataclass

from telethon import TelegramClient, types
from telethon.sessions import StringSession

from ..config import settings
from ..multi_db import BroadcastTarget, ConnectedAccount
from .session_crypto import decrypt_session


@dataclass
class DialogCandidate:
    peer_id: int
    peer_kind: str
    access_hash: int | None
    title: str
    username: str | None
    is_channel: bool


class MultiSender:
    async def open_client(self, account: ConnectedAccount) -> TelegramClient:
        session = decrypt_session(account.session_enc)
        client = TelegramClient(StringSession(session), settings.api_id, settings.api_hash, connection_retries=4, request_retries=2)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError("Сессия аккаунта больше не авторизована. Подключи аккаунт заново.")
        return client

    async def check_account(self, account: ConnectedAccount) -> tuple[bool, str]:
        try:
            client = await self.open_client(account)
            me = await client.get_me()
            await client.disconnect()
            label = f"@{me.username}" if getattr(me, "username", None) else str(me.id)
            return True, f"Аккаунт в сети · {label}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    async def logout_account(self, account: ConnectedAccount):
        try:
            client = await self.open_client(account)
            await client.log_out()
        except Exception:
            pass

    async def list_dialogs(self, account: ConnectedAccount, limit: int = 80) -> list[DialogCandidate]:
        client = await self.open_client(account)
        result: list[DialogCandidate] = []
        try:
            async for dialog in client.iter_dialogs(limit=limit):
                entity = dialog.entity
                if isinstance(entity, types.User):
                    continue
                if isinstance(entity, types.Channel):
                    kind = "channel"
                    access_hash = getattr(entity, "access_hash", None)
                    is_channel = bool(getattr(entity, "broadcast", False))
                elif isinstance(entity, types.Chat):
                    kind = "chat"
                    access_hash = None
                    is_channel = False
                else:
                    continue
                result.append(DialogCandidate(
                    peer_id=int(entity.id),
                    peer_kind=kind,
                    access_hash=int(access_hash) if access_hash is not None else None,
                    title=(getattr(entity, "title", None) or dialog.name or str(entity.id))[:255],
                    username=getattr(entity, "username", None),
                    is_channel=is_channel,
                ))
        finally:
            await client.disconnect()
        return result

    def input_peer(self, target: BroadcastTarget):
        if target.peer_kind == "channel":
            if target.access_hash is None:
                raise RuntimeError("У канала потерян access_hash. Добавь его заново из списка чатов.")
            return types.InputPeerChannel(channel_id=target.peer_id, access_hash=target.access_hash)
        if target.peer_kind == "chat":
            return types.InputPeerChat(chat_id=target.peer_id)
        raise RuntimeError("Неизвестный тип получателя")

    async def latest_saved_bundle(self, account: ConnectedAccount, limit: int = 40) -> tuple[list[int], str]:
        client = await self.open_client(account)
        try:
            messages = await client.get_messages("me", limit=limit)
            first = next((m for m in messages if m and (m.message or m.media)), None)
            if not first:
                raise RuntimeError("В Избранном нет подходящих сообщений")
            if first.grouped_id:
                bundle = [m for m in messages if m.grouped_id == first.grouped_id]
            else:
                bundle = [first]
            bundle = sorted(bundle, key=lambda m: m.id)
            ids = [int(m.id) for m in bundle]
            preview = next((m.raw_text for m in bundle if m.raw_text), "[медиа]")
            return ids, preview[:500]
        finally:
            await client.disconnect()

    async def send_saved_bundle(self, client: TelegramClient, target, message_ids: list[int]):
        messages = await client.get_messages("me", ids=message_ids)
        if not isinstance(messages, list):
            messages = [messages]
        messages = [m for m in messages if m]
        messages.sort(key=lambda m: m.id)
        if not messages:
            raise RuntimeError("Исходный пост в Избранном не найден")

        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.grouped_id:
                group = [m for m in messages[i:] if m.grouped_id == msg.grouped_id]
                files = [m.media for m in group if m.media]
                captions = [m.raw_text or "" for m in group if m.media]
                if files:
                    await client.send_file(target, files, caption=captions)
                else:
                    for m in group:
                        if m.raw_text:
                            await client.send_message(target, m.raw_text, formatting_entities=m.entities)
                i += len(group)
                continue

            if msg.media:
                await client.send_file(target, msg.media, caption=msg.raw_text or "")
            else:
                await client.send_message(target, msg.raw_text or "", formatting_entities=msg.entities)
            i += 1

    async def test_to_saved(self, account: ConnectedAccount, message_ids: list[int]):
        client = await self.open_client(account)
        try:
            await self.send_saved_bundle(client, "me", message_ids)
        finally:
            await client.disconnect()


multi_sender = MultiSender()
