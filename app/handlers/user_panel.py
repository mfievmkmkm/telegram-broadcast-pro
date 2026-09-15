from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from ..config import settings
from ..db import repo, utcnow
from ..keyboards import (
    admin_controls, admin_roles, admins_menu, back_main, campaign_confirm,
    campaign_controls, cancel_flow, chat_controls, chats_menu, main_menu,
    schedule_menu, target_menu, template_controls, templates_menu,
)
from ..services.access import require, role_of
from ..services.userbot import user_sender
from ..states import AddChatFlow, AdminFlow, CampaignFlow, TagChatFlow, TemplateFlow

router = Router(name="user_panel")
TZ = ZoneInfo(settings.timezone)

STATUS = {
    "draft": "📝", "scheduled": "🗓", "running": "🚀", "paused": "⏸",
    "completed": "✅", "failed": "❌", "canceled": "🛑",
}


def fmt_dt(value: datetime | None) -> str:
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ).strftime("%d.%m.%Y %H:%M")


def parse_local_datetime(text: str) -> datetime | None:
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text.strip(), fmt).replace(tzinfo=TZ).astimezone(timezone.utc)
        except ValueError:
            pass
    return None


async def show_main(target: Message | CallbackQuery, state: FSMContext | None = None):
    if state:
        await state.clear()
    role = await role_of(target.from_user.id)
    sender = await user_sender.sender_label()
    text = (
        "📨 <b>Broadcast Pro · User Mode</b>\n\n"
        f"Отправитель: <b>{html.escape(sender)}</b>\n"
        f"Роль: <b>{html.escape(role or 'none')}</b>\n"
        f"Часовой пояс: <code>{html.escape(settings.timezone)}</code>\n\n"
        "Панель управляет рассылками, а сообщения уходят от обычного Telegram-аккаунта."
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=main_menu(role or "viewer"), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=main_menu(role or "viewer"), parse_mode="HTML")


@router.message(CommandStart())
@router.message(Command("panel"))
async def start(message: Message, state: FSMContext):
    if await require(message, "viewer"):
        await show_main(message, state)


@router.message(Command("id"))
async def id_cmd(message: Message):
    await message.answer(f"Ваш user_id: <code>{message.from_user.id}</code>\nchat_id: <code>{message.chat.id}</code>", parse_mode="HTML")


@router.callback_query(F.data == "menu")
async def menu(call: CallbackQuery, state: FSMContext):
    if await require(call, "viewer"):
        await show_main(call, state)


@router.callback_query(F.data == "flow:cancel")
async def cancel(call: CallbackQuery, state: FSMContext):
    if await require(call, "viewer"):
        await state.clear()
        await show_main(call)


