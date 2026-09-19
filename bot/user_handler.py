from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bot.update import Update

if TYPE_CHECKING:
    from bot import ModeratorService, TelegramApi, TicketService

# Логотип компании для приветствия
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


class UserHandler:
    """Обрабатывает сообщения обычных пользователей."""

    def __init__(
        self,
        api: "TelegramApi",
        tickets: "TicketService",
        moderators: "ModeratorService",
    ) -> None:
        self._api = api
        self._tickets = tickets
        self._moderators = moderators

    def handle(self, update: Update) -> None:
        # Нажатие кнопки от не-модератора (старое/поддельное сообщение) — игнорируем
        if update.callback_query_id is not None:
            return

        text = update.text.strip()

        if text in ("/start", "/help"):
            caption = (
                "👷 Добро пожаловать в техподдержку «ИТМеханизатор»!\n"
                "\n"
                "Как обратиться к нам:\n"
                "1. Просто напишите сюда описание проблемы — мы её увидим.\n"
                "2. /ticket — создать заявку с описанием\n"
                "3. /status — статус вашей последней заявки\n"
                "4. /faq — частые вопросы"
            )
            if _LOGO_PATH.exists():
                self._api.send_photo(
                    update.chat_id,
                    _LOGO_PATH,
                    "🛠 ИТМеханизатор — Support\n\n" + caption,
                )
            else:
                self._api.send_message(update.chat_id, caption,
                                       reply_buttons=[["📝 Заявка", "📊 Статус", "❓ FAQ"]])
                return
            self._api.send_message(
                update.chat_id,
                "Выберите действие или просто напишите вашу проблему:",
                reply_buttons=[["📝 Заявка", "📊 Статус", "❓ FAQ"]],
            )
            return

        if text in ("❓ FAQ", "/faq"):
            self._send(update.chat_id, (
                "❓ Частые вопросы:\n"
                "\n"
                "1. Не запускается приложение — попробуйте очистить кэш и перезапустить.\n"
                "2. Не приходят уведомления — проверьте разрешения в настройках телефона.\n"
                "3. Ошибка входа — убедитесь, что используете актуальный логин и пароль.\n"
                "\n"
                "Не помогло? Нажмите «📝 Заявка» и опишите проблему."
            ))
            return

        if text in ("📝 Заявка", "/ticket"):
            self._send(update.chat_id, (
                "📝 Опишите вашу проблему одним сообщением — я создам заявку, "
                "и оператор скоро ответит вам здесь."
            ))
            return

        if text in ("📊 Статус", "/status"):
            last = self._find_last_user_ticket(update.user_id)
            if last is None:
                self._send(update.chat_id, "У вас пока нет заявок. Нажмите «📝 Заявка» или просто напишите нам.")
            else:
                status = "🟡 в работе" if last.status == "NEW" else "✅ закрыта"
                self._send(update.chat_id, f"Ваша заявка #{last.id} — {status}\n\nТекст: {last.text}")
            return

        if text.startswith("/ticket "):
            description = text[len("/ticket"):].strip()
            self._create_ticket(update, description)
            return

        # Любое другое сообщение — это тоже заявка
        self._create_ticket(update, text)

    def _find_last_user_ticket(self, user_id: int):
        last = None
        for ticket in self._tickets.find_new():
            if ticket.user_id == user_id:
                last = ticket
        if last is not None:
            return last
        # Если открытых нет, ищем последнюю закрытую
        for ticket in self._tickets.get_all():
            if ticket.user_id == user_id:
                last = ticket
        return last

    def _create_ticket(self, update: Update, description: str) -> None:
        ticket = self._tickets.create(update.user_id, update.user_name, description)
        self._send(update.chat_id, f"✅ Заявка #{ticket.id} создана. Оператор скоро ответит вам здесь.")

        # Уведомляем всех модераторов с кнопками действий
        notice = (
            f"🔔 Новая заявка #{ticket.id} от {update.user_name}\n"
            f"\n"
            f"{description}"
        )
        buttons = [[
            {"text": "💬 Ответить", "callback_data": f"mod:answer:{ticket.id}"},
            {"text": "✅ Закрыть", "callback_data": f"mod:close:{ticket.id}"},
        ]]
        for moderator_id in self._moderators.get_all():
            self._api.send_message(moderator_id, notice, buttons)

    def _send(self, chat_id: int, text: str) -> None:
        self._api.send_message(chat_id, text)
