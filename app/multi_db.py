from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (UniqueConstraint("owner_user_id", "tg_user_id", name="uq_owner_tg_account"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    session_enc: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BroadcastTarget(Base):
    __tablename__ = "broadcast_targets"
    __table_args__ = (UniqueConstraint("account_id", "peer_kind", "peer_id", name="uq_account_peer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("connected_accounts.id", ondelete="CASCADE"), index=True)
    peer_id: Mapped[int] = mapped_column(BigInteger)
    peer_kind: Mapped[str] = mapped_column(String(16))
    access_hash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserCampaign(Base):
    __tablename__ = "user_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("connected_accounts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    source_message_ids: Mapped[str] = mapped_column(Text)
    target_ids: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="scheduled")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_total: Mapped[int] = mapped_column(Integer, default=0)
    failed_total: Mapped[int] = mapped_column(Integer, default=0)


class SendLog(Base):
    __tablename__ = "send_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("user_campaigns.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("broadcast_targets.id", ondelete="CASCADE"), index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_multi_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class MultiRepo:
    async def list_accounts(self, owner_user_id: int, active_only: bool = True) -> list[ConnectedAccount]:
        async with Session() as s:
            q = select(ConnectedAccount).where(ConnectedAccount.owner_user_id == owner_user_id)
            if active_only:
                q = q.where(ConnectedAccount.active.is_(True))
            q = q.order_by(ConnectedAccount.id.desc())
            return list((await s.execute(q)).scalars())

    async def get_account(self, account_id: int, owner_user_id: int | None = None) -> ConnectedAccount | None:
        async with Session() as s:
            obj = await s.get(ConnectedAccount, account_id)
            if not obj:
                return None
            if owner_user_id is not None and obj.owner_user_id != owner_user_id:
                return None
            return obj

    async def upsert_account(self, owner_user_id: int, tg_user_id: int, username: str | None,
                             first_name: str | None, phone_masked: str | None, session_enc: str) -> ConnectedAccount:
        async with Session() as s:
            q = select(ConnectedAccount).where(
                ConnectedAccount.owner_user_id == owner_user_id,
                ConnectedAccount.tg_user_id == tg_user_id,
            )
            obj = (await s.execute(q)).scalar_one_or_none()
            if obj is None:
                obj = ConnectedAccount(
                    owner_user_id=owner_user_id,
                    tg_user_id=tg_user_id,
                    username=username,
                    first_name=first_name,
                    phone_masked=phone_masked,
                    session_enc=session_enc,
                    active=True,
                )
                s.add(obj)
            else:
                obj.username = username
                obj.first_name = first_name
                obj.phone_masked = phone_masked
                obj.session_enc = session_enc
                obj.active = True
                obj.updated_at = utcnow()
            await s.commit()
            await s.refresh(obj)
            return obj

    async def deactivate_account(self, account_id: int, owner_user_id: int):
        async with Session() as s:
            obj = await s.get(ConnectedAccount, account_id)
            if obj and obj.owner_user_id == owner_user_id:
                obj.active = False
                await s.execute(update(UserCampaign).where(
                    UserCampaign.account_id == account_id,
                    UserCampaign.status.in_(["scheduled", "active", "running"]),
                ).values(status="paused", last_result="Аккаунт отключён"))
                await s.commit()

    async def list_targets(self, owner_user_id: int, account_id: int, enabled_only: bool = False) -> list[BroadcastTarget]:
        async with Session() as s:
            q = select(BroadcastTarget).where(
                BroadcastTarget.owner_user_id == owner_user_id,
                BroadcastTarget.account_id == account_id,
            )
            if enabled_only:
                q = q.where(BroadcastTarget.enabled.is_(True))
            q = q.order_by(BroadcastTarget.title)
            return list((await s.execute(q)).scalars())

    async def get_target(self, target_id: int, owner_user_id: int | None = None) -> BroadcastTarget | None:
        async with Session() as s:
            obj = await s.get(BroadcastTarget, target_id)
            if not obj:
                return None
            if owner_user_id is not None and obj.owner_user_id != owner_user_id:
                return None
            return obj

    async def upsert_target(self, owner_user_id: int, account_id: int, peer_id: int, peer_kind: str,
                            access_hash: int | None, title: str, username: str | None) -> BroadcastTarget:
        async with Session() as s:
            q = select(BroadcastTarget).where(
                BroadcastTarget.account_id == account_id,
                BroadcastTarget.peer_kind == peer_kind,
                BroadcastTarget.peer_id == peer_id,
            )
            obj = (await s.execute(q)).scalar_one_or_none()
            if obj is None:
                obj = BroadcastTarget(
                    owner_user_id=owner_user_id,
                    account_id=account_id,
                    peer_id=peer_id,
                    peer_kind=peer_kind,
                    access_hash=access_hash,
                    title=title[:255],
                    username=username,
                    enabled=True,
                )
                s.add(obj)
            else:
                obj.access_hash = access_hash
                obj.title = title[:255]
                obj.username = username
                obj.enabled = True
            await s.commit()
            await s.refresh(obj)
            return obj

    async def toggle_target(self, target_id: int, owner_user_id: int) -> bool | None:
        async with Session() as s:
            obj = await s.get(BroadcastTarget, target_id)
            if not obj or obj.owner_user_id != owner_user_id:
                return None
            obj.enabled = not obj.enabled
            await s.commit()
            return obj.enabled

    async def create_campaign(self, owner_user_id: int, account_id: int, name: str, message_ids: list[int],
                              target_ids: list[int], next_run_at: datetime, interval_minutes: int | None) -> UserCampaign:
        async with Session() as s:
            obj = UserCampaign(
                owner_user_id=owner_user_id,
                account_id=account_id,
                name=name[:160],
                source_message_ids=",".join(str(int(x)) for x in sorted(set(message_ids))),
                target_ids=",".join(str(int(x)) for x in sorted(set(target_ids))),
                status="scheduled",
                next_run_at=next_run_at,
                interval_minutes=interval_minutes,
            )
            s.add(obj)
            await s.commit()
            await s.refresh(obj)
            return obj

    async def list_campaigns(self, owner_user_id: int, limit: int = 20) -> list[UserCampaign]:
        async with Session() as s:
            q = select(UserCampaign).where(UserCampaign.owner_user_id == owner_user_id).order_by(UserCampaign.id.desc()).limit(limit)
            return list((await s.execute(q)).scalars())

    async def get_campaign(self, campaign_id: int, owner_user_id: int | None = None) -> UserCampaign | None:
        async with Session() as s:
            obj = await s.get(UserCampaign, campaign_id)
            if not obj:
                return None
            if owner_user_id is not None and obj.owner_user_id != owner_user_id:
                return None
            return obj

    async def due_campaigns(self, now: datetime) -> list[UserCampaign]:
        async with Session() as s:
            q = select(UserCampaign).where(
                UserCampaign.status.in_(["scheduled", "active"]),
                UserCampaign.next_run_at.is_not(None),
                UserCampaign.next_run_at <= now,
            ).order_by(UserCampaign.next_run_at).limit(20)
            return list((await s.execute(q)).scalars())

    async def update_campaign(self, campaign_id: int, **values):
        async with Session() as s:
            obj = await s.get(UserCampaign, campaign_id)
            if not obj:
                return
            for key, value in values.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)
            await s.commit()

    async def add_log(self, campaign_id: int, target_id: int, ok: bool, error: str | None = None):
        async with Session() as s:
            s.add(SendLog(campaign_id=campaign_id, target_id=target_id, ok=ok, error=(error or "")[:2000] or None))
            await s.commit()

    async def stats(self, owner_user_id: int) -> tuple[int, int, int, int]:
        accounts = await self.list_accounts(owner_user_id)
        campaigns = await self.list_campaigns(owner_user_id, limit=1000)
        sent = sum(c.sent_total for c in campaigns)
        failed = sum(c.failed_total for c in campaigns)
        active = sum(1 for c in campaigns if c.status in {"scheduled", "active", "running", "paused"})
        return len(accounts), active, sent, failed


multi_repo = MultiRepo()
