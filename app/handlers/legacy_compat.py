from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from .public_panel import render_home

router = Router(name="legacy-compat")


@router.callback_query(
    F.data.startswith("campaign:")
    | F.data.startswith("template:")
    | F.data.startswith("chat:")
    | F.data.startswith("admin:")
    | (F.data == "stats")
    | (F.data == "health")
    | (F.data == "menu")
)
async def legacy_button_redirect(call: CallbackQuery, state: FSMContext):
    """Redirect buttons left in chats by the old admin-panel version."""
    await render_home(call, state)