# ---------- CHATS ----------
@router.callback_query(F.data == "chat:list")
async def chat_list(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    chats = await repo.list_chats()
    await call.message.edit_text(
        f"💬 <b>Чаты</b>\n\nВсего: <b>{len(chats)}</b> · активных: <b>{sum(c.enabled for c in chats)}</b>\n"
        "Добавляй только группы/каналы, где подключённому аккаунту разрешено писать.",
        reply_markup=chats_menu(chats), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "chat:add")
async def chat_add(call: CallbackQuery, state: FSMContext):
    if not await require(call, "admin"):
        return
    await state.set_state(AddChatFlow.waiting_chat_id)
    await call.message.edit_text(
        "➕ <b>Добавить чат</b>\n\n"
        "Управляющего бота туда добавлять не нужно. В чате должен состоять аккаунт-отправитель.\n\n"
        "Пришли <code>@username</code> публичной группы/канала или <code>-100...</code> chat_id.",
        reply_markup=cancel_flow(), parse_mode="HTML"
    )
    await call.answer()


@router.message(AddChatFlow.waiting_chat_id)
async def chat_add_value(message: Message, state: FSMContext):
    if not await require(message, "admin"):
        return
    raw = (message.text or "").strip()
    ref: int | str = int(raw) if raw.lstrip("-").isdigit() else raw
    try:
        target = await user_sender.resolve_target(ref)
        await repo.upsert_chat(target.chat_id, target.title, target.chat_type, target.username, message.from_user.id)
        await repo.audit(message.from_user.id, "chat_add", f"chat={target.chat_id} via=userbot")
        await state.clear()
        chats = await repo.list_chats()
        await message.answer(f"✅ <b>{html.escape(target.title)}</b> добавлен", reply_markup=chats_menu(chats), parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Не удалось добавить: <code>{html.escape(type(e).__name__ + ': ' + str(e))}</code>", parse_mode="HTML")


@router.callback_query(F.data.startswith("chat:view:"))
async def chat_view(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    chat_id = int(call.data.split(":")[-1])
    c = await repo.get_chat(chat_id)
    if not c:
        await call.answer("Чат не найден", show_alert=True); return
    await call.message.edit_text(
        f"💬 <b>{html.escape(c.title)}</b>\n\nID: <code>{c.chat_id}</code>\n"
        f"Тип: <code>{html.escape(c.chat_type)}</code>\n"
        f"Статус: {'✅ активен' if c.enabled else '⛔ выключен'}\n"
        f"Теги: <code>{html.escape(c.tags or '—')}</code>",
        reply_markup=chat_controls(c.chat_id, c.enabled), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("chat:toggle:"))
async def chat_toggle(call: CallbackQuery):
    if not await require(call, "admin"):
        return
    cid = int(call.data.split(":")[-1])
    c = await repo.get_chat(cid)
    if c:
        await repo.set_chat_enabled(cid, not c.enabled)
        c = await repo.get_chat(cid)
        await call.message.edit_reply_markup(reply_markup=chat_controls(cid, c.enabled))
    await call.answer("Статус изменён")


@router.callback_query(F.data.startswith("chat:tags:"))
async def chat_tags(call: CallbackQuery, state: FSMContext):
    if not await require(call, "admin"):
        return
    await state.set_state(TagChatFlow.waiting_tags)
    await state.update_data(tag_chat_id=int(call.data.split(":")[-1]))
    await call.message.edit_text("🏷 Пришли теги через запятую, например <code>ads, football</code>. Для очистки — <code>-</code>.", reply_markup=cancel_flow(), parse_mode="HTML")
    await call.answer()


@router.message(TagChatFlow.waiting_tags)
async def chat_tags_value(message: Message, state: FSMContext):
    if not await require(message, "admin"):
        return
    data = await state.get_data()
    raw = (message.text or "").strip()
    await repo.set_chat_tags(int(data["tag_chat_id"]), [] if raw == "-" else raw.split(","))
    await state.clear()
    await message.answer("✅ Теги сохранены", reply_markup=back_main())


@router.callback_query(F.data.startswith("chat:check:"))
async def chat_check(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    ok, note = await user_sender.check_target(int(call.data.split(":")[-1]))
    await call.answer(("✅ " if ok else "⚠️ ") + note[:160], show_alert=True)


# ---------- TEMPLATES ----------
@router.callback_query(F.data == "template:list")
async def template_list(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    items = await repo.list_templates()
    await call.message.edit_text(
        "🧩 <b>Шаблоны</b>\n\nНовый шаблон берёт последнее сообщение/альбом из Избранного аккаунта-отправителя.",
        reply_markup=templates_menu(items), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "template:new")
async def template_new(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    await state.set_state(TemplateFlow.waiting_name)
    await call.message.edit_text("Сначала положи пост в Избранное аккаунта-отправителя. Теперь пришли название шаблона.", reply_markup=cancel_flow())
    await call.answer()


@router.message(TemplateFlow.waiting_name)
async def template_name(message: Message, state: FSMContext):
    if not await require(message, "editor"):
        return
    name = (message.text or "").strip()[:120]
    if not name:
        await message.answer("Название пустое"); return
    try:
        ids, preview = await user_sender.latest_saved_bundle()
        t = await repo.create_template(name, user_sender.me.id, ids, message.from_user.id)
        await state.clear()
        await message.answer(
            f"✅ Шаблон <b>{html.escape(t.name)}</b> сохранён · {len(ids)} сообщ.\n{html.escape(preview[:180])}",
            reply_markup=template_controls(t.id), parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Не смог взять пост из Избранного: <code>{html.escape(str(e))}</code>", parse_mode="HTML")


@router.callback_query(F.data.startswith("template:view:"))
async def template_view(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    tid = int(call.data.split(":")[-1])
    t = await repo.get_template(tid)
    if not t:
        await call.answer("Шаблон не найден", show_alert=True); return
    await call.message.edit_text(f"🧩 <b>{html.escape(t.name)}</b>\nID: <code>{t.id}</code>", reply_markup=template_controls(t.id), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("template:delete:"))
async def template_delete(call: CallbackQuery):
    if not await require(call, "editor"):
        return
    await repo.delete_template(int(call.data.split(":")[-1]))
    await call.message.edit_text("✅ Шаблон удалён", reply_markup=back_main())
    await call.answer()


# ---------- CAMPAIGNS ----------
async def begin_campaign(target: Message | CallbackQuery, state: FSMContext, template_id: int | None = None):
    await state.clear()
    if template_id:
        t = await repo.get_template(template_id)
        if not t:
            return
        ids = [int(x) for x in (t.source_message_ids or str(t.source_message_id)).split(",") if x]
        await state.update_data(source_chat_id=t.source_chat_id, source_message_id=t.source_message_id, source_message_ids=ids, preview_text=f"[шаблон] {t.name}")
    await state.set_state(CampaignFlow.waiting_name)
    text = (
        "📣 <b>Новая рассылка</b>\n\n"
        + ("Используется сохранённый шаблон.\n\n" if template_id else "1) Положи нужный пост/альбом в <b>Избранное</b> аккаунта-отправителя.\n2) ")
        + "Пришли название кампании."
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=cancel_flow(), parse_mode="HTML"); await target.answer()
    else:
        await target.answer(text, reply_markup=cancel_flow(), parse_mode="HTML")


@router.callback_query(F.data == "campaign:new")
async def campaign_new(call: CallbackQuery, state: FSMContext):
    if await require(call, "editor"):
        await begin_campaign(call, state)


@router.callback_query(F.data.startswith("template:use:"))
async def campaign_from_template(call: CallbackQuery, state: FSMContext):
    if await require(call, "editor"):
        await begin_campaign(call, state, int(call.data.split(":")[-1]))


@router.message(CampaignFlow.waiting_name)
async def campaign_name(message: Message, state: FSMContext):
    if not await require(message, "editor"):
        return
    name = (message.text or "").strip()[:160]
    if not name:
        await message.answer("Название пустое"); return
    data = await state.get_data()
    if not data.get("source_message_id"):
        try:
            ids, preview = await user_sender.latest_saved_bundle()
            await state.update_data(source_chat_id=user_sender.me.id, source_message_id=ids[0], source_message_ids=ids, preview_text=preview)
        except Exception as e:
            await message.answer(f"❌ Сначала положи пост в Избранное. <code>{html.escape(str(e))}</code>", parse_mode="HTML"); return
    await state.update_data(name=name)
    tags = await repo.all_tags()
    await state.set_state(CampaignFlow.choosing_target)
    await message.answer("🎯 Куда отправляем?", reply_markup=target_menu(tags))


@router.callback_query(CampaignFlow.choosing_target, F.data.startswith("target:"))
async def campaign_target(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    parts = call.data.split(":", 2)
    mode = parts[1]
    value = parts[2] if mode == "tag" and len(parts) > 2 else None
    targets = await repo.target_chats(mode, value)
    if not targets:
        await call.answer("Нет активных чатов", show_alert=True); return
    await state.update_data(target_mode=mode, target_value=value, target_count=len(targets))
    await state.set_state(CampaignFlow.choosing_schedule)
    await call.message.edit_text(f"🎯 Получателей: <b>{len(targets)}</b>\n\nВыбери режим времени:", reply_markup=schedule_menu(), parse_mode="HTML")
    await call.answer()


async def show_confirm(target: Message | CallbackQuery, state: FSMContext):
    d = await state.get_data()
    repeat = d.get("repeat_minutes")
    text = (
        "✅ <b>Проверь кампанию</b>\n\n"
        f"Название: <b>{html.escape(d.get('name', ''))}</b>\n"
        f"Чатов: <b>{d.get('target_count', 0)}</b>\n"
        f"Старт: <b>{fmt_dt(d.get('scheduled_at'))}</b>\n"
        f"Повтор: <b>{('каждые ' + str(repeat) + ' мин') if repeat else 'нет'}</b>\n\n"
        "🧪 Перед запуском можно отправить тест в Избранное."
    )
    await state.set_state(CampaignFlow.confirming)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=campaign_confirm(), parse_mode="HTML"); await target.answer()
    else:
        await target.answer(text, reply_markup=campaign_confirm(), parse_mode="HTML")


@router.callback_query(CampaignFlow.choosing_schedule, F.data == "schedule:now")
async def schedule_now(call: CallbackQuery, state: FSMContext):
    await state.update_data(scheduled_at=utcnow(), repeat_minutes=None)
    await show_confirm(call, state)


@router.callback_query(CampaignFlow.choosing_schedule, F.data.startswith("schedule:repeat:"))
async def schedule_repeat_quick(call: CallbackQuery, state: FSMContext):
    minutes = int(call.data.rsplit(":", 1)[-1])
    if minutes < 15:
        await call.answer("Минимум 15 минут", show_alert=True); return
    await state.update_data(scheduled_at=utcnow(), repeat_minutes=minutes)
    await show_confirm(call, state)


@router.callback_query(CampaignFlow.choosing_schedule, F.data == "schedule:repeat")
async def schedule_repeat(call: CallbackQuery, state: FSMContext):
    await state.set_state(CampaignFlow.waiting_repeat_minutes)
    await call.message.edit_text("🔁 Пришли интервал в минутах. Минимум <b>15</b>. Например: <code>15</code>, <code>45</code>, <code>180</code>.", reply_markup=cancel_flow(), parse_mode="HTML")
    await call.answer()


@router.message(CampaignFlow.waiting_repeat_minutes)
async def repeat_value(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 15:
        await message.answer("Нужно число минут ≥ 15"); return
    await state.update_data(scheduled_at=utcnow(), repeat_minutes=min(int(raw), 525600))
    await show_confirm(message, state)


@router.callback_query(CampaignFlow.choosing_schedule, F.data == "schedule:custom")
async def schedule_custom(call: CallbackQuery, state: FSMContext):
    await state.set_state(CampaignFlow.waiting_datetime)
    await call.message.edit_text(f"🕒 Пришли дату/время ({html.escape(settings.timezone)}):\n<code>16.09.2026 18:30</code>", reply_markup=cancel_flow(), parse_mode="HTML")
    await call.answer()


@router.message(CampaignFlow.waiting_datetime)
async def datetime_value(message: Message, state: FSMContext):
    dt = parse_local_datetime(message.text or "")
    if not dt or dt <= utcnow() - timedelta(minutes=1):
        await message.answer("Не понял время или оно уже прошло. Пример: <code>16.09.2026 18:30</code>", parse_mode="HTML"); return
    await state.update_data(scheduled_at=dt, repeat_minutes=None)
    await show_confirm(message, state)


@router.callback_query(CampaignFlow.confirming, F.data == "campaign:test")
async def campaign_test(call: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    try:
        ids = sorted(set(d.get("source_message_ids") or [d["source_message_id"]]))
        await user_sender.resend_saved_bundle("me", ids)
        await call.answer("🧪 Тест отправлен в Избранное аккаунта-отправителя", show_alert=True)
    except Exception as e:
        await call.answer(f"Ошибка теста: {type(e).__name__}", show_alert=True)


@router.callback_query(CampaignFlow.confirming, F.data == "campaign:confirm")
async def campaign_confirm_create(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    d = await state.get_data()
    ids = sorted(set(d.get("source_message_ids") or [d["source_message_id"]]))
    c = await repo.create_campaign(
        name=d["name"], source_chat_id=d["source_chat_id"], source_message_id=ids[0],
        source_message_ids=",".join(map(str, ids)), preview_text=d.get("preview_text", ""),
        target_mode=d["target_mode"], target_value=d.get("target_value"), status="scheduled",
        scheduled_at=d["scheduled_at"], repeat_minutes=d.get("repeat_minutes"),
        button_text=None, button_url=None, created_by=call.from_user.id,
    )
    await repo.audit(call.from_user.id, "campaign_create", f"campaign={c.id}")
    await state.clear()
    await call.message.edit_text(f"✅ <b>Кампания #{c.id}</b> создана\nСтарт: <b>{fmt_dt(c.scheduled_at)}</b>", reply_markup=campaign_controls(c.id, c.status), parse_mode="HTML")
    await call.answer("Кампания создана")


@router.callback_query(F.data == "campaign:list")
async def campaign_list(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    items = await repo.list_campaigns(limit=20)
    rows = [[InlineKeyboardButton(text=f"{STATUS.get(c.status, '•')} #{c.id} {c.name[:30]}", callback_data=f"campaign:view:{c.id}")] for c in items]
    rows += [[InlineKeyboardButton(text="➕ Новая рассылка", callback_data="campaign:new")], [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu")]]
    await call.message.edit_text("🗓 <b>Кампании</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("campaign:view:"))
async def campaign_view(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    c = await repo.get_campaign(int(call.data.split(":")[-1]))
    if not c:
        await call.answer("Не найдено", show_alert=True); return
    await call.message.edit_text(
        f"{STATUS.get(c.status, '•')} <b>Кампания #{c.id}</b>\n\n"
        f"{html.escape(c.name)}\nСтатус: <code>{c.status}</code>\n"
        f"Следующий запуск: <b>{fmt_dt(c.scheduled_at)}</b>\n"
        f"Повтор: <b>{str(c.repeat_minutes) + ' мин' if c.repeat_minutes else 'нет'}</b>\n"
        f"Ошибка: <code>{html.escape((c.last_error or '—')[:350])}</code>",
        reply_markup=campaign_controls(c.id, c.status), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("campaign:pause:"))
async def campaign_pause(call: CallbackQuery):
    if not await require(call, "editor"):
        return
    cid = int(call.data.split(":")[-1]); await repo.update_campaign(cid, status="paused")
    await call.message.edit_reply_markup(reply_markup=campaign_controls(cid, "paused")); await call.answer("Пауза")


@router.callback_query(F.data.startswith("campaign:resume:"))
async def campaign_resume(call: CallbackQuery):
    if not await require(call, "editor"):
        return
    cid = int(call.data.split(":")[-1]); await repo.update_campaign(cid, status="scheduled", scheduled_at=utcnow())
    await call.message.edit_reply_markup(reply_markup=campaign_controls(cid, "scheduled")); await call.answer("Продолжаю")


@router.callback_query(F.data.startswith("campaign:stop:"))
async def campaign_stop(call: CallbackQuery):
    if not await require(call, "editor"):
        return
    cid = int(call.data.split(":")[-1]); await repo.update_campaign(cid, status="canceled"); await repo.cancel_resumable_runs(cid)
    await call.message.edit_reply_markup(reply_markup=campaign_controls(cid, "canceled")); await call.answer("Остановлено")


@router.callback_query(F.data.startswith("campaign:rerun:"))
async def campaign_rerun(call: CallbackQuery):
    if not await require(call, "editor"):
        return
    cid = int(call.data.split(":")[-1]); await repo.cancel_resumable_runs(cid, "full rerun"); await repo.update_campaign(cid, status="scheduled", scheduled_at=utcnow())
    await call.message.edit_reply_markup(reply_markup=campaign_controls(cid, "scheduled")); await call.answer("Поставлено в очередь")


# ---------- ADMINS ----------
@router.callback_query(F.data == "admin:list")
async def admin_list(call: CallbackQuery):
    if not await require(call, "owner"):
        return
    admins = await repo.list_admins()
    await call.message.edit_text("👥 <b>Администраторы</b>\nowner — всё · admin — чаты/кампании · editor — кампании · viewer — просмотр", reply_markup=admins_menu(admins), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "admin:add")
async def admin_add(call: CallbackQuery, state: FSMContext):
    if not await require(call, "owner"):
        return
    await state.set_state(AdminFlow.waiting_user_id)
    await call.message.edit_text("Пришли Telegram user_id нового админа.", reply_markup=cancel_flow()); await call.answer()


@router.message(AdminFlow.waiting_user_id)
async def admin_user_id(message: Message, state: FSMContext):
    if not await require(message, "owner"):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой ID"); return
    uid = int(raw); await state.update_data(admin_user_id=uid); await state.set_state(AdminFlow.waiting_role)
    await message.answer("Выбери роль:", reply_markup=admin_roles(uid))


@router.callback_query(F.data.startswith("admin:role:"))
async def admin_set_role(call: CallbackQuery, state: FSMContext):
    if not await require(call, "owner"):
        return
    _, _, uid, role = call.data.split(":")
    if role not in {"admin", "editor", "viewer"}:
        return
    await repo.upsert_admin(int(uid), role); await state.clear()
    await call.message.edit_text("✅ Доступ сохранён", reply_markup=admins_menu(await repo.list_admins())); await call.answer()


@router.callback_query(F.data.startswith("admin:view:"))
async def admin_view(call: CallbackQuery):
    if not await require(call, "owner"):
        return
    uid = int(call.data.split(":")[-1]); a = await repo.get_admin(uid)
    if not a:
        await call.answer("Не найден", show_alert=True); return
    await call.message.edit_text(f"👤 <b>{uid}</b>\nРоль: <code>{a.role}</code>", reply_markup=admin_controls(uid, a.role), parse_mode="HTML"); await call.answer()


@router.callback_query(F.data.startswith("admin:changerole:"))
async def admin_change_role(call: CallbackQuery):
    if not await require(call, "owner"):
        return
    uid = int(call.data.split(":")[-1]); a = await repo.get_admin(uid)
    if not a or a.role == "owner":
        await call.answer("Owner меняется через OWNER_IDS", show_alert=True); return
    await call.message.edit_text("Новая роль:", reply_markup=admin_roles(uid)); await call.answer()


@router.callback_query(F.data.startswith("admin:remove:"))
async def admin_remove(call: CallbackQuery):
    if not await require(call, "owner"):
        return
    uid = int(call.data.split(":")[-1]); a = await repo.get_admin(uid)
    if not a or a.role == "owner":
        await call.answer("Owner нельзя удалить здесь", show_alert=True); return
    await repo.deactivate_admin(uid)
    await call.message.edit_text("✅ Доступ удалён", reply_markup=admins_menu(await repo.list_admins())); await call.answer()


# ---------- STATS / HEALTH ----------
@router.callback_query(F.data == "stats")
async def stats(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    s = await repo.stats(); runs = await repo.latest_runs(limit=5)
    total = s["sent"] + s["failed"]; success = s["sent"] / total * 100 if total else 0
    recent = "\n".join(f"• #{r.campaign_id}: ✅ {r.sent} · ❌ {r.failed}" for r in runs) or "Запусков пока нет"
    await call.message.edit_text(
        f"📊 <b>Статистика</b>\n\nАктивных чатов: <b>{s['chats']}</b>\nКампаний: <b>{s['campaigns']}</b>\n"
        f"Успешно: <b>{s['sent']}</b> · ошибок: <b>{s['failed']}</b> · {success:.1f}%\n\n{recent}",
        reply_markup=back_main(), parse_mode="HTML"
    ); await call.answer()


@router.callback_query(F.data == "health")
async def health(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    chats = await repo.list_chats(enabled_only=True); good = 0; bad = []
    for c in chats[:50]:
        ok, note = await user_sender.check_target(c.chat_id)
        good += int(ok)
        if not ok:
            bad.append(f"• {c.title}: {note}")
    detail = "\n".join(html.escape(x) for x in bad[:10]) or "Ошибок доступа не найдено"
    await call.message.edit_text(
        f"🩺 <b>Система</b>\n\nАккаунт: <b>{html.escape(await user_sender.sender_label())}</b>\n"
        f"Чатов доступно: <b>{good}/{min(len(chats), 50)}</b>\n\n{detail}", reply_markup=back_main(), parse_mode="HTML"
    ); await call.answer()
