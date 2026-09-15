from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu(role: str):
    rows = [
        [InlineKeyboardButton(text="📣 Новая рассылка", callback_data="campaign:new")],
        [InlineKeyboardButton(text="🗓 Кампании", callback_data="campaign:list"), InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🧩 Шаблоны", callback_data="template:list"), InlineKeyboardButton(text="💬 Чаты", callback_data="chat:list")],
    ]
    if role == "owner":
        rows.append([InlineKeyboardButton(text="👥 Админы", callback_data="admin:list")])
    rows.append([InlineKeyboardButton(text="🩺 Проверка системы", callback_data="health")])
    return kb(rows)


def back_main():
    return kb([[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu")]])


def cancel_flow():
    return kb([[InlineKeyboardButton(text="❌ Отмена", callback_data="flow:cancel")]])


def content_collect_done(kind: str, count: int):
    callback = "campaign:content_done" if kind == "campaign" else "template:content_done"
    return kb([
        [InlineKeyboardButton(text=f"✅ Готово · сообщений: {count}", callback_data=callback)],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="flow:cancel")],
    ])


def target_menu(tags: list[str]):
    rows = [[InlineKeyboardButton(text="🌐 Все активные чаты", callback_data="target:all")]]
    for tag in tags[:20]:
        rows.append([InlineKeyboardButton(text=f"🏷 {tag}", callback_data=f"target:tag:{tag}")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="flow:cancel")])
    return kb(rows)


def schedule_menu():
    return kb([
        [InlineKeyboardButton(text="🚀 Сейчас", callback_data="schedule:now"), InlineKeyboardButton(text="⏱ Через 10 минут", callback_data="schedule:10")],
        [InlineKeyboardButton(text="🕒 Указать дату/время", callback_data="schedule:custom")],
        [InlineKeyboardButton(text="🔁 Повторять по интервалу", callback_data="schedule:repeat")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="flow:cancel")],
    ])


def campaign_confirm():
    return kb([
        [InlineKeyboardButton(text="🔗 CTA-кнопка", callback_data="campaign:button"), InlineKeyboardButton(text="🧪 Тест себе", callback_data="campaign:test")],
        [InlineKeyboardButton(text="✅ Создать кампанию", callback_data="campaign:confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="flow:cancel")],
    ])


def campaign_controls(campaign_id: int, status: str):
    rows = []
    if status in {"scheduled", "running"}:
        rows.append([
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"campaign:pause:{campaign_id}"),
            InlineKeyboardButton(text="🛑 Стоп", callback_data=f"campaign:stop:{campaign_id}"),
        ])
    elif status == "paused":
        rows.append([
            InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"campaign:resume:{campaign_id}"),
            InlineKeyboardButton(text="🛑 Стоп", callback_data=f"campaign:stop:{campaign_id}"),
        ])
    elif status in {"completed", "failed", "canceled"}:
        rows.append([InlineKeyboardButton(text="🔁 Повторить сейчас", callback_data=f"campaign:rerun:{campaign_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Кампании", callback_data="campaign:list")])
    return kb(rows)


def chats_menu(chats):
    rows = [[InlineKeyboardButton(text="➕ Добавить чат", callback_data="chat:add")]]
    for c in chats[:30]:
        icon = "✅" if c.enabled else "⛔"
        rows.append([InlineKeyboardButton(text=f"{icon} {c.title[:34]}", callback_data=f"chat:view:{c.chat_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu")])
    return kb(rows)


def chat_controls(chat_id: int, enabled: bool):
    toggle = "⛔ Выключить" if enabled else "✅ Включить"
    return kb([
        [InlineKeyboardButton(text=toggle, callback_data=f"chat:toggle:{chat_id}")],
        [InlineKeyboardButton(text="🏷 Изменить теги", callback_data=f"chat:tags:{chat_id}"), InlineKeyboardButton(text="🩺 Проверить права", callback_data=f"chat:check:{chat_id}")],
        [InlineKeyboardButton(text="⬅️ Чаты", callback_data="chat:list")],
    ])


def templates_menu(templates):
    rows = [[InlineKeyboardButton(text="➕ Новый шаблон", callback_data="template:new")]]
    for t in templates[:20]:
        rows.append([
            InlineKeyboardButton(text=f"🧩 {t.name[:28]}", callback_data=f"template:view:{t.id}"),
            InlineKeyboardButton(text="📣", callback_data=f"template:use:{t.id}"),
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu")])
    return kb(rows)


def template_controls(template_id: int):
    return kb([
        [InlineKeyboardButton(text="📣 Создать рассылку", callback_data=f"template:use:{template_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"template:delete:{template_id}")],
        [InlineKeyboardButton(text="⬅️ Шаблоны", callback_data="template:list")],
    ])


def admins_menu(admins):
    rows = [[InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin:add")]]
    for a in admins:
        rows.append([InlineKeyboardButton(text=f"{a.role.upper()} · {a.user_id}", callback_data=f"admin:view:{a.user_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu")])
    return kb(rows)


def admin_roles(user_id: int):
    return kb([
        [InlineKeyboardButton(text="🛡 Admin", callback_data=f"admin:role:{user_id}:admin")],
        [InlineKeyboardButton(text="✍️ Editor", callback_data=f"admin:role:{user_id}:editor")],
        [InlineKeyboardButton(text="👁 Viewer", callback_data=f"admin:role:{user_id}:viewer")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:list")],
    ])


def admin_controls(user_id: int, role: str):
    rows = []
    if role != "owner":
        rows.append([InlineKeyboardButton(text="🔄 Сменить роль", callback_data=f"admin:changerole:{user_id}")])
        rows.append([InlineKeyboardButton(text="🗑 Удалить доступ", callback_data=f"admin:remove:{user_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Админы", callback_data="admin:list")])
    return kb(rows)
