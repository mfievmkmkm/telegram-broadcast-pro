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

            target_ids = [int(x) for x in (campaign.target_ids or "").split(",") if x]
            message_ids = [int(x) for x in (campaign.source_message_ids or "").split(",") if x]
            if not target_ids or not message_ids:
                await multi_repo.update_campaign(campaign_id, status="failed", last_result="Нет получателей или контента")
                return

            await multi_repo.update_campaign(campaign_id, status="running", last_run_at=utcnow())
            client = await multi_sender.open_client(account)
            sent = 0
            failed = 0
            try:
                for target_id in target_ids:
                    current = await multi_repo.get_campaign(campaign_id)
                    if not current or current.status in {"paused", "stopped"}:
                        return
                    target = await multi_repo.get_target(target_id)
                    if not target or not target.enabled or target.account_id != account.id:
                        continue
                    try:
                        peer = multi_sender.input_peer(target)
                        await multi_sender.send_saved_bundle(client, peer, message_ids)
                        sent += 1
                        await multi_repo.add_log(campaign_id, target.id, True)
                    except errors.FloodWaitError as e:
                        wait_seconds = int(getattr(e, "seconds", 60))
                        await multi_repo.add_log(campaign_id, target.id, False, f"FloodWait {wait_seconds}s")
                        await multi_repo.update_campaign(
                            campaign_id,
                            status="active",
                            next_run_at=utcnow() + timedelta(seconds=max(wait_seconds, 60)),
                            last_result=f"Telegram попросил подождать {wait_seconds} сек. Запуск перенесён.",
                            sent_total=campaign.sent_total + sent,
                            failed_total=campaign.failed_total + failed,
                        )
                        return
                    except Exception as e:
                        failed += 1
                        err = f"{type(e).__name__}: {e}"[:1000]
                        await multi_repo.add_log(campaign_id, target.id, False, err)
                        log.warning("campaign=%s target=%s error=%s", campaign_id, target.id, err)
                    await asyncio.sleep(max(settings.send_delay_seconds, 0.5))
            finally:
                await client.disconnect()

            current = await multi_repo.get_campaign(campaign_id)
            if not current or current.status in {"paused", "stopped"}:
                return
            total_sent = current.sent_total + sent
            total_failed = current.failed_total + failed
            result = f"Последний круг: ✅ {sent} · ❌ {failed}"
            if current.interval_minutes:
                await multi_repo.update_campaign(
                    campaign_id,
                    status="active",
                    next_run_at=utcnow() + timedelta(minutes=current.interval_minutes),
                    last_result=result,
                    sent_total=total_sent,
                    failed_total=total_failed,
                )
            else:
                await multi_repo.update_campaign(
                    campaign_id,
                    status="completed",
                    next_run_at=None,
                    last_result=result,
                    sent_total=total_sent,
                    failed_total=total_failed,
                )
        except Exception as e:
            log.exception("campaign %s crashed", campaign_id)
            await multi_repo.update_campaign(campaign_id, status="paused", last_result=f"{type(e).__name__}: {e}"[:1000])
        finally:
            self._locks.discard(campaign_id)

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
