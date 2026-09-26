"""Кнопки для бота техподдержки в Telegram.

В телеграм-боте есть два вида кнопок:
- inline ({"text": ..., "callback_data": ...}) — под сообщением модераторам;
- reply-кнопки в поле ввода — постоянная клавиатура чата (для пользователей:
  их callback-нажатия бот игнорирует, поэтому им нужны кнопки-сообщения).
"""

# Reply-клавиатура пользователя: кнопки отправляют свой текст сообщением
USER_BUTTONS = [["📝 Заявка", "📊 Статус", "❓ FAQ"]]


def menu_row() -> list[dict]:
    """Ряд главных кнопок — добавляется внизу клавиатур модератора,
    чтобы «Открытые заявки» и «Модераторы» всегда были под рукой."""
    return [
        {"text": "📋 Открытые заявки", "callback_data": "mod:list"},
        {"text": "🛠 Модераторы", "callback_data": "mod:mods"},
    ]


def with_menu(buttons: list[list[dict]]) -> list[list[dict]]:
    """Добавляет ряд главных кнопок внизу клавиатуры (если его там ещё нет)."""
    if buttons and buttons[-1] == menu_row():
        return buttons
    return buttons + [menu_row()]


def menu_keyboard() -> list[list[dict]]:
    """Кнопки меню модератора под сообщением."""
    return [menu_row()]


def status_button() -> list[list[str]]:
    """Кнопка «Статус» — reply-клавиатура к сообщениям модератора пользователю."""
    return [["📊 Статус"]]


def closed_ticket_buttons() -> list[list[str]]:
    """Кнопки к уведомлению о закрытии заявки: новая заявка + статус."""
    return [["📝 Заявка", "📊 Статус"]]


def ticket_keyboard(ticket_id: int) -> list[list[dict]]:
    return with_menu([
        [
            {"text": "💬 Ответить", "callback_data": f"mod:answer:{ticket_id}"},
            {"text": "✅ Закрыть", "callback_data": f"mod:close:{ticket_id}"},
        ],
    ])


def cancel_button(ticket_id: int) -> list[list[dict]]:
    """Промпт «Напишите ответ» — только надпись, без кнопок.

    Отменить ввод можно командой /mod или /cancel.
    """
    return []


def refresh_button() -> list[list[dict]]:
    return with_menu([[{"text": "🔄 Обновить", "callback_data": "mod:list"}]])


def remove_moderator_button(user_id: int) -> list[list[dict]]:
    return with_menu([[
        {"text": "🗑 Удалить", "callback_data": f"mod:remove:{user_id}"},
    ]])


def add_moderator_button() -> list[list[dict]]:
    return with_menu([[{"text": "➕ Добавить модератора", "callback_data": "mod:add"}]])