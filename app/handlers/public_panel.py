from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from ..config import settings
from ..multi_db import multi_repo, utcnow
from ..public_keyboards import (
    account_view_kb, accounts_kb, back_home, campaign_view_kb, campaigns_kb,
    choose_account_kb, code_keypad, confirm_kb, dialog_picker_kb, home_kb,
    login_method_kb, qr_kb, schedule_kb, source_kb, target_mode_kb,
    target_select_kb, targets_kb,
)
from ..public_states import CampaignWizard, LoginFlow
from ..services.account_auth import auth_manager
from ..services.multi_sender import multi_sender

router = Router(name="public-panel")
TZ = ZoneInfo(settings.timezone)


def account_label(account) -> str:
    if account.username:
        return f"@{account.username}"
    if account.first_name:
        return account.first_name
    return str(account.tg_user_id)


def fmt_dt(value: datetime | None) -> str:
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ).strftime("%d.%m.%Y %H:%M")


def parse_dt(text: str) -> datetime | None:
    raw = text.strip()
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=TZ).astimezone(timezone.utc)
        except ValueError:
            pass
    return None


async def render_home(target: Message | CallbackQuery, state: FSMContext | None = None):
    if state:
        await state.clear()
    uid = target.from_user.id
    accounts, active, sent, failed = await multi_repo.stats(uid)
    text = (
        "<b>⚡ BROADCAST</b>\n"
        "<i>рассылки от твоих Telegram-аккаунтов</i>\n\n"
        f"👤 Аккаунтов: <b>{accounts}</b>\n"
        f"🔁 Активных рассылок: <b>{active}</b>\n"
        f"✅ Отправлено: <b>{sent}</b> · ❌ ошибок: <b>{failed}</b>\n\n"
        "Подключи аккаунт → выбери его чаты → положи пост в Избранное → задай интервал."
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=home_kb(), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=home_kb(), parse_mode="HTML")


