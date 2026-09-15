from __future__ import annotations

import asyncio
import html
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import repo, utcnow
from ..keyboards import (
    admin_controls, admin_roles, admins_menu, back_main, campaign_confirm,
    campaign_controls, cancel_flow, chat_controls, chats_menu, content_collect_done, main_menu,
    schedule_menu, target_menu, template_controls, templates_menu,
)
from ..states import AddChatFlow, AdminFlow, CampaignFlow, TagChatFlow, TemplateFlow
from ..services.access import require, role_of
from ..services.chat_rights import check_chat_rights

router = Router(name="panel")
TZ = ZoneInfo(settings.timezone)
CONTENT_LOCKS: dict[int, asyncio.Lock] = {}

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
    raw = text.strip()
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=TZ)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    return None


async def show_main(target: Message | CallbackQuery, state: FSMContext | None = None):
    if state:
        await state.clear()
    user_id = target.from_user.id
    role = await role_of(user_id)
    text = (
        "📨 <b>Broadcast Pro</b>\n\n"
        f"Роль: <b>{html.escape(role or 'none')}</b>\n"
        f"Часовой пояс: <code>{html.escape(settings.timezone)}</code>\n\n"
        "Управление чатами, кампаниями, шаблонами и расписанием — из одной панели."
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=main_menu(role or "viewer"), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=main_menu(role or "viewer"), parse_mode="HTML")


@router.message(CommandStart())
@router.message(Command("panel"))
async def start(message: Message, state: FSMContext):
    if not await require(message, "viewer"):
        return
    await show_main(message, state)


@router.message(Command("id"))
async def id_cmd(message: Message):
    await message.answer(f"Ваш user_id: <code>{message.from_user.id}</code>\nchat_id: <code>{message.chat.id}</code>", parse_mode="HTML")


@router.callback_query(F.data == "menu")
async def menu(call: CallbackQuery, state: FSMContext):
    if not await require(call, "viewer"):
        return
    await show_main(call, state)


@router.callback_query(F.data == "flow:cancel")
async def cancel(call: CallbackQuery, state: FSMContext):
    if not await require(call, "viewer"):
        return
    await state.clear()
    await show_main(call)


# ---------- CHATS ----------
@router.message(Command("register_here"))
async def register_here(message: Message, bot: Bot):
    if not await require(message, "admin"):
        return
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эту команду нужно отправить в группе. Для канала используй «Добавить чат» в панели.")
        return
    ok, note = await check_chat_rights(bot, message.chat.id)
    await repo.upsert_chat(
        message.chat.id,
        message.chat.title or str(message.chat.id),
        message.chat.type.value,
        message.chat.username,
        message.from_user.id,
    )
    await repo.audit(message.from_user.id, "chat_register", f"chat={message.chat.id} ok={ok}")
    await message.answer(f"✅ Чат зарегистрирован.\nПроверка прав: <b>{html.escape(note)}</b>", parse_mode="HTML")


