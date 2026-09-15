from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings


def _key() -> bytes:
    seed = settings.session_secret or f"{settings.bot_token}|{settings.api_hash}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


_cipher = Fernet(_key())


def encrypt_session(value: str) -> str:
    return _cipher.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_session(value: str) -> str:
    try:
        return _cipher.decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Не удалось расшифровать Telegram-сессию. Проверь SESSION_SECRET.") from exc