@router.message(CommandStart())
@router.message(Command("panel"))
async def start(message: Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("Открой бота в личке — подключение аккаунтов работает только там.")
        return
    await render_home(message, state)


@router.callback_query(F.data == "pub:home")
async def home(call: CallbackQuery, state: FSMContext):
    await auth_manager.cancel(call.from_user.id)
    await render_home(call, state)


@router.callback_query(F.data == "pub:help")
async def help_page(call: CallbackQuery):
    text = (
        "<b>ℹ️ Как это работает</b>\n\n"
        "<b>1.</b> Подключаешь свой Telegram по QR или номеру.\n"
        "<b>2.</b> Бот показывает группы и каналы этого аккаунта — отмечаешь нужные.\n"
        "<b>3.</b> Готовый пост кладёшь в <b>Избранное</b> подключённого аккаунта.\n"
        "<b>4.</b> Создаёшь рассылку и выбираешь: один раз, каждые 15/30/60/120 минут или свой интервал.\n\n"
        "🔐 Telegram-сессия хранится в базе зашифрованно. Код входа и пароль 2FA не сохраняются.\n"
        "⚠️ Отправляй только туда, где такие сообщения разрешены. Ограничения Telegram и FloodWait не обходятся."
    )
    await call.message.edit_text(text, reply_markup=back_home(), parse_mode="HTML")
    await call.answer()


# ---------------- ACCOUNTS / LOGIN ----------------
@router.callback_query(F.data == "pub:accounts")
async def accounts_page(call: CallbackQuery):
    items = await multi_repo.list_accounts(call.from_user.id)
    await call.message.edit_text(
        f"<b>👤 Мои аккаунты</b>\n\nПодключено: <b>{len(items)}</b> из <b>{settings.max_accounts_per_user}</b>\n"
        "Каждый аккаунт полностью отделён: свои чаты и свои рассылки.",
        reply_markup=accounts_kb(items), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "acct:add")
async def account_add(call: CallbackQuery, state: FSMContext):
    items = await multi_repo.list_accounts(call.from_user.id)
    if len(items) >= settings.max_accounts_per_user:
        await call.answer(f"Лимит: {settings.max_accounts_per_user} аккаунтов", show_alert=True)
        return
    await state.clear()
    await call.message.edit_text(
        "<b>➕ Подключение Telegram</b>\n\n"
        "Выбери способ входа. QR — самый удобный: код вводить не нужно.\n\n"
        "🔐 После входа сохраняется только зашифрованная сессия.",
        reply_markup=login_method_kb(), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "login:cancel")
async def login_cancel(call: CallbackQuery, state: FSMContext):
    await auth_manager.cancel(call.from_user.id)
    await state.clear()
    await accounts_page(call)


@router.callback_query(F.data == "login:phone")
async def login_phone(call: CallbackQuery, state: FSMContext):
    await state.set_state(LoginFlow.waiting_phone)
    await call.message.edit_text(
        "<b>📱 Вход по номеру</b>\n\nПришли номер в международном формате:\n<code>+79991234567</code>\n\n"
        "Сообщение с номером удалю после обработки.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="login:cancel")]]),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(LoginFlow.waiting_phone)
async def login_phone_value(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    digits = re.sub(r"\D", "", raw)
    try:
        await message.delete()
    except Exception:
        pass
    if not (7 <= len(digits) <= 15):
        await message.answer("❌ Номер не похож на корректный. Пример: <code>+79991234567</code>", parse_mode="HTML")
        return
    phone = "+" + digits
    status = await message.answer("⏳ Отправляю код входа через Telegram…")
    try:
        await auth_manager.start_phone(message.from_user.id, phone)
    except Exception as e:
        await state.clear()
        await status.edit_text(f"❌ Не удалось отправить код: <code>{html.escape(type(e).__name__ + ': ' + str(e))}</code>", reply_markup=login_method_kb(), parse_mode="HTML")
        return
    await state.set_state(LoginFlow.waiting_code)
    await state.update_data(code_digits="")
    await status.edit_text(
        "<b>🔢 Код отправлен</b>\n\nВведи его кнопками ниже — так код не нужно пересылать сообщением.\n\nКод: <code>•••••</code>",
        reply_markup=code_keypad(0), parse_mode="HTML"
    )


@router.callback_query(LoginFlow.waiting_code, F.data.startswith("login:digit:"))
async def login_code_keypad(call: CallbackQuery, state: FSMContext):
    action = call.data.rsplit(":", 1)[-1]
    data = await state.get_data()
    code = str(data.get("code_digits", ""))
    if action.isdigit() and len(code) < 8:
        code += action
        await state.update_data(code_digits=code)
    elif action == "back":
        code = code[:-1]
        await state.update_data(code_digits=code)
    elif action == "ok":
        if len(code) < 4:
            await call.answer("Код слишком короткий", show_alert=True)
            return
        result, account = await auth_manager.verify_code(call.from_user.id, code)
        if result == "password":
            await state.set_state(LoginFlow.waiting_password)
            await call.message.edit_text(
                "<b>🔐 Включена двухэтапная защита</b>\n\nПришли пароль 2FA одним сообщением. "
                "Я сразу удалю сообщение и не сохраню пароль.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="login:cancel")]]),
                parse_mode="HTML"
            )
            await call.answer()
            return
        if result == "invalid":
            await state.update_data(code_digits="")
            await call.message.edit_text("❌ Неверный код. Попробуй ещё раз.\n\nКод: <code>•••••</code>", reply_markup=code_keypad(0), parse_mode="HTML")
            await call.answer()
            return
        if result in {"expired", "failed"} or not account:
            await state.clear()
            await call.message.edit_text("⌛ Код/сессия входа истекли. Запусти подключение заново.", reply_markup=login_method_kb())
            await call.answer()
            return
        await login_success(call, state, account)
        return

    await call.message.edit_text(
        f"<b>🔢 Код отправлен</b>\n\nВведи его кнопками ниже.\n\nКод: <code>{'•' * len(code)}{'·' * max(0, 5-len(code))}</code>",
        reply_markup=code_keypad(len(code)), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "login:noop")
async def login_noop(call: CallbackQuery):
    await call.answer()


@router.message(LoginFlow.waiting_password)
async def login_password(message: Message, state: FSMContext):
    password = message.text or ""
    try:
        await message.delete()
    except Exception:
        pass
    result, account = await auth_manager.verify_password(message.from_user.id, password)
    if result == "invalid":
        await message.answer("❌ Пароль не подошёл. Пришли пароль 2FA ещё раз.")
        return
    if result != "ok" or not account:
        await state.clear()
        await message.answer("⌛ Сессия входа истекла. Начни подключение заново.", reply_markup=login_method_kb())
        return
    await state.clear()
    await message.answer(
        f"<b>✅ Аккаунт подключён</b>\n\n👤 {html.escape(account_label(account))}\n📱 {html.escape(account.phone_masked or 'скрыт')}",
        reply_markup=account_view_kb(account.id), parse_mode="HTML"
    )


@router.callback_query(F.data == "login:qr")
async def login_qr(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("⏳ Создаю безопасный QR для входа…", parse_mode="HTML")
    try:
        png = await auth_manager.start_qr(call.from_user.id)
    except Exception as e:
        await call.message.edit_text(f"❌ QR не создался: <code>{html.escape(str(e))}</code>", reply_markup=login_method_kb(), parse_mode="HTML")
        await call.answer()
        return
    await call.message.answer_photo(
        BufferedInputFile(png, filename="telegram-login.png"),
        caption=(
            "<b>▦ Вход по QR</b>\n\n"
            "Telegram → Настройки → Устройства → Подключить устройство → отсканируй QR.\n\n"
            "После сканирования нажми <b>«Я отсканировал»</b>. QR быстро истекает — его можно обновить."
        ),
        reply_markup=qr_kb(), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "login:qr:refresh")
async def login_qr_refresh(call: CallbackQuery):
    try:
        png = await auth_manager.refresh_qr(call.from_user.id)
        await call.message.answer_photo(BufferedInputFile(png, filename="telegram-login.png"), caption="🔄 Новый QR. Отсканируй его и нажми «Я отсканировал».", reply_markup=qr_kb())
        await call.answer("QR обновлён")
    except Exception as e:
        await call.answer(f"Ошибка: {type(e).__name__}", show_alert=True)


@router.callback_query(F.data == "login:qr:check")
async def login_qr_check(call: CallbackQuery, state: FSMContext):
    result, account = await auth_manager.check_qr(call.from_user.id)
    if result == "pending":
        await call.answer("Пока не вижу подтверждения. Отсканируй QR в Telegram.", show_alert=True)
        return
    if result == "password":
        await state.set_state(LoginFlow.waiting_password)
        await call.message.answer(
            "<b>🔐 У аккаунта включён 2FA</b>\n\nПришли пароль одним сообщением. Я удалю его сразу после проверки.",
            parse_mode="HTML"
        )
        await call.answer()
        return
    if result == "expired":
        png = await auth_manager.refresh_qr(call.from_user.id)
        await call.message.answer_photo(BufferedInputFile(png, filename="telegram-login.png"), caption="⌛ Старый QR истёк. Вот новый:", reply_markup=qr_kb())
        await call.answer("QR обновлён")
        return
    if result != "ok" or not account:
        await call.answer("Не получилось завершить вход. Обнови QR.", show_alert=True)
        return
    await login_success(call, state, account)


async def login_success(call: CallbackQuery, state: FSMContext, account):
    await state.clear()
    await call.message.answer(
        f"<b>✅ Аккаунт подключён</b>\n\n👤 {html.escape(account_label(account))}\n"
        f"📱 {html.escape(account.phone_masked or 'скрыт')}\n\nТеперь добавь группы/каналы этого аккаунта.",
        reply_markup=account_view_kb(account.id), parse_mode="HTML"
    )
    await call.answer("Готово")


@router.callback_query(F.data.startswith("acct:view:"))
async def account_view(call: CallbackQuery):
    aid = int(call.data.split(":")[-1])
    account = await multi_repo.get_account(aid, call.from_user.id)
    if not account or not account.active:
        await call.answer("Аккаунт не найден", show_alert=True)
        return
    targets = await multi_repo.list_targets(call.from_user.id, aid, enabled_only=True)
    await call.message.edit_text(
        f"<b>👤 {html.escape(account_label(account))}</b>\n\n"
        f"Telegram ID: <code>{account.tg_user_id}</code>\n"
        f"Телефон: <code>{html.escape(account.phone_masked or 'скрыт')}</code>\n"
        f"Получателей: <b>{len(targets)}</b>\n"
        f"Подключён: <b>{fmt_dt(account.created_at)}</b>",
        reply_markup=account_view_kb(aid), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("acct:check:"))
async def account_check(call: CallbackQuery):
    aid = int(call.data.split(":")[-1])
    account = await multi_repo.get_account(aid, call.from_user.id)
    if not account:
        await call.answer("Не найден", show_alert=True); return
    ok, note = await multi_sender.check_account(account)
    await call.answer(("✅ " if ok else "❌ ") + note[:170], show_alert=True)


@router.callback_query(F.data.startswith("acct:unlink:"))
async def account_unlink_ask(call: CallbackQuery):
    aid = int(call.data.split(":")[-1])
    account = await multi_repo.get_account(aid, call.from_user.id)
    if not account:
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, отключить", callback_data=f"acct:unlinkok:{aid}")],
        [InlineKeyboardButton(text="↩️ Нет", callback_data=f"acct:view:{aid}")],
    ])
    await call.message.edit_text(
        f"<b>Отключить {html.escape(account_label(account))}?</b>\n\n"
        "Активные рассылки этого аккаунта будут поставлены на паузу. Эта Telegram-сессия будет завершена.",
        reply_markup=markup, parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("acct:unlinkok:"))
async def account_unlink(call: CallbackQuery):
    aid = int(call.data.split(":")[-1])
    account = await multi_repo.get_account(aid, call.from_user.id)
    if account:
        await multi_sender.logout_account(account)
        await multi_repo.deactivate_account(aid, call.from_user.id)
    await call.message.edit_text("✅ Аккаунт отключён, его сессия завершена.", reply_markup=back_home())
    await call.answer()


# ---------------- TARGETS ----------------
@router.callback_query(F.data == "pub:targets")
async def targets_entry(call: CallbackQuery):
    accounts = await multi_repo.list_accounts(call.from_user.id)
    if not accounts:
        await call.message.edit_text("Сначала подключи Telegram-аккаунт.", reply_markup=login_method_kb())
        await call.answer(); return
    if len(accounts) == 1:
        await show_targets(call, accounts[0].id)
        return
    await call.message.edit_text("<b>🎯 Получатели</b>\n\nВыбери аккаунт:", reply_markup=choose_account_kb(accounts, "acct:targets"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("acct:targets:"))
async def targets_for_account(call: CallbackQuery):
    await show_targets(call, int(call.data.split(":")[-1]))


async def show_targets(call: CallbackQuery, account_id: int):
    account = await multi_repo.get_account(account_id, call.from_user.id)
    if not account:
        await call.answer("Аккаунт не найден", show_alert=True); return
    targets = await multi_repo.list_targets(call.from_user.id, account_id)
    await call.message.edit_text(
        f"<b>🎯 Получатели · {html.escape(account_label(account))}</b>\n\n"
        f"Добавлено: <b>{len(targets)}</b> · активных: <b>{sum(1 for t in targets if t.enabled)}</b>\n\n"
        "Нажми «Добавить из моих чатов» — бот покажет группы и каналы, которые видит этот аккаунт.",
        reply_markup=targets_kb(targets, account_id), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("target:dialogs:"))
async def dialogs_picker(call: CallbackQuery):
    _, _, aid, page = call.data.split(":")
    aid, page = int(aid), int(page)
    account = await multi_repo.get_account(aid, call.from_user.id)
    if not account:
        await call.answer("Аккаунт не найден", show_alert=True); return
    await call.answer("Загружаю чаты…")
    try:
        dialogs = await multi_sender.list_dialogs(account)
    except Exception as e:
        await call.message.edit_text(f"❌ Не смог загрузить диалоги: <code>{html.escape(str(e))}</code>", reply_markup=account_view_kb(aid), parse_mode="HTML")
        return
    existing = await multi_repo.list_targets(call.from_user.id, aid)
    added = {(t.peer_kind, t.peer_id) for t in existing}
    await call.message.edit_text(
        f"<b>➕ Выбери чаты</b>\n\nНайдено групп/каналов: <b>{len(dialogs)}</b>\n✅ — уже добавлено",
        reply_markup=dialog_picker_kb(dialogs, aid, added, page), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("target:add:"))
async def target_add_from_dialog(call: CallbackQuery):
    _, _, aid, kind, peer_id, page = call.data.split(":")
    aid, peer_id, page = int(aid), int(peer_id), int(page)
    account = await multi_repo.get_account(aid, call.from_user.id)
    if not account:
        await call.answer("Аккаунт не найден", show_alert=True); return
    dialogs = await multi_sender.list_dialogs(account)
    item = next((d for d in dialogs if d.peer_kind == kind and d.peer_id == peer_id), None)
    if not item:
        await call.answer("Чат больше не найден в аккаунте", show_alert=True); return
    await multi_repo.upsert_target(call.from_user.id, aid, item.peer_id, item.peer_kind, item.access_hash, item.title, item.username)
    existing = await multi_repo.list_targets(call.from_user.id, aid)
    added = {(t.peer_kind, t.peer_id) for t in existing}
    await call.message.edit_reply_markup(reply_markup=dialog_picker_kb(dialogs, aid, added, page))
    await call.answer("Добавлено ✅")


@router.callback_query(F.data.startswith("target:toggle:"))
async def target_toggle(call: CallbackQuery):
    _, _, target_id, account_id = call.data.split(":")
    await multi_repo.toggle_target(int(target_id), call.from_user.id)
    await show_targets(call, int(account_id))


# ---------------- CAMPAIGN WIZARD ----------------
@router.callback_query(F.data == "pub:new")
async def new_campaign(call: CallbackQuery, state: FSMContext):
    accounts = await multi_repo.list_accounts(call.from_user.id)
    if not accounts:
        await call.message.edit_text("Сначала подключи Telegram-аккаунт.", reply_markup=login_method_kb())
        await call.answer(); return
    await state.clear()
    if len(accounts) == 1:
        await begin_wizard(call, state, accounts[0].id)
        return
    await state.set_state(CampaignWizard.choosing_account)
    await call.message.edit_text("<b>📣 Новая рассылка</b>\n\nОт какого аккаунта отправлять?", reply_markup=choose_account_kb(accounts, "wiz:account"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("acct:new:"))
@router.callback_query(F.data.startswith("wiz:account:"))
async def wizard_account(call: CallbackQuery, state: FSMContext):
    await begin_wizard(call, state, int(call.data.split(":")[-1]))


async def begin_wizard(call: CallbackQuery, state: FSMContext, account_id: int):
    account = await multi_repo.get_account(account_id, call.from_user.id)
    if not account:
        await call.answer("Аккаунт не найден", show_alert=True); return
    await state.clear()
    await state.set_state(CampaignWizard.choosing_source)
    await state.update_data(account_id=account_id)
    await call.message.edit_text(
        f"<b>📣 Рассылка · {html.escape(account_label(account))}</b>\n\n"
        "1. Открой <b>Избранное</b> этого аккаунта.\n"
        "2. Отправь туда готовый пост — текст, фото, видео или альбом.\n"
        "3. Вернись сюда и нажми кнопку ниже.\n\n"
        "Бот возьмёт именно последнее сообщение/альбом.",
        reply_markup=source_kb(account_id), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("wiz:source:"))
async def wizard_source(call: CallbackQuery, state: FSMContext):
    aid = int(call.data.split(":")[-1])
    account = await multi_repo.get_account(aid, call.from_user.id)
    if not account:
        await call.answer("Аккаунт не найден", show_alert=True); return
    try:
        ids, preview = await multi_sender.latest_saved_bundle(account)
    except Exception as e:
        await call.answer(f"Не смог прочитать Избранное: {str(e)[:120]}", show_alert=True); return
    targets = await multi_repo.list_targets(call.from_user.id, aid, enabled_only=True)
    if not targets:
        await call.message.edit_text(
            "✅ Пост нашёл, но получателей ещё нет. Сначала добавь группы/каналы аккаунта.",
            reply_markup=targets_kb([], aid)
        )
        await call.answer(); return
    await state.update_data(account_id=aid, source_message_ids=ids, preview=preview, selected_target_ids=[])
    await state.set_state(CampaignWizard.choosing_targets)
    await call.message.edit_text(
        f"<b>✅ Контент найден</b> · {len(ids)} сообщ.\n\n<blockquote>{html.escape(preview[:350])}</blockquote>\n"
        f"Получателей доступно: <b>{len(targets)}</b>\n\nКому отправлять?",
        reply_markup=target_mode_kb(aid), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("wiz:targets:all:"))
async def wizard_targets_all(call: CallbackQuery, state: FSMContext):
    aid = int(call.data.split(":")[-1])
    targets = await multi_repo.list_targets(call.from_user.id, aid, enabled_only=True)
    if not targets:
        await call.answer("Нет активных получателей", show_alert=True); return
    if len(targets) > settings.max_targets_per_campaign:
        await call.answer(f"Слишком много: {len(targets)}. Лимит {settings.max_targets_per_campaign}", show_alert=True); return
    await state.update_data(selected_target_ids=[t.id for t in targets])
    await ask_campaign_name(call, state)


@router.callback_query(F.data.startswith("wiz:targets:pick:"))
async def wizard_targets_pick(call: CallbackQuery, state: FSMContext):
    _, _, _, aid, page = call.data.split(":")
    aid, page = int(aid), int(page)
    targets = await multi_repo.list_targets(call.from_user.id, aid, enabled_only=True)
    data = await state.get_data()
    selected = {int(x) for x in data.get("selected_target_ids", [])}
    await call.message.edit_text(
        "<b>🎯 Выбери получателей</b>\n\nМожно отметить несколько групп/каналов.",
        reply_markup=target_select_kb(targets, selected, aid, page), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("wiz:target:toggle:"))
async def wizard_target_toggle(call: CallbackQuery, state: FSMContext):
    _, _, _, aid, tid, page = call.data.split(":")
    aid, tid, page = int(aid), int(tid), int(page)
    data = await state.get_data()
    selected = {int(x) for x in data.get("selected_target_ids", [])}
    if tid in selected:
        selected.remove(tid)
    elif len(selected) < settings.max_targets_per_campaign:
        selected.add(tid)
    await state.update_data(selected_target_ids=sorted(selected))
    targets = await multi_repo.list_targets(call.from_user.id, aid, enabled_only=True)
    await call.message.edit_reply_markup(reply_markup=target_select_kb(targets, selected, aid, page))
    await call.answer()


@router.callback_query(F.data.startswith("wiz:targets:done:"))
async def wizard_targets_done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected_target_ids"):
        await call.answer("Выбери хотя бы один чат", show_alert=True); return
    await ask_campaign_name(call, state)


async def ask_campaign_name(call: CallbackQuery, state: FSMContext):
    await state.set_state(CampaignWizard.waiting_name)
    await call.message.edit_text(
        "<b>✏️ Название рассылки</b>\n\nНапиши короткое название для себя, например:\n<code>Реклама лиги · вечер</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="pub:home")]]),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(CampaignWizard.waiting_name)
async def wizard_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()[:160]
    if not name:
        await message.answer("Название не должно быть пустым."); return
    await state.update_data(name=name)
    await state.set_state(CampaignWizard.choosing_schedule)
    await message.answer(
        f"<b>⏱ Режим отправки</b>\n\nМинимальный повтор: <b>{settings.min_repeat_minutes} минут</b>. Когда отправлять?",
        reply_markup=schedule_kb(), parse_mode="HTML"
    )


@router.callback_query(CampaignWizard.choosing_schedule, F.data.startswith("wiz:schedule:"))
async def wizard_schedule(call: CallbackQuery, state: FSMContext):
    value = call.data.rsplit(":", 1)[-1]
    if value == "custom":
        await state.set_state(CampaignWizard.waiting_interval)
        await call.message.edit_text(
            f"<b>⚙️ Свой интервал</b>\n\nПришли число минут. Минимум: <b>{settings.min_repeat_minutes}</b>.\nНапример: <code>45</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="pub:home")]]),
            parse_mode="HTML"
        )
        await call.answer(); return
    if value == "datetime":
        await state.set_state(CampaignWizard.waiting_datetime)
        await call.message.edit_text(
            f"<b>🕒 Отправить по времени</b>\n\nЧасовой пояс: <code>{html.escape(settings.timezone)}</code>\n"
            "Пришли дату и время:\n<code>16.09.2026 18:30</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="pub:home")]]),
            parse_mode="HTML"
        )
        await call.answer(); return
    if value == "now":
        await state.update_data(next_run_at=utcnow(), interval_minutes=None)
    else:
        minutes = int(value)
        if minutes < settings.min_repeat_minutes:
            minutes = settings.min_repeat_minutes
        await state.update_data(next_run_at=utcnow(), interval_minutes=minutes)
    await show_confirmation(call, state)


@router.message(CampaignWizard.waiting_interval)
async def wizard_interval(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Пришли только число минут."); return
    minutes = int(raw)
    if minutes < settings.min_repeat_minutes:
        await message.answer(f"Минимум — {settings.min_repeat_minutes} минут."); return
    if minutes > 43200:
        await message.answer("Максимум — 43200 минут (30 дней)."); return
    await state.update_data(next_run_at=utcnow(), interval_minutes=minutes)
    await show_confirmation(message, state)


@router.message(CampaignWizard.waiting_datetime)
async def wizard_datetime(message: Message, state: FSMContext):
    dt = parse_dt(message.text or "")
    if not dt:
        await message.answer("Формат: <code>16.09.2026 18:30</code>", parse_mode="HTML"); return
    if dt <= utcnow():
        await message.answer("Это время уже прошло."); return
    await state.update_data(next_run_at=dt, interval_minutes=None)
    await show_confirmation(message, state)


async def show_confirmation(target: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    account = await multi_repo.get_account(int(data["account_id"]), target.from_user.id)
    if not account:
        return
    interval = data.get("interval_minutes")
    mode = f"каждые {interval} мин" if interval else "один раз"
    text = (
        "<b>🚀 Всё готово</b>\n\n"
        f"👤 Отправитель: <b>{html.escape(account_label(account))}</b>\n"
        f"📝 Название: <b>{html.escape(data.get('name',''))}</b>\n"
        f"🎯 Получателей: <b>{len(data.get('selected_target_ids', []))}</b>\n"
        f"⏱ Режим: <b>{mode}</b>\n"
        f"🕒 Первый запуск: <b>{fmt_dt(data.get('next_run_at'))}</b>\n\n"
        f"<blockquote>{html.escape(str(data.get('preview',''))[:350])}</blockquote>"
    )
    await state.set_state(CampaignWizard.confirming)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=confirm_kb(), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=confirm_kb(), parse_mode="HTML")


@router.callback_query(CampaignWizard.confirming, F.data == "wiz:test")
async def wizard_test(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    account = await multi_repo.get_account(int(data["account_id"]), call.from_user.id)
    if not account:
        return
    try:
        await multi_sender.test_to_saved(account, [int(x) for x in data.get("source_message_ids", [])])
        await call.answer("🧪 Копия отправлена в Избранное этого аккаунта", show_alert=True)
    except Exception as e:
        await call.answer(f"Тест не отправился: {type(e).__name__}", show_alert=True)


@router.callback_query(CampaignWizard.confirming, F.data == "wiz:launch")
async def wizard_launch(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    aid = int(data["account_id"])
    account = await multi_repo.get_account(aid, call.from_user.id)
    if not account:
        await call.answer("Аккаунт не найден", show_alert=True); return
    selected = [int(x) for x in data.get("selected_target_ids", [])]
    valid = []
    for tid in selected[:settings.max_targets_per_campaign]:
        t = await multi_repo.get_target(tid, call.from_user.id)
        if t and t.account_id == aid and t.enabled:
            valid.append(tid)
    if not valid:
        await call.answer("Нет доступных получателей", show_alert=True); return
    c = await multi_repo.create_campaign(
        owner_user_id=call.from_user.id,
        account_id=aid,
        name=data["name"],
        message_ids=[int(x) for x in data["source_message_ids"]],
        target_ids=valid,
        next_run_at=data["next_run_at"],
        interval_minutes=data.get("interval_minutes"),
    )
    await state.clear()
    await call.message.edit_text(
        f"<b>✅ Рассылка #{c.id} запущена</b>\n\n{html.escape(c.name)}\n"
        f"Первый запуск: <b>{fmt_dt(c.next_run_at)}</b>\n"
        f"Повтор: <b>{str(c.interval_minutes) + ' мин' if c.interval_minutes else 'нет'}</b>",
        reply_markup=campaign_view_kb(c.id, c.status), parse_mode="HTML"
    )
    await call.answer("Готово")


# ---------------- CAMPAIGNS / STATS ----------------
@router.callback_query(F.data == "pub:campaigns")
async def campaigns_page(call: CallbackQuery):
    items = await multi_repo.list_campaigns(call.from_user.id)
    await call.message.edit_text(
        f"<b>🗓 Мои рассылки</b>\n\nПоследних: <b>{len(items)}</b>\n🔁 активна · ⏸ пауза · ✅ завершена",
        reply_markup=campaigns_kb(items), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("camp:view:"))
async def campaign_view(call: CallbackQuery):
    cid = int(call.data.split(":")[-1])
    c = await multi_repo.get_campaign(cid, call.from_user.id)
    if not c:
        await call.answer("Не найдено", show_alert=True); return
    account = await multi_repo.get_account(c.account_id, call.from_user.id)
    await call.message.edit_text(
        f"<b>📣 Рассылка #{c.id}</b>\n\n"
        f"{html.escape(c.name)}\n"
        f"👤 {html.escape(account_label(account)) if account else 'аккаунт отключён'}\n"
        f"Статус: <code>{c.status}</code>\n"
        f"Следующий запуск: <b>{fmt_dt(c.next_run_at)}</b>\n"
        f"Интервал: <b>{str(c.interval_minutes) + ' мин' if c.interval_minutes else 'нет'}</b>\n"
        f"✅ Всего: <b>{c.sent_total}</b> · ❌ <b>{c.failed_total}</b>\n"
        f"Последний результат: <code>{html.escape((c.last_result or '—')[:500])}</code>",
        reply_markup=campaign_view_kb(c.id, c.status), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("camp:pause:"))
async def campaign_pause(call: CallbackQuery):
    cid = int(call.data.split(":")[-1])
    c = await multi_repo.get_campaign(cid, call.from_user.id)
    if c:
        await multi_repo.update_campaign(cid, status="paused")
        await call.message.edit_reply_markup(reply_markup=campaign_view_kb(cid, "paused"))
    await call.answer("Пауза")


@router.callback_query(F.data.startswith("camp:stop:"))
async def campaign_stop(call: CallbackQuery):
    cid = int(call.data.split(":")[-1])
    c = await multi_repo.get_campaign(cid, call.from_user.id)
    if c:
        await multi_repo.update_campaign(cid, status="stopped", next_run_at=None)
        await call.message.edit_reply_markup(reply_markup=campaign_view_kb(cid, "stopped"))
    await call.answer("Остановлено")


@router.callback_query(F.data.startswith("camp:resume:"))
async def campaign_resume(call: CallbackQuery):
    cid = int(call.data.split(":")[-1])
    c = await multi_repo.get_campaign(cid, call.from_user.id)
    if c:
        await multi_repo.update_campaign(cid, status="scheduled", next_run_at=utcnow())
        await call.message.edit_reply_markup(reply_markup=campaign_view_kb(cid, "scheduled"))
    await call.answer("Продолжаю")


@router.callback_query(F.data == "pub:stats")
async def stats_page(call: CallbackQuery):
    accounts, active, sent, failed = await multi_repo.stats(call.from_user.id)
    total = sent + failed
    rate = (sent / total * 100) if total else 0
    await call.message.edit_text(
        "<b>📊 Статистика</b>\n\n"
        f"👤 Аккаунтов: <b>{accounts}</b>\n"
        f"🔁 Активных/на паузе: <b>{active}</b>\n"
        f"✅ Успешно отправлено: <b>{sent}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>\n"
        f"📈 Успешность: <b>{rate:.1f}%</b>",
        reply_markup=back_home(), parse_mode="HTML"
    )
    await call.answer()
