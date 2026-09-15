from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from telethon import errors

from ..config import settings
from ..multi_db import multi_repo, utcnow
from .multi_sender import multi_sender

log = logging.getLogger("multi-broadcast")


class MultiBroadcastService:
    def __init__(self):
        self._locks: set[int] = set()
        self._account_locks: dict[int, asyncio.Lock] = {}

    async def run_campaign(self, campaign_id: int):
        if campaign_id in self._locks:
            return
        self._locks.add(campaign_id)
        try:
            campaign = await multi_repo.get_campaign(campaign_id)
            if not campaign or campaign.status not in {"scheduled", "active", "running"}:
                return
            account = await multi_repo.get_account(campaign.account_id)
            if not account or not account.active:
                await multi_repo.update_campaign(campaign_id, status="paused", last_result="Аккаунт отключён")
                return

            account_lock = self._account_locks.setdefault(account.id, asyncio.Lock())
            async with account_lock:
                await self._run_locked(campaign_id, account)
        except Exception as e:
            log.exception("campaign %s crashed", campaign_id)
            await multi_repo.update_campaign(campaign_id, status="paused", last_result=f"{type(e).__name__}: {e}"[:1000])
        finally:
            self._locks.discard(campaign_id)

    async def _run_locked(self, campaign_id: int, account):
        campaign = await multi_repo.get_campaign(campaign_id)
        if not campaign or campaign.status not in {"scheduled", "active", "running"}:
            return

        target_ids = [int(x) for x in (campaign.target_ids or "").split(",") if x]
        message_ids = [int(x) for x in (campaign.source_message_ids or "").split(",") if x]
        if not target_ids or not message_ids:
            await multi_repo.update_campaign(campaign_id, status="failed", last_result="Нет получателей или контента")
            return

        cursor = max(0, min(int(campaign.run_cursor or 0), len(target_ids)))
        await multi_repo.update_campaign(campaign_id, status="running", last_run_at=utcnow())
        client = await multi_sender.open_client(account)
        cycle_sent = 0
        cycle_failed = 0
        try:
            for idx in range(cursor, len(target_ids)):
                current = await multi_repo.get_campaign(campaign_id)
                if not current or current.status in {"paused", "stopped"}:
                    return

                target_id = target_ids[idx]
                target = await multi_repo.get_target(target_id)
                if not target or not target.enabled or target.account_id != account.id:
                    await multi_repo.advance_campaign(campaign_id, idx + 1)
                    continue

                while True:
                    current = await multi_repo.get_campaign(campaign_id)
                    if not current or current.status in {"paused", "stopped"}:
                        return
                    try:
                        peer = multi_sender.input_peer(target)
                        await multi_sender.send_saved_bundle(client, peer, message_ids)
                        cycle_sent += 1
                        await multi_repo.add_log(campaign_id, target.id, True)
                        await multi_repo.advance_campaign(campaign_id, idx + 1, sent_delta=1)
                        break
                    except errors.FloodWaitError as e:
                        wait_seconds = max(int(getattr(e, "seconds", 60)), 1)
                        await multi_repo.update_campaign(
                            campaign_id,
                            last_result=f"FloodWait: Telegram попросил подождать {wait_seconds} сек. Прогресс сохранён.",
                        )
                        if wait_seconds > 900:
                            await multi_repo.update_campaign(
                                campaign_id,
                                status="active",
                                next_run_at=utcnow() + timedelta(seconds=wait_seconds + 1),
                            )
                            return
                        await asyncio.sleep(wait_seconds + 1)
                        continue
                    except Exception as e:
                        cycle_failed += 1
                        err = f"{type(e).__name__}: {e}"[:1000]
                        await multi_repo.add_log(campaign_id, target.id, False, err)
                        await multi_repo.advance_campaign(campaign_id, idx + 1, failed_delta=1)
                        log.warning("campaign=%s target=%s error=%s", campaign_id, target.id, err)
                        break

                await asyncio.sleep(max(settings.send_delay_seconds, 0.5))
        finally:
            await client.disconnect()

        current = await multi_repo.get_campaign(campaign_id)
        if not current or current.status in {"paused", "stopped"}:
            return

        result = f"Последний круг: ✅ {cycle_sent} · ❌ {cycle_failed}"
        if current.interval_minutes:
            await multi_repo.update_campaign(
                campaign_id,
                status="active",
                next_run_at=utcnow() + timedelta(minutes=current.interval_minutes),
                run_cursor=0,
                last_result=result,
            )
        else:
            await multi_repo.update_campaign(
                campaign_id,
                status="completed",
                next_run_at=None,
                run_cursor=0,
                last_result=result,
            )

    async def worker(self):
        while True:
            try:
                due = await multi_repo.due_campaigns(utcnow())
                for campaign in due:
                    asyncio.create_task(self.run_campaign(campaign.id))
            except Exception:
                log.exception("scheduler error")
            await asyncio.sleep(max(settings.worker_poll_seconds, 2))


multi_broadcast = MultiBroadcastService()
