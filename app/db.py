from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, delete, func, select, update
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Admin(Base):
    __tablename__ = "admins"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="admin")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatTarget(Base):
    __tablename__ = "chat_targets"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    chat_type: Mapped[str] = mapped_column(String(32), default="unknown")
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tags: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    source_chat_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(Integer)
    source_message_ids: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160))
    source_chat_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(Integer)
    source_message_ids: Mapped[str] = mapped_column(Text, default="")
    preview_text: Mapped[str] = mapped_column(Text, default="")
    target_mode: Mapped[str] = mapped_column(String(16), default="all")
    target_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    repeat_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    button_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    button_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CampaignRun(Base):
    __tablename__ = "campaign_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="running")
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("run_id", "chat_id", name="uq_run_chat"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("campaign_runs.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        for owner_id in settings.owner_ids:
            obj = await session.get(Admin, owner_id)
            if obj is None:
                session.add(Admin(user_id=owner_id, role="owner", active=True))
            else:
                obj.role = "owner"
                obj.active = True
        await session.commit()


ROLE_LEVEL = {"viewer": 10, "editor": 20, "admin": 30, "owner": 40}


class Repo:
    async def get_admin(self, user_id: int) -> Admin | None:
        async with Session() as s:
            obj = await s.get(Admin, user_id)
            return obj if obj and obj.active else None

    async def role_at_least(self, user_id: int, role: str) -> bool:
        admin = await self.get_admin(user_id)
        return bool(admin and ROLE_LEVEL.get(admin.role, 0) >= ROLE_LEVEL.get(role, 999))

    async def list_admins(self) -> list[Admin]:
        async with Session() as s:
            r = await s.execute(select(Admin).where(Admin.active.is_(True)).order_by(Admin.role.desc(), Admin.user_id))
            return list(r.scalars())

    async def upsert_admin(self, user_id: int, role: str, username: str | None = None):
        async with Session() as s:
            obj = await s.get(Admin, user_id)
            if obj is None:
                obj = Admin(user_id=user_id, role=role, username=username, active=True)
                s.add(obj)
            else:
                obj.role, obj.active = role, True
                if username:
                    obj.username = username
            await s.commit()

    async def deactivate_admin(self, user_id: int):
        async with Session() as s:
            obj = await s.get(Admin, user_id)
            if obj and obj.role != "owner":
                obj.active = False
                await s.commit()

    async def upsert_chat(self, chat_id: int, title: str, chat_type: str, username: str | None, added_by: int | None):
        async with Session() as s:
            obj = await s.get(ChatTarget, chat_id)
            if obj is None:
                s.add(ChatTarget(chat_id=chat_id, title=title[:255], chat_type=chat_type, username=username, added_by=added_by, enabled=True))
            else:
                obj.title, obj.chat_type, obj.username, obj.enabled = title[:255], chat_type, username, True
                obj.updated_at = utcnow()
            await s.commit()

    async def list_chats(self, enabled_only: bool = False) -> list[ChatTarget]:
        async with Session() as s:
            q = select(ChatTarget)
            if enabled_only:
                q = q.where(ChatTarget.enabled.is_(True))
            q = q.order_by(ChatTarget.title)
            r = await s.execute(q)
            return list(r.scalars())

    async def get_chat(self, chat_id: int) -> ChatTarget | None:
        async with Session() as s:
            return await s.get(ChatTarget, chat_id)

    async def set_chat_enabled(self, chat_id: int, enabled: bool):
        async with Session() as s:
            obj = await s.get(ChatTarget, chat_id)
            if obj:
                obj.enabled = enabled
                obj.updated_at = utcnow()
                await s.commit()

    async def set_chat_tags(self, chat_id: int, tags: Iterable[str]):
        cleaned = sorted({t.strip().lower().replace(" ", "_")[:40] for t in tags if t.strip()})
        async with Session() as s:
            obj = await s.get(ChatTarget, chat_id)
            if obj:
                obj.tags = ",".join(cleaned)
                obj.updated_at = utcnow()
                await s.commit()

    async def all_tags(self) -> list[str]:
        chats = await self.list_chats(enabled_only=True)
        tags = set()
        for c in chats:
            tags.update(x for x in c.tags.split(",") if x)
        return sorted(tags)

    async def target_chats(self, mode: str, value: str | None) -> list[ChatTarget]:
        chats = await self.list_chats(enabled_only=True)
        if mode == "tag" and value:
            return [c for c in chats if value.lower() in {x for x in c.tags.split(",") if x}]
        return chats

    async def create_template(self, name: str, source_chat_id: int, source_message_ids: list[int], created_by: int) -> Template:
        async with Session() as s:
            ids = sorted({int(x) for x in source_message_ids})
            obj = Template(
                name=name[:120], source_chat_id=source_chat_id,
                source_message_id=ids[0], source_message_ids=",".join(map(str, ids)),
                created_by=created_by
            )
            s.add(obj)
            await s.commit(); await s.refresh(obj)
            return obj

    async def list_templates(self, limit: int = 20) -> list[Template]:
        async with Session() as s:
            r = await s.execute(select(Template).order_by(Template.id.desc()).limit(limit))
            return list(r.scalars())

    async def get_template(self, template_id: int) -> Template | None:
        async with Session() as s:
            return await s.get(Template, template_id)

    async def delete_template(self, template_id: int):
        async with Session() as s:
            await s.execute(delete(Template).where(Template.id == template_id))
            await s.commit()

    async def create_campaign(self, **kwargs) -> Campaign:
        async with Session() as s:
            obj = Campaign(**kwargs)
            s.add(obj)
            await s.commit(); await s.refresh(obj)
            return obj

    async def get_campaign(self, campaign_id: int) -> Campaign | None:
        async with Session() as s:
            return await s.get(Campaign, campaign_id)

    async def list_campaigns(self, statuses: tuple[str, ...] | None = None, limit: int = 20) -> list[Campaign]:
        async with Session() as s:
            q = select(Campaign)
            if statuses:
                q = q.where(Campaign.status.in_(statuses))
            r = await s.execute(q.order_by(Campaign.id.desc()).limit(limit))
            return list(r.scalars())

    async def due_campaigns(self, now: datetime) -> list[Campaign]:
        async with Session() as s:
            q = select(Campaign).where(
                Campaign.status == "scheduled",
                Campaign.scheduled_at.is_not(None),
                Campaign.scheduled_at <= now,
            ).order_by(Campaign.scheduled_at.asc()).limit(5)
            r = await s.execute(q)
            return list(r.scalars())

    async def update_campaign(self, campaign_id: int, **values):
        values["updated_at"] = utcnow()
        async with Session() as s:
            await s.execute(update(Campaign).where(Campaign.id == campaign_id).values(**values))
            await s.commit()

    async def create_run(self, campaign_id: int, total: int) -> CampaignRun:
        async with Session() as s:
            obj = CampaignRun(campaign_id=campaign_id, total=total, status="running")
            s.add(obj)
            await s.commit(); await s.refresh(obj)
            return obj

    async def create_deliveries(self, run_id: int, chat_ids: list[int]):
        async with Session() as s:
            s.add_all([Delivery(run_id=run_id, chat_id=x) for x in chat_ids])
            await s.commit()

    async def mark_delivery(self, delivery_id: int, status: str, attempts: int, error: str | None = None):
        async with Session() as s:
            await s.execute(update(Delivery).where(Delivery.id == delivery_id).values(
                status=status, attempts=attempts, error=(error or "")[:2000] or None,
                sent_at=utcnow() if status == "sent" else None,
            ))
            await s.commit()

    async def pending_deliveries(self, run_id: int) -> list[Delivery]:
        async with Session() as s:
            r = await s.execute(select(Delivery).where(Delivery.run_id == run_id, Delivery.status == "pending").order_by(Delivery.id))
            return list(r.scalars())

    async def resumable_run(self, campaign_id: int) -> CampaignRun | None:
        async with Session() as s:
            r = await s.execute(
                select(CampaignRun)
                .where(CampaignRun.campaign_id == campaign_id, CampaignRun.status.in_(("paused", "running")))
                .order_by(CampaignRun.id.desc())
                .limit(1)
            )
            return r.scalar_one_or_none()

    async def set_run_status(self, run_id: int, status: str):
        async with Session() as s:
            await s.execute(update(CampaignRun).where(CampaignRun.id == run_id).values(status=status))
            await s.commit()

    async def skip_pending(self, run_id: int, reason: str):
        async with Session() as s:
            await s.execute(
                update(Delivery)
                .where(Delivery.run_id == run_id, Delivery.status == "pending")
                .values(status="skipped", error=reason[:2000])
            )
            await s.commit()

    async def cancel_resumable_runs(self, campaign_id: int, reason: str = "campaign canceled"):
        async with Session() as s:
            r = await s.execute(
                select(CampaignRun.id).where(
                    CampaignRun.campaign_id == campaign_id,
                    CampaignRun.status.in_(("paused", "running"))
                )
            )
            run_ids = [x for x in r.scalars()]
            if not run_ids:
                return
            await s.execute(
                update(Delivery)
                .where(Delivery.run_id.in_(run_ids), Delivery.status == "pending")
                .values(status="skipped", error=reason[:2000])
            )
            await s.execute(
                update(CampaignRun)
                .where(CampaignRun.id.in_(run_ids))
                .values(status="canceled", finished_at=utcnow())
            )
            await s.commit()

    async def finish_run(self, run_id: int, status: str):
        async with Session() as s:
            sent = await s.scalar(select(func.count()).select_from(Delivery).where(Delivery.run_id == run_id, Delivery.status == "sent")) or 0
            failed = await s.scalar(select(func.count()).select_from(Delivery).where(Delivery.run_id == run_id, Delivery.status == "failed")) or 0
            skipped = await s.scalar(select(func.count()).select_from(Delivery).where(Delivery.run_id == run_id, Delivery.status == "skipped")) or 0
            await s.execute(update(CampaignRun).where(CampaignRun.id == run_id).values(
                status=status, sent=sent, failed=failed, skipped=skipped, finished_at=utcnow()
            ))
            await s.commit()
            return int(sent), int(failed), int(skipped)

    async def latest_runs(self, limit: int = 10) -> list[CampaignRun]:
        async with Session() as s:
            r = await s.execute(select(CampaignRun).order_by(CampaignRun.id.desc()).limit(limit))
            return list(r.scalars())

    async def stats(self) -> dict:
        async with Session() as s:
            chats = await s.scalar(select(func.count()).select_from(ChatTarget).where(ChatTarget.enabled.is_(True))) or 0
            admins = await s.scalar(select(func.count()).select_from(Admin).where(Admin.active.is_(True))) or 0
            campaigns = await s.scalar(select(func.count()).select_from(Campaign)) or 0
            sent = await s.scalar(select(func.count()).select_from(Delivery).where(Delivery.status == "sent")) or 0
            failed = await s.scalar(select(func.count()).select_from(Delivery).where(Delivery.status == "failed")) or 0
            return {"chats": chats, "admins": admins, "campaigns": campaigns, "sent": sent, "failed": failed}

    async def audit(self, actor_id: int | None, action: str, details: str = ""):
        async with Session() as s:
            s.add(AuditLog(actor_id=actor_id, action=action[:80], details=details[:4000]))
            await s.commit()


repo = Repo()
