from aiogram.fsm.state import State, StatesGroup


class CampaignFlow(StatesGroup):
    waiting_name = State()
    waiting_message = State()
    choosing_target = State()
    choosing_schedule = State()
    waiting_datetime = State()
    waiting_repeat_minutes = State()
    waiting_button = State()
    confirming = State()


class AddChatFlow(StatesGroup):
    waiting_chat_id = State()


class TagChatFlow(StatesGroup):
    waiting_tags = State()


class AdminFlow(StatesGroup):
    waiting_user_id = State()
    waiting_role = State()


class TemplateFlow(StatesGroup):
    waiting_name = State()
    waiting_message = State()
