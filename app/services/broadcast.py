from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from telethon.errors import FloodWaitError, RPCError

from ..config import settings
from ..db import repo, utcnow
from .userbot import user_sender

log = logging.getLogger("broadcast")


class BroadcastService:
    def __init__(self):
        self._locks: set[int] = set()

    async def execute_campaign(self, campaign_id: int):
        if campaign_id in self._locks:
            return
        self._locks.add(campaign_id)
        try:
            campaign = await repo.get_campaign(campaign_id)
            if not campaign or campaign.status not in {"scheduled", "running"}:
                return

            targets = await repo.target_chats(campaign.target_mode, campaign.target_value)
            if len(targets) > settings.max_recipients_per_campaign:
                await repo.update_campaign(
                    campaign_id, status="failed",
                    last_error=f"recipient limit exceeded: {len(targets)} > {settings.max_recipients_per_campaign}"
                )
                return

            await repo.update_campaign(campaign_id, status="running", last_run_at=utcnow(), last_error=None)
            run = await repo.resumable_run(campaign_id)
            if run is None:
                run = await repo.create_run(campaign_id, len(targets))
                await repo.create_deliveries(run.id, [x.chat_id for x in targets])
            else:
                await repo.set_run_status(run.id, "running")

            deliveries = await repo.pending_deliveries(run.id)
            by_chat = {x.chat_id: x for x in targets}
            ids = [int(x) for x in (campaign.source_message_ids or str(campaign.source_message_id)).split(",") if x]
            ids = sorted(set(ids))
            extra_link = None
            if campaign.button_text and campaign.button_url:
                extra_link = (campaign.button_text, campaign.button_url)

            for delivery in deliveries:
                current = await repo.get_campaign(campaign_id)
                if not current:
                    return
                if current.status == "paused":
                    await repo.finish_run(run.id, "paused")
                    return
                if current.status == "canceled":
                    await repo.skip_pending(run.id, "campaign canceled")
                    await repo.finish_run(run.id, "canceled")
                    return

                target = by_chat.get(delivery.chat_id)
                if not target or not target.enabled:
                    await repo.mark_delivery(delivery.id, "skipped", delivery.attempts, "chat disabled")
                    continue

                attempts = 0
                error = None
                sent = False
                while attempts <= settings.max_retries and not sent:
                    attempts += 1
                    try:
                        await user_sender.resend_saved_bundle(delivery.chat_id, ids, extra_link=extra_link)
                        sent = True
                    except FloodWaitError as e:
                        wait_for = int(getattr(e, "seconds", 0) or 0)
                        error = f"FloodWaitError: wait {wait_for}s"
                        await asyncio.sleep(wait_for + 1)
                    except RPCError as e:
                        error = f"{type(e).__name__}: {e}"
                        break
                    except Exception as e:
                        error = f"{type(e).__name__}: {e}"
                        if attempts <= settings.max_retries:
                            await asyncio.sleep(min(2 * attempts, 5))

                if sent:
                    await repo.mark_delivery(delivery.id, "sent", attempts)
                else:
                    await repo.mark_delivery(delivery.id, "failed", attempts, error or "unknown error")
                    log.warning("Campaign %s -> %s failed: %s", campaign_id, delivery.chat_id, error)

                await asyncio.sleep(settings.send_delay_seconds)

            sent_count, failed_count, skipped_count = await repo.finish_run(run.id, "completed")
            current = await repo.get_campaign(campaign_id)
            if not current:
                return
            if current.status in {"canceled", "paused"}:
                return

            if current.repeat_minutes and current.repeat_minutes > 0:
                next_at = utcnow() + timedelta(minutes=current.repeat_minutes)
                await repo.update_campaign(campaign_id, status="scheduled", scheduled_at=next_at)
            else:
                await repo.update_campaign(campaign_id, status="completed")

            await repo.audit(None, "campaign_run", f"campaign={campaign_id} sent={sent_count} failed={failed_count} skipped={skipped_count}")
        except Exception as e:
            log.exception("Campaign %s crashed", campaign_id)
            await repo.update_campaign(campaign_id, status="failed", last_error=f"{type(e).__name__}: {e}"[:2000])
        finally:
            self._locks.discard(campaign_id)

    async def worker(self):
        while True:
            try:
                due = await repo.due_campaigns(utcnow())
                for campaign in due:
                    asyncio.create_task(self.execute_campaign(campaign.id))
            except Exception:
                log.exception("Scheduler worker error")
            await asyncio.sleep(settings.worker_poll_seconds)