@router.callback_query(F.data == "chat:list")
async def chat_list(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    chats = await repo.list_chats()
    enabled = sum(1 for c in chats if c.enabled)
    await call.message.edit_text(
        f"💬 <b>Чаты</b>\n\nВсего: <b>{len(chats)}</b> · активных: <b>{enabled}</b>\n"
        "Нажми на чат для настроек.",
        reply_markup=chats_menu(chats), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "chat:add")
async def chat_add(call: CallbackQuery, state: FSMContext):
    if not await require(call, "admin"):
        return
    await state.set_state(AddChatFlow.waiting_chat_id)
    await call.message.edit_text(
        "➕ <b>Добавление чата</b>\n\n"
        "Добавь бота в группу/канал и дай право отправлять сообщения. Затем пришли сюда <code>chat_id</code> "
        "(обычно начинается с <code>-100</code>) или публичный <code>@username</code>.\n\n"
        "Для групп ещё проще: отправь <code>/register_here</code> прямо в группе.",
        reply_markup=cancel_flow(), parse_mode="HTML"
    )
    await call.answer()


@router.message(AddChatFlow.waiting_chat_id)
async def chat_add_value(message: Message, state: FSMContext, bot: Bot):
    if not await require(message, "admin"):
        return
    raw = (message.text or "").strip()
    ref: int | str = int(raw) if raw.lstrip("-").isdigit() else raw
    try:
        chat = await bot.get_chat(ref)
        ok, note = await check_chat_rights(bot, chat.id)
        await repo.upsert_chat(chat.id, chat.title or chat.full_name or str(chat.id), chat.type.value, chat.username, message.from_user.id)
        await repo.audit(message.from_user.id, "chat_add", f"chat={chat.id} ok={ok}")
        await state.clear()
        chats = await repo.list_chats()
        await message.answer(
            f"✅ <b>{html.escape(chat.title or str(chat.id))}</b> добавлен\n"
            f"Права: {'✅' if ok else '⚠️'} {html.escape(note)}",
            reply_markup=chats_menu(chats), parse_mode="HTML"
        )
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
    tags = c.tags or "—"
    await call.message.edit_text(
        f"💬 <b>{html.escape(c.title)}</b>\n\n"
        f"ID: <code>{c.chat_id}</code>\n"
        f"Тип: <code>{html.escape(c.chat_type)}</code>\n"
        f"Статус: {'✅ активен' if c.enabled else '⛔ выключен'}\n"
        f"Теги: <code>{html.escape(tags)}</code>",
        reply_markup=chat_controls(c.chat_id, c.enabled), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("chat:toggle:"))
async def chat_toggle(call: CallbackQuery):
    if not await require(call, "admin"):
        return
    chat_id = int(call.data.split(":")[-1])
    c = await repo.get_chat(chat_id)
    if not c:
        return
    await repo.set_chat_enabled(chat_id, not c.enabled)
    await repo.audit(call.from_user.id, "chat_toggle", f"chat={chat_id} enabled={not c.enabled}")
    c = await repo.get_chat(chat_id)
    await call.message.edit_reply_markup(reply_markup=chat_controls(chat_id, c.enabled))
    await call.answer("Статус изменён")


@router.callback_query(F.data.startswith("chat:tags:"))
async def chat_tags(call: CallbackQuery, state: FSMContext):
    if not await require(call, "admin"):
        return
    chat_id = int(call.data.split(":")[-1])
    await state.set_state(TagChatFlow.waiting_tags)
    await state.update_data(tag_chat_id=chat_id)
    await call.message.edit_text(
        "🏷 Пришли теги через запятую. Например:\n<code>football, chelyabinsk, partners</code>\n\n"
        "Чтобы очистить теги — отправь <code>-</code>.",
        reply_markup=cancel_flow(), parse_mode="HTML"
    )
    await call.answer()


@router.message(TagChatFlow.waiting_tags)
async def chat_tags_value(message: Message, state: FSMContext):
    if not await require(message, "admin"):
        return
    data = await state.get_data()
    chat_id = int(data["tag_chat_id"])
    raw = (message.text or "").strip()
    tags = [] if raw == "-" else raw.split(",")
    await repo.set_chat_tags(chat_id, tags)
    await repo.audit(message.from_user.id, "chat_tags", f"chat={chat_id} tags={raw}")
    await state.clear()
    c = await repo.get_chat(chat_id)
    await message.answer("✅ Теги сохранены", reply_markup=chat_controls(chat_id, c.enabled))


@router.callback_query(F.data.startswith("chat:check:"))
async def chat_check(call: CallbackQuery, bot: Bot):
    if not await require(call, "admin"):
        return
    chat_id = int(call.data.split(":")[-1])
    ok, note = await check_chat_rights(bot, chat_id)
    await call.answer(("✅ " if ok else "⚠️ ") + note[:150], show_alert=True)


# ---------- TEMPLATES ----------
@router.callback_query(F.data == "template:list")
async def template_list(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    items = await repo.list_templates()
    await call.message.edit_text(
        f"🧩 <b>Шаблоны</b>\n\nСохранено: <b>{len(items)}</b>\n"
        "Шаблон хранит исходное Telegram-сообщение со всем его медиа и форматированием.",
        reply_markup=templates_menu(items), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "template:new")
async def template_new(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    await state.set_state(TemplateFlow.waiting_name)
    await call.message.edit_text("Название шаблона?", reply_markup=cancel_flow())
    await call.answer()


@router.message(TemplateFlow.waiting_name)
async def template_name(message: Message, state: FSMContext):
    if not await require(message, "editor"):
        return
    name = (message.text or "").strip()[:120]
    if not name:
        await message.answer("Название не должно быть пустым."); return
    await state.update_data(template_name=name, template_source_chat_id=message.chat.id, template_message_ids=[])
    await state.set_state(TemplateFlow.waiting_message)
    await message.answer(
        "Теперь отправь одно или несколько сообщений шаблона. Можно текст, фото, видео, документы и альбомы. "
        "Когда закончишь — нажми «Готово».",
        reply_markup=content_collect_done("template", 0)
    )


@router.message(TemplateFlow.waiting_message)
async def template_message(message: Message, state: FSMContext):
    if not await require(message, "editor"):
        return
    lock = CONTENT_LOCKS.setdefault(message.from_user.id, asyncio.Lock())
    async with lock:
        data = await state.get_data()
        source_chat_id = data.get("template_source_chat_id")
        if source_chat_id is not None and source_chat_id != message.chat.id:
            await message.answer("Все сообщения одного шаблона нужно прислать в этот же чат с ботом.")
            return
        ids = list(data.get("template_message_ids", []))
        if message.message_id not in ids:
            ids.append(message.message_id)
        ids = sorted(ids)[:100]
        await state.update_data(template_source_chat_id=message.chat.id, template_message_ids=ids)
    await message.answer(
        f"Добавлено: <b>{len(ids)}</b>. Можешь прислать ещё или нажать «Готово».",
        reply_markup=content_collect_done("template", len(ids)), parse_mode="HTML"
    )


@router.callback_query(TemplateFlow.waiting_message, F.data == "template:content_done")
async def template_content_done(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    data = await state.get_data()
    ids = sorted(set(data.get("template_message_ids", [])))
    if not ids:
        await call.answer("Сначала пришли хотя бы одно сообщение", show_alert=True)
        return
    t = await repo.create_template(
        data["template_name"], data["template_source_chat_id"], ids, call.from_user.id
    )
    await repo.audit(call.from_user.id, "template_create", f"template={t.id} messages={len(ids)}")
    await state.clear()
    await call.message.edit_text(
        f"✅ Шаблон <b>{html.escape(t.name)}</b> сохранён · сообщений: <b>{len(ids)}</b>",
        reply_markup=template_controls(t.id), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("template:view:"))
async def template_view(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    tid = int(call.data.split(":")[-1])
    t = await repo.get_template(tid)
    if not t:
        await call.answer("Шаблон не найден", show_alert=True); return
    await call.message.edit_text(
        f"🧩 <b>{html.escape(t.name)}</b>\n\nСоздан: {fmt_dt(t.created_at)}\nID: <code>{t.id}</code>",
        reply_markup=template_controls(t.id), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("template:delete:"))
async def template_delete(call: CallbackQuery):
    if not await require(call, "editor"):
        return
    tid = int(call.data.split(":")[-1])
    await repo.delete_template(tid)
    await repo.audit(call.from_user.id, "template_delete", f"template={tid}")
    items = await repo.list_templates()
    await call.message.edit_text("🧩 Шаблон удалён", reply_markup=templates_menu(items))
    await call.answer()


# ---------- CAMPAIGN CREATION ----------
async def ask_campaign_name(message_or_call, state: FSMContext, template_id: int | None = None):
    await state.clear()
    if template_id:
        t = await repo.get_template(template_id)
        if not t:
            return False
        await state.update_data(
            source_chat_id=t.source_chat_id,
            source_message_id=t.source_message_id,
            source_message_ids=[int(x) for x in (t.source_message_ids or str(t.source_message_id)).split(",") if x],
            preview_text=f"[шаблон] {t.name}",
            template_id=t.id,
        )
    await state.set_state(CampaignFlow.waiting_name)
    text = "📣 <b>Новая кампания</b>\n\nКак её назвать? Например: <code>Матчи 14 сентября</code>"
    if isinstance(message_or_call, CallbackQuery):
        await message_or_call.message.edit_text(text, reply_markup=cancel_flow(), parse_mode="HTML")
        await message_or_call.answer()
    else:
        await message_or_call.answer(text, reply_markup=cancel_flow(), parse_mode="HTML")
    return True


@router.callback_query(F.data == "campaign:new")
async def campaign_new(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    await ask_campaign_name(call, state)


@router.callback_query(F.data.startswith("template:use:"))
async def campaign_from_template(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    tid = int(call.data.split(":")[-1])
    ok = await ask_campaign_name(call, state, tid)
    if not ok:
        await call.answer("Шаблон не найден", show_alert=True)


@router.message(CampaignFlow.waiting_name)
async def campaign_name(message: Message, state: FSMContext):
    if not await require(message, "editor"):
        return
    name = (message.text or "").strip()[:160]
    if not name:
        await message.answer("Название не должно быть пустым."); return
    await state.update_data(name=name)
    data = await state.get_data()
    if data.get("source_message_id"):
        tags = await repo.all_tags()
        await state.set_state(CampaignFlow.choosing_target)
        await message.answer("Куда отправляем?", reply_markup=target_menu(tags))
    else:
        await state.update_data(source_chat_id=message.chat.id, source_message_ids=[], preview_text="")
        await state.set_state(CampaignFlow.waiting_message)
        await message.answer(
            "Теперь пришли одно или несколько сообщений рассылки. Можно текст, фото, видео, документы и альбомы. "
            "Когда закончишь — нажми «Готово».",
            reply_markup=content_collect_done("campaign", 0)
        )


@router.message(CampaignFlow.waiting_message)
async def campaign_source(message: Message, state: FSMContext):
    if not await require(message, "editor"):
        return
    lock = CONTENT_LOCKS.setdefault(message.from_user.id, asyncio.Lock())
    async with lock:
        data = await state.get_data()
        source_chat_id = data.get("source_chat_id")
        if source_chat_id is not None and source_chat_id != message.chat.id:
            await message.answer("Все сообщения одной кампании нужно прислать в этот же чат с ботом.")
            return
        ids = list(data.get("source_message_ids", []))
        if message.message_id not in ids:
            ids.append(message.message_id)
        ids = sorted(ids)[:100]
        preview = data.get("preview_text") or message.text or message.caption or "[медиа/пакет]"
        await state.update_data(
            source_chat_id=message.chat.id, source_message_id=ids[0], source_message_ids=ids, preview_text=preview[:500]
        )
    await message.answer(
        f"Добавлено: <b>{len(ids)}</b>. Пришли ещё или нажми «Готово».",
        reply_markup=content_collect_done("campaign", len(ids)), parse_mode="HTML"
    )


@router.callback_query(CampaignFlow.waiting_message, F.data == "campaign:content_done")
async def campaign_content_done(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    data = await state.get_data()
    ids = sorted(set(data.get("source_message_ids", [])))
    if not ids:
        await call.answer("Сначала пришли хотя бы одно сообщение", show_alert=True)
        return
    await state.update_data(source_message_id=ids[0], source_message_ids=ids)
    tags = await repo.all_tags()
    await state.set_state(CampaignFlow.choosing_target)
    await call.message.edit_text(
        f"📦 Контент готов · сообщений: <b>{len(ids)}</b>\n\n🎯 Выбери получателей",
        reply_markup=target_menu(tags), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(CampaignFlow.choosing_target, F.data.startswith("target:"))
async def campaign_target(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    parts = call.data.split(":", 2)
    mode = parts[1]
    value = parts[2] if mode == "tag" and len(parts) > 2 else None
    targets = await repo.target_chats(mode, value)
    if not targets:
        await call.answer("В этой группе нет активных чатов", show_alert=True); return
    if len(targets) > settings.max_recipients_per_campaign:
        await call.answer(f"Слишком много чатов: {len(targets)}. Лимит {settings.max_recipients_per_campaign}", show_alert=True); return
    await state.update_data(target_mode=mode, target_value=value, target_count=len(targets))
    await state.set_state(CampaignFlow.choosing_schedule)
    await call.message.edit_text(
        f"🎯 Получателей: <b>{len(targets)}</b>\n\nКогда отправить?",
        reply_markup=schedule_menu(), parse_mode="HTML"
    )
    await call.answer()


async def show_campaign_confirmation(target: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    when = data.get("scheduled_at")
    repeat = data.get("repeat_minutes")
    target_name = "все активные чаты" if data.get("target_mode") == "all" else f"тег #{data.get('target_value')}"
    button = data.get("button_text")
    text = (
        "✅ <b>Проверь кампанию</b>\n\n"
        f"Название: <b>{html.escape(data.get('name', ''))}</b>\n"
        f"Получатели: <b>{data.get('target_count', 0)}</b> · {html.escape(target_name)}\n"
        f"Старт: <b>{fmt_dt(when)}</b>\n"
        f"Повтор: <b>{('каждые ' + str(repeat) + ' мин') if repeat else 'нет'}</b>\n"
        f"CTA: <b>{html.escape(button) if button else 'нет'}</b>\n\n"
        "После создания её можно поставить на паузу или остановить."
    )
    await state.set_state(CampaignFlow.confirming)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=campaign_confirm(), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=campaign_confirm(), parse_mode="HTML")


@router.callback_query(CampaignFlow.choosing_schedule, F.data == "schedule:now")
async def schedule_now(call: CallbackQuery, state: FSMContext):
    await state.update_data(scheduled_at=utcnow(), repeat_minutes=None)
    await show_campaign_confirmation(call, state)


@router.callback_query(CampaignFlow.choosing_schedule, F.data == "schedule:10")
async def schedule_10(call: CallbackQuery, state: FSMContext):
    await state.update_data(scheduled_at=utcnow() + timedelta(minutes=10), repeat_minutes=None)
    await show_campaign_confirmation(call, state)


@router.callback_query(CampaignFlow.choosing_schedule, F.data == "schedule:custom")
async def schedule_custom(call: CallbackQuery, state: FSMContext):
    await state.set_state(CampaignFlow.waiting_datetime)
    await call.message.edit_text(
        f"🕒 Пришли дату и время в часовом поясе <code>{html.escape(settings.timezone)}</code>:\n"
        "<code>14.09.2026 18:30</code>", reply_markup=cancel_flow(), parse_mode="HTML"
    )
    await call.answer()


@router.message(CampaignFlow.waiting_datetime)
async def schedule_datetime_value(message: Message, state: FSMContext):
    dt = parse_local_datetime(message.text or "")
    if not dt:
        await message.answer("Не понял формат. Пример: <code>14.09.2026 18:30</code>", parse_mode="HTML"); return
    if dt <= utcnow() - timedelta(minutes=1):
        await message.answer("Это время уже прошло. Укажи будущее время."); return
    await state.update_data(scheduled_at=dt, repeat_minutes=None)
    await show_campaign_confirmation(message, state)


@router.callback_query(CampaignFlow.choosing_schedule, F.data == "schedule:repeat")
async def schedule_repeat(call: CallbackQuery, state: FSMContext):
    await state.set_state(CampaignFlow.waiting_repeat_minutes)
    await call.message.edit_text(
        "🔁 Через сколько минут повторять рассылку?\n\n"
        "Например: <code>60</code> = раз в час, <code>1440</code> = раз в сутки.\n"
        "Первый запуск — сразу.", reply_markup=cancel_flow(), parse_mode="HTML"
    )
    await call.answer()


@router.message(CampaignFlow.waiting_repeat_minutes)
async def schedule_repeat_value(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 10:
        await message.answer("Минимальный интервал — 10 минут. Пришли число минут."); return
    minutes = min(int(raw), 525600)
    await state.update_data(scheduled_at=utcnow(), repeat_minutes=minutes)
    await show_campaign_confirmation(message, state)


@router.callback_query(CampaignFlow.confirming, F.data == "campaign:button")
async def campaign_button_start(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    await state.set_state(CampaignFlow.waiting_button)
    await call.message.edit_text(
        "🔗 Пришли кнопку в формате:\n<code>Текст кнопки | https://example.com</code>\n\n"
        "Чтобы убрать кнопку, отправь <code>-</code>.",
        reply_markup=cancel_flow(), parse_mode="HTML"
    )
    await call.answer()


@router.message(CampaignFlow.waiting_button)
async def campaign_button_value(message: Message, state: FSMContext):
    if not await require(message, "editor"):
        return
    raw = (message.text or "").strip()
    if raw == "-":
        await state.update_data(button_text=None, button_url=None)
        await show_campaign_confirmation(message, state)
        return
    if "|" not in raw:
        await message.answer("Формат: <code>Текст | https://example.com</code>", parse_mode="HTML")
        return
    text, url = [x.strip() for x in raw.split("|", 1)]
    if not text or len(text) > 64 or not url.startswith(("https://", "http://", "tg://")):
        await message.answer("Проверь текст (до 64 символов) и ссылку http/https/tg.")
        return
    await state.update_data(button_text=text, button_url=url[:500])
    await show_campaign_confirmation(message, state)


@router.callback_query(CampaignFlow.confirming, F.data == "campaign:test")
async def campaign_test_send(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not await require(call, "editor"):
        return
    data = await state.get_data()
    try:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        markup = None
        if data.get("button_text") and data.get("button_url"):
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=data["button_text"], url=data["button_url"])
            ]])
        ids = sorted(set(data.get("source_message_ids") or [data["source_message_id"]]))
        if len(ids) == 1:
            await bot.copy_message(
                chat_id=call.from_user.id, from_chat_id=data["source_chat_id"], message_id=ids[0], reply_markup=markup
            )
        else:
            copied = await bot.copy_messages(
                chat_id=call.from_user.id, from_chat_id=data["source_chat_id"], message_ids=ids[:100]
            )
            if markup and copied:
                await bot.edit_message_reply_markup(
                    chat_id=call.from_user.id, message_id=copied[-1].message_id, reply_markup=markup
                )
        await call.answer("🧪 Тест отправлен тебе в личку", show_alert=True)
    except Exception as e:
        await call.answer(f"Тест не отправлен: {type(e).__name__}", show_alert=True)


@router.callback_query(CampaignFlow.confirming, F.data == "campaign:confirm")
async def campaign_confirm_create(call: CallbackQuery, state: FSMContext):
    if not await require(call, "editor"):
        return
    data = await state.get_data()
    c = await repo.create_campaign(
        name=data["name"],
        source_chat_id=data["source_chat_id"],
        source_message_id=data["source_message_id"],
        source_message_ids=",".join(map(str, sorted(set(data.get("source_message_ids") or [data["source_message_id"]])))),
        preview_text=data.get("preview_text", ""),
        target_mode=data["target_mode"],
        target_value=data.get("target_value"),
        status="scheduled",
        scheduled_at=data["scheduled_at"],
        repeat_minutes=data.get("repeat_minutes"),
        button_text=data.get("button_text"),
        button_url=data.get("button_url"),
        created_by=call.from_user.id,
    )
    await repo.audit(call.from_user.id, "campaign_create", f"campaign={c.id}")
    await state.clear()
    await call.message.edit_text(
        f"✅ <b>Кампания #{c.id} создана</b>\n\n"
        f"{html.escape(c.name)}\nСтарт: <b>{fmt_dt(c.scheduled_at)}</b>",
        reply_markup=campaign_controls(c.id, c.status), parse_mode="HTML"
    )
    await call.answer("Кампания создана")


# ---------- CAMPAIGN MANAGEMENT ----------
@router.callback_query(F.data == "campaign:list")
async def campaign_list(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    items = await repo.list_campaigns(limit=20)
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for c in items:
        icon = STATUS.get(c.status, "•")
        rows.append([InlineKeyboardButton(text=f"{icon} #{c.id} {c.name[:32]}", callback_data=f"campaign:view:{c.id}")])
    rows.append([InlineKeyboardButton(text="➕ Новая рассылка", callback_data="campaign:new")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu")])
    await call.message.edit_text(
        "🗓 <b>Последние кампании</b>\n\n"
        "✅ завершена · 🗓 ожидает · 🚀 идёт · ⏸ пауза · 🛑 остановлена",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("campaign:view:"))
async def campaign_view(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    cid = int(call.data.split(":")[-1])
    c = await repo.get_campaign(cid)
    if not c:
        await call.answer("Кампания не найдена", show_alert=True); return
    target_name = "все" if c.target_mode == "all" else f"#{c.target_value}"
    await call.message.edit_text(
        f"{STATUS.get(c.status, '•')} <b>Кампания #{c.id}</b>\n\n"
        f"Название: <b>{html.escape(c.name)}</b>\n"
        f"Статус: <code>{c.status}</code>\n"
        f"Цель: <code>{html.escape(target_name)}</code>\n"
        f"Следующий запуск: <b>{fmt_dt(c.scheduled_at)}</b>\n"
        f"Повтор: <b>{str(c.repeat_minutes) + ' мин' if c.repeat_minutes else 'нет'}</b>\n"
        f"Последний запуск: <b>{fmt_dt(c.last_run_at)}</b>\n"
        f"Ошибка: <code>{html.escape((c.last_error or '—')[:500])}</code>",
        reply_markup=campaign_controls(c.id, c.status), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("campaign:pause:"))
async def campaign_pause(call: CallbackQuery):
    if not await require(call, "editor"):
        return
    cid = int(call.data.split(":")[-1])
    await repo.update_campaign(cid, status="paused")
    await repo.audit(call.from_user.id, "campaign_pause", f"campaign={cid}")
    await call.message.edit_reply_markup(reply_markup=campaign_controls(cid, "paused"))
    await call.answer("Поставлено на паузу")


@router.callback_query(F.data.startswith("campaign:resume:"))
async def campaign_resume(call: CallbackQuery):
    if not await require(call, "editor"):
        return
    cid = int(call.data.split(":")[-1])
    await repo.update_campaign(cid, status="scheduled", scheduled_at=utcnow())
    await repo.audit(call.from_user.id, "campaign_resume", f"campaign={cid}")
    await call.message.edit_reply_markup(reply_markup=campaign_controls(cid, "scheduled"))
    await call.answer("Продолжаю с оставшихся чатов")


@router.callback_query(F.data.startswith("campaign:stop:"))
async def campaign_stop(call: CallbackQuery):
    if not await require(call, "editor"):
        return
    cid = int(call.data.split(":")[-1])
    await repo.update_campaign(cid, status="canceled")
    await repo.cancel_resumable_runs(cid, "campaign stopped by admin")
    await repo.audit(call.from_user.id, "campaign_stop", f"campaign={cid}")
    await call.message.edit_reply_markup(reply_markup=campaign_controls(cid, "canceled"))
    await call.answer("Кампания остановлена")


@router.callback_query(F.data.startswith("campaign:rerun:"))
async def campaign_rerun(call: CallbackQuery):
    if not await require(call, "editor"):
        return
    cid = int(call.data.split(":")[-1])
    c = await repo.get_campaign(cid)
    if not c:
        return
    await repo.cancel_resumable_runs(cid, "superseded by full rerun")
    await repo.update_campaign(cid, status="scheduled", scheduled_at=utcnow())
    await repo.audit(call.from_user.id, "campaign_rerun", f"campaign={cid}")
    await call.message.edit_reply_markup(reply_markup=campaign_controls(cid, "scheduled"))
    await call.answer("Повторный запуск поставлен в очередь")


# ---------- ADMINS ----------
@router.callback_query(F.data == "admin:list")
async def admin_list(call: CallbackQuery):
    if not await require(call, "owner"):
        return
    admins = await repo.list_admins()
    await call.message.edit_text(
        "👥 <b>Администраторы</b>\n\n"
        "owner — всё\nadmin — кампании + чаты\neditor — кампании + шаблоны\nviewer — просмотр",
        reply_markup=admins_menu(admins), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "admin:add")
async def admin_add(call: CallbackQuery, state: FSMContext):
    if not await require(call, "owner"):
        return
    await state.set_state(AdminFlow.waiting_user_id)
    await call.message.edit_text("Пришли Telegram user_id нового админа. Он может узнать его командой /id.", reply_markup=cancel_flow())
    await call.answer()


@router.message(AdminFlow.waiting_user_id)
async def admin_user_id(message: Message, state: FSMContext):
    if not await require(message, "owner"):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой Telegram user_id."); return
    uid = int(raw)
    await state.update_data(admin_user_id=uid)
    await state.set_state(AdminFlow.waiting_role)
    await message.answer("Выбери роль:", reply_markup=admin_roles(uid))


@router.callback_query(F.data.startswith("admin:role:"))
async def admin_set_role(call: CallbackQuery, state: FSMContext):
    if not await require(call, "owner"):
        return
    _, _, uid, role = call.data.split(":")
    uid = int(uid)
    if role not in {"admin", "editor", "viewer"}:
        return
    await repo.upsert_admin(uid, role)
    await repo.audit(call.from_user.id, "admin_upsert", f"user={uid} role={role}")
    await state.clear()
    admins = await repo.list_admins()
    await call.message.edit_text("✅ Доступ сохранён", reply_markup=admins_menu(admins))
    await call.answer()


@router.callback_query(F.data.startswith("admin:view:"))
async def admin_view(call: CallbackQuery):
    if not await require(call, "owner"):
        return
    uid = int(call.data.split(":")[-1])
    a = await repo.get_admin(uid)
    if not a:
        await call.answer("Не найден", show_alert=True); return
    await call.message.edit_text(
        f"👤 <b>{uid}</b>\nРоль: <code>{a.role}</code>\nСоздан: {fmt_dt(a.created_at)}",
        reply_markup=admin_controls(uid, a.role), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:changerole:"))
async def admin_change_role(call: CallbackQuery):
    if not await require(call, "owner"):
        return
    uid = int(call.data.split(":")[-1])
    a = await repo.get_admin(uid)
    if not a or a.role == "owner":
        await call.answer("Owner меняется только через OWNER_IDS", show_alert=True); return
    await call.message.edit_text("Новая роль:", reply_markup=admin_roles(uid))
    await call.answer()


@router.callback_query(F.data.startswith("admin:remove:"))
async def admin_remove(call: CallbackQuery):
    if not await require(call, "owner"):
        return
    uid = int(call.data.split(":")[-1])
    a = await repo.get_admin(uid)
    if not a or a.role == "owner":
        await call.answer("Owner нельзя удалить из панели", show_alert=True); return
    await repo.deactivate_admin(uid)
    await repo.audit(call.from_user.id, "admin_remove", f"user={uid}")
    admins = await repo.list_admins()
    await call.message.edit_text("✅ Доступ удалён", reply_markup=admins_menu(admins))
    await call.answer()


# ---------- STATS / HEALTH ----------
@router.callback_query(F.data == "stats")
async def stats(call: CallbackQuery):
    if not await require(call, "viewer"):
        return
    s = await repo.stats()
    runs = await repo.latest_runs(limit=5)
    total_deliveries = s["sent"] + s["failed"]
    success = (s["sent"] / total_deliveries * 100) if total_deliveries else 0
    recent = "\n".join(
        f"• #{r.campaign_id}: ✅ {r.sent} · ❌ {r.failed} · ⏭ {r.skipped}" for r in runs
    ) or "Запусков пока нет"
    await call.message.edit_text(
        "📊 <b>Статистика</b>\n\n"
        f"Активных чатов: <b>{s['chats']}</b>\n"
        f"Админов: <b>{s['admins']}</b>\n"
        f"Кампаний: <b>{s['campaigns']}</b>\n"
        f"Успешных доставок: <b>{s['sent']}</b>\n"
        f"Ошибок: <b>{s['failed']}</b>\n"
        f"Успешность: <b>{success:.1f}%</b>\n\n"
        f"<b>Последние запуски</b>\n{recent}",
        reply_markup=back_main(), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "health")
async def health(call: CallbackQuery, bot: Bot):
    if not await require(call, "viewer"):
        return
    await call.answer("Проверяю чаты…")
    chats = await repo.list_chats(enabled_only=True)
    good = 0; bad = []
    for c in chats[:50]:
        ok, note = await check_chat_rights(bot, c.chat_id)
        if ok:
            good += 1
        else:
            bad.append(f"• {c.title}: {note}")
    extra = "\n".join(html.escape(x) for x in bad[:10]) or "Ошибок прав не найдено"
    await call.message.edit_text(
        "🩺 <b>Проверка системы</b>\n\n"
        f"База данных: ✅\n"
        f"Проверено чатов: <b>{min(len(chats), 50)}</b>\n"
        f"Готовы к отправке: <b>{good}</b>\n\n"
        f"{extra}",
        reply_markup=back_main(), parse_mode="HTML"
    )
