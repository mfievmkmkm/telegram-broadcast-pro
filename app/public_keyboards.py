from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def home_kb():
    return kb([
        [InlineKeyboardButton(text="👤 Аккаунты", callback_data="pub:accounts"), InlineKeyboardButton(text="🎯 Получатели", callback_data="pub:targets")],
        [InlineKeyboardButton(text="📣 Новая рассылка", callback_data="pub:new")],
        [InlineKeyboardButton(text="🗓 Мои рассылки", callback_data="pub:campaigns"), InlineKeyboardButton(text="📊 Статистика", callback_data="pub:stats")],
        [InlineKeyboardButton(text="ℹ️ Как работает", callback_data="pub:help")],
    ])


def back_home():
    return kb([[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="pub:home")]])


def accounts_kb(accounts):
    rows = [[InlineKeyboardButton(text="➕ Подключить аккаунт", callback_data="acct:add")]]
    for a in accounts[:20]:
        label = f"@{a.username}" if a.username else (a.first_name or str(a.tg_user_id))
        rows.append([InlineKeyboardButton(text=f"👤 {label}", callback_data=f"acct:view:{a.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="pub:home")])
    return kb(rows)


def login_method_kb():
    return kb([
        [InlineKeyboardButton(text="▦ Войти по QR", callback_data="login:qr")],
        [InlineKeyboardButton(text="📱 По номеру и коду", callback_data="login:phone")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="login:cancel")],
    ])


def qr_kb():
    return kb([
        [InlineKeyboardButton(text="✅ Я отсканировал", callback_data="login:qr:check")],
        [InlineKeyboardButton(text="🔄 Новый QR", callback_data="login:qr:refresh")],
    ])


def code_keypad(code_len: int):
    rows = []
    for row in ((1,2,3),(4,5,6),(7,8,9)):
        rows.append([InlineKeyboardButton(text=str(x), callback_data=f"login:digit:{x}") for x in row])
    rows.append([
        InlineKeyboardButton(text="⌫", callback_data="login:digit:back"),
        InlineKeyboardButton(text="0", callback_data="login:digit:0"),
        InlineKeyboardButton(text="✅", callback_data="login:digit:ok"),
    ])
    rows.append([InlineKeyboardButton(text=f"Введено: {code_len}", callback_data="login:noop")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="login:cancel")])
    return kb(rows)


def account_view_kb(account_id: int):
    return kb([
        [InlineKeyboardButton(text="🩺 Проверить", callback_data=f"acct:check:{account_id}"), InlineKeyboardButton(text="🎯 Чаты", callback_data=f"acct:targets:{account_id}")],
        [InlineKeyboardButton(text="📣 Рассылка с этого аккаунта", callback_data=f"acct:new:{account_id}")],
        [InlineKeyboardButton(text="🗑 Отключить аккаунт", callback_data=f"acct:unlink:{account_id}")],
        [InlineKeyboardButton(text="⬅️ Аккаунты", callback_data="pub:accounts")],
    ])


def choose_account_kb(accounts, prefix: str):
    rows = []
    for a in accounts[:20]:
        label = f"@{a.username}" if a.username else (a.first_name or str(a.tg_user_id))
        rows.append([InlineKeyboardButton(text=f"👤 {label}", callback_data=f"{prefix}:{a.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="pub:home")])
    return kb(rows)


def targets_kb(targets, account_id: int):
    rows = [[InlineKeyboardButton(text="➕ Добавить из моих чатов", callback_data=f"target:dialogs:{account_id}:0")]]
    for t in targets[:30]:
        icon = "✅" if t.enabled else "⛔"
        rows.append([InlineKeyboardButton(text=f"{icon} {t.title[:34]}", callback_data=f"target:toggle:{t.id}:{account_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Аккаунт", callback_data=f"acct:view:{account_id}")])
    return kb(rows)


def dialog_picker_kb(items, account_id: int, added_keys: set[tuple[str,int]], page: int, per_page: int = 10):
    start = page * per_page
    chunk = items[start:start + per_page]
    rows = []
    for d in chunk:
        key = (d.peer_kind, d.peer_id)
        icon = "✅" if key in added_keys else ("📢" if d.is_channel else "👥")
        rows.append([InlineKeyboardButton(text=f"{icon} {d.title[:32]}", callback_data=f"target:add:{account_id}:{d.peer_kind}:{d.peer_id}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"target:dialogs:{account_id}:{page-1}"))
    if start + per_page < len(items):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"target:dialogs:{account_id}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="✅ Готово", callback_data=f"acct:targets:{account_id}")])
    return kb(rows)


def source_kb(account_id: int):
    return kb([
        [InlineKeyboardButton(text="📥 Забрать последнее из Избранного", callback_data=f"wiz:source:{account_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="pub:home")],
    ])


def target_mode_kb(account_id: int):
    return kb([
        [InlineKeyboardButton(text="🌐 Все активные получатели", callback_data=f"wiz:targets:all:{account_id}")],
        [InlineKeyboardButton(text="🎯 Выбрать вручную", callback_data=f"wiz:targets:pick:{account_id}:0")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="pub:home")],
    ])


def target_select_kb(targets, selected: set[int], account_id: int, page: int, per_page: int = 10):
    start = page * per_page
    chunk = targets[start:start + per_page]
    rows = []
    for t in chunk:
        icon = "✅" if t.id in selected else "▫️"
        rows.append([InlineKeyboardButton(text=f"{icon} {t.title[:32]}", callback_data=f"wiz:target:toggle:{account_id}:{t.id}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"wiz:targets:pick:{account_id}:{page-1}"))
    if start + per_page < len(targets):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"wiz:targets:pick:{account_id}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=f"✅ Готово · {len(selected)}", callback_data=f"wiz:targets:done:{account_id}")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="pub:home")])
    return kb(rows)


def schedule_kb():
    return kb([
        [InlineKeyboardButton(text="🚀 Один раз сейчас", callback_data="wiz:schedule:now")],
        [InlineKeyboardButton(text="🔁 Каждые 15 мин", callback_data="wiz:schedule:15"), InlineKeyboardButton(text="🔁 30 мин", callback_data="wiz:schedule:30")],
        [InlineKeyboardButton(text="🔁 1 час", callback_data="wiz:schedule:60"), InlineKeyboardButton(text="🔁 2 часа", callback_data="wiz:schedule:120")],
        [InlineKeyboardButton(text="⚙️ Свой интервал", callback_data="wiz:schedule:custom"), InlineKeyboardButton(text="🕒 По времени", callback_data="wiz:schedule:datetime")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="pub:home")],
    ])


def confirm_kb():
    return kb([
        [InlineKeyboardButton(text="🧪 Тест в Избранное", callback_data="wiz:test")],
        [InlineKeyboardButton(text="🚀 Запустить", callback_data="wiz:launch")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="pub:home")],
    ])


def campaigns_kb(items):
    rows = []
    icons = {"scheduled":"🗓", "active":"🔁", "running":"🚀", "paused":"⏸", "completed":"✅", "stopped":"🛑", "failed":"❌"}
    for c in items[:20]:
        rows.append([InlineKeyboardButton(text=f"{icons.get(c.status,'•')} #{c.id} {c.name[:30]}", callback_data=f"camp:view:{c.id}")])
    rows.append([InlineKeyboardButton(text="➕ Новая рассылка", callback_data="pub:new")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="pub:home")])
    return kb(rows)


def campaign_view_kb(campaign_id: int, status: str):
    rows = []
    if status in {"scheduled", "active", "running"}:
        rows.append([InlineKeyboardButton(text="⏸ Пауза", callback_data=f"camp:pause:{campaign_id}"), InlineKeyboardButton(text="🛑 Стоп", callback_data=f"camp:stop:{campaign_id}")])
    elif status == "paused":
        rows.append([InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"camp:resume:{campaign_id}"), InlineKeyboardButton(text="🛑 Стоп", callback_data=f"camp:stop:{campaign_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Рассылки", callback_data="pub:campaigns")])
    return kb(rows)
