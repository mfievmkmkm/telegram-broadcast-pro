from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO

import qrcode
from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from ..config import settings
from ..multi_db import ConnectedAccount, multi_repo
from .session_crypto import encrypt_session


@dataclass
class LoginContext:
    owner_user_id: int
    mode: str
    client: TelegramClient
    phone: str | None = None
    phone_code_hash: str | None = None
    qr: object | None = None
    wait_task: asyncio.Task | None = None


class AccountAuthManager:
    def __init__(self):
        self.contexts: dict[int, LoginContext] = {}

    def _new_client(self) -> TelegramClient:
        if not settings.api_id or not settings.api_hash:
            raise RuntimeError("API_ID/API_HASH не настроены на сервере")
        return TelegramClient(
            StringSession(), settings.api_id, settings.api_hash,
            connection_retries=4, request_retries=2,
        )

    async def _expire_context(self, owner_user_id: int, ctx: LoginContext, seconds: int = 300):
        await asyncio.sleep(seconds)
        if self.contexts.get(owner_user_id) is not ctx:
            return
        self.contexts.pop(owner_user_id, None)
        if ctx.wait_task and not ctx.wait_task.done():
            ctx.wait_task.cancel()
        try:
            await ctx.client.disconnect()
        except Exception:
            pass

    async def cancel(self, owner_user_id: int):
        ctx = self.contexts.pop(owner_user_id, None)
        if not ctx:
            return
        if ctx.wait_task and not ctx.wait_task.done():
            ctx.wait_task.cancel()
        try:
            await ctx.client.disconnect()
        except Exception:
            pass

    async def start_phone(self, owner_user_id: int, phone: str):
        await self.cancel(owner_user_id)
        client = self._new_client()
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
        except Exception:
            await client.disconnect()
            raise
        ctx = LoginContext(
            owner_user_id=owner_user_id,
            mode="phone",
            client=client,
            phone=phone,
            phone_code_hash=sent.phone_code_hash,
        )
        self.contexts[owner_user_id] = ctx
        asyncio.create_task(self._expire_context(owner_user_id, ctx))

    async def verify_code(self, owner_user_id: int, code: str) -> tuple[str, ConnectedAccount | None]:
        ctx = self.contexts.get(owner_user_id)
        if not ctx or ctx.mode != "phone" or not ctx.phone:
            return "expired", None
        try:
            await ctx.client.sign_in(phone=ctx.phone, code=code, phone_code_hash=ctx.phone_code_hash)
        except errors.SessionPasswordNeededError:
            return "password", None
        except errors.PhoneCodeInvalidError:
            return "invalid", None
        except errors.PhoneCodeExpiredError:
            return "expired", None
        return "ok", await self._finish(owner_user_id)

    async def start_qr(self, owner_user_id: int) -> bytes:
        await self.cancel(owner_user_id)
        client = self._new_client()
        await client.connect()
        qr = await client.qr_login()
        ctx = LoginContext(owner_user_id=owner_user_id, mode="qr", client=client, qr=qr)
        ctx.wait_task = asyncio.create_task(qr.wait())
        self.contexts[owner_user_id] = ctx
        asyncio.create_task(self._expire_context(owner_user_id, ctx))
        return self._qr_png(qr.url)

    async def refresh_qr(self, owner_user_id: int) -> bytes:
        ctx = self.contexts.get(owner_user_id)
        if not ctx or ctx.mode != "qr" or not ctx.qr:
            return await self.start_qr(owner_user_id)
        if ctx.wait_task and not ctx.wait_task.done():
            ctx.wait_task.cancel()
        await ctx.qr.recreate()
        ctx.wait_task = asyncio.create_task(ctx.qr.wait())
        return self._qr_png(ctx.qr.url)

    async def check_qr(self, owner_user_id: int) -> tuple[str, ConnectedAccount | None]:
        ctx = self.contexts.get(owner_user_id)
        if not ctx or ctx.mode != "qr" or not ctx.wait_task:
            return "expired", None
        if not ctx.wait_task.done():
            return "pending", None
        try:
            ctx.wait_task.result()
        except errors.SessionPasswordNeededError:
            return "password", None
        except asyncio.TimeoutError:
            return "expired", None
        except Exception:
            return "failed", None
        return "ok", await self._finish(owner_user_id)

    async def verify_password(self, owner_user_id: int, password: str) -> tuple[str, ConnectedAccount | None]:
        ctx = self.contexts.get(owner_user_id)
        if not ctx:
            return "expired", None
        try:
            await ctx.client.sign_in(password=password)
        except errors.PasswordHashInvalidError:
            return "invalid", None
        return "ok", await self._finish(owner_user_id)

    async def _finish(self, owner_user_id: int) -> ConnectedAccount:
        ctx = self.contexts.get(owner_user_id)
        if not ctx:
            raise RuntimeError("Сессия входа истекла")
        me = await ctx.client.get_me()
        raw_session = ctx.client.session.save()
        account = await multi_repo.upsert_account(
            owner_user_id=owner_user_id,
            tg_user_id=me.id,
            username=getattr(me, "username", None),
            first_name=getattr(me, "first_name", None),
            phone_masked=self.mask_phone(getattr(me, "phone", None) or ctx.phone),
            session_enc=encrypt_session(raw_session),
        )
        self.contexts.pop(owner_user_id, None)
        await ctx.client.disconnect()
        return account

    @staticmethod
    def mask_phone(phone: str | None) -> str | None:
        if not phone:
            return None
        p = "".join(ch for ch in str(phone) if ch.isdigit())
        if len(p) <= 4:
            return "••••"
        return "+" + p[:1] + "•" * max(4, len(p) - 5) + p[-4:]

    @staticmethod
    def _qr_png(url: str) -> bytes:
        image = qrcode.make(url)
        buf = BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()


auth_manager = AccountAuthManager()
