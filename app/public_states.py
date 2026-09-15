from aiogram.fsm.state import State, StatesGroup


class LoginFlow(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()


class CampaignWizard(StatesGroup):
    choosing_account = State()
    choosing_source = State()
    choosing_targets = State()
    waiting_name = State()
    choosing_schedule = State()
    waiting_interval = State()
    waiting_datetime = State()
    confirming = State()
