"""Тесты телеграм-бота: пользователи, модераторы, кнопки, заявки, парсинг API."""
from __future__ import annotations

import io
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from bot.mod_handler import ModHandler
from bot.moderator_service import ModeratorService
from bot.ticket_service import TicketService
from bot.update import Update
from bot.user_handler import UserHandler


# --- Фейки ---

@dataclass
class Sent:
    chat_id: int
    text: str
    buttons: object
    reply_buttons: object


class FakeApi:
    """Запоминает все отправленные сообщения вместо реального Telegram."""

    def __init__(self) -> None:
        self.sent: list[Sent] = []
        self.deleted: list[tuple] = []
        self.callback_answers: list[int] = []
        self.photos: list[tuple] = []
        self._next_id = 1

    def send_message(self, chat_id, text, buttons=None, reply_buttons=None):
        self.sent.append(Sent(chat_id, text, buttons, reply_buttons))
        message_id = self._next_id
        self._next_id += 1
        return message_id

    def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))
        return True

    def send_message_to_all(self, chat_ids, text, buttons=None):
        for chat_id in chat_ids:
            self.send_message(chat_id, text, buttons)

    def answer_callback(self, callback_query_id):
        self.callback_answers.append(callback_query_id)

    def send_photo(self, chat_id, photo_path, caption=""):
        self.photos.append((chat_id, str(photo_path), caption))

    def to(self, chat_id: int) -> list[Sent]:
        return [s for s in self.sent if s.chat_id == chat_id]

    def texts(self, chat_id: int) -> list[str]:
        return [s.text for s in self.to(chat_id)]


class FakeConfig:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.bot_token = "TEST"
        self.operator_id = None


def make_update(update_id, user_id, text, chat_id=None, callback_query_id=None, callback_data=""):
    return Update(
        update_id=update_id,
        chat_id=chat_id or user_id,
        user_id=user_id,
        user_name="Тест",
        text=text,
        callback_query_id=callback_query_id,
        callback_data=callback_data,
    )


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.api = FakeApi()
        self.config = FakeConfig(self.data_dir)
        self.tickets = TicketService(self.config)
        self.moderators = ModeratorService(self.config)
        self.moderators.add(100)
        self.users = UserHandler(self.api, self.tickets, self.moderators)
        self.mods = ModHandler(self.api, self.tickets, self.moderators)

    def tearDown(self):
        self.tmp.cleanup()

    def press(self, data: str, user_id: int = 100, qid: int = 1):
        """Нажатие inline-кнопки."""
        self.mods.handle(make_update(999, user_id, "", callback_query_id=qid, callback_data=data))

    def say(self, text: str, user_id: int = 100):
        """Текстовое сообщение."""
        if self.moderators.is_moderator(user_id):
            self.mods.handle(make_update(999, user_id, text))
        else:
            self.users.handle(make_update(999, user_id, text))


# --- Тесты пользователя ---

class TestUserHandler(BaseTest):
    def test_start_shows_logo_and_buttons(self):
        self.say("/start", user_id=200)
        # Приветствие с логотипом и подписью Support
        self.assertIn("ИТМеханизатор — Support", self.api.photos[0][2])
        buttons_msg = [s for s in self.api.sent if s.reply_buttons]
        self.assertEqual(buttons_msg[0].reply_buttons, [["📝 Заявка", "📊 Статус", "❓ FAQ"]])

    def test_start_without_logo_falls_back_to_text(self):
        from bot import user_handler
        with patch.object(user_handler, "_LOGO_PATH", Path("нет_такого.png")):
            self.say("/start", user_id=200)
        msg = self.api.to(200)[0]
        self.assertIn("ИТМеханизатор — Support", msg.text)
        self.assertEqual(msg.reply_buttons, [["📝 Заявка", "📊 Статус", "❓ FAQ"]])

    def test_myid_command(self):
        self.say("/myid", user_id=200)
        self.assertIn("Ваш ID в Telegram: 200", self.api.texts(200)[0])

    def test_faq_button(self):
        self.say("❓ FAQ", user_id=200)
        self.assertIn("Частые вопросы", self.api.texts(200)[0])

    def test_ticket_button_asks_description(self):
        self.say("📝 Заявка", user_id=200)
        self.assertIn("Опишите", self.api.texts(200)[0])

    def test_status_no_tickets(self):
        self.say("📊 Статус", user_id=200)
        self.assertIn("нет заявок", self.api.texts(200)[0])

    def test_plain_text_does_not_create_ticket(self):
        # Заявка создаётся только после нажатия кнопки «📝 Заявка»
        self.say("не работает вход", user_id=200)
        self.assertEqual(self.tickets.get_all(), [])
        self.assertIn("нажмите кнопку", self.api.texts(200)[0].lower())

    def test_ticket_flow_separate_messages(self):
        # Гибрид: каждое событие по заявке — отдельное сообщение у модератора
        self.say("📝 Заявка", user_id=200)
        self.say("проблема А", user_id=200)
        notice = self.api.to(100)[0]
        self.assertIn("Новая заявка #1", notice.text)
        self.assertIn("проблема А", notice.text)
        self.assertEqual(notice.buttons[0][0]["callback_data"], "mod:answer:1")

        # Ответ модератора: пользователь получает ответ, автор — подтверждение
        self.press("mod:answer:1")
        self.api.sent.clear()  # промпт «Напишите ответ» — служебное
        self.say("вот решение")
        self.assertIn("Ответ поддержки по заявке #1", self.api.texts(200)[0])
        self.assertIn("Ответ отправлен автору заявки #1", self.api.texts(100)[-1])

        # Ответ пользователя — отдельное сообщение только назначенному модератору
        self.say("спасибо, помогло", user_id=200)
        reply = [s for s in self.api.to(100) if "Ответ пользователя" in s.text][0]
        self.assertIn("спасибо, помогло", reply.text)
        self.assertEqual(reply.buttons[0][0]["callback_data"], "mod:answer:1")

    def test_mod_answer_not_broadcast_to_other_mods(self):
        # Ответ модератора уходит только пользователю и автору —
        # другим модераторам ничего не приходит (диалог один-на-один)
        self.moderators.add(300)
        self.say("📝 Заявка", user_id=200)
        self.say("проблема А", user_id=200)
        self.api.sent.clear()
        self.press("mod:answer:1")
        self.say("вот решение")
        self.assertEqual(self.api.to(300), [])
        # Автор получил подтверждение отправки, а не дубль ответа
        self.assertIn("Ответ отправлен автору заявки #1", self.api.texts(100)[-1])

    def test_empty_text_does_not_create_ticket(self):
        # Пустой текст отфильтровывается в Bot._handle, а обработчик
        # на всякий случай просит описание, но заявку не создаёт
        self.say("", user_id=200)
        self.assertEqual(self.tickets.get_all(), [])

    def test_status_after_ticket(self):
        self.say("📝 Заявка", user_id=200)
        self.say("не работает вход", user_id=200)
        self.say("📊 Статус", user_id=200)
        self.assertIn("в работе", self.api.texts(200)[-1])

    def test_status_closed_ticket(self):
        self.say("📝 Заявка", user_id=200)
        self.say("не работает вход", user_id=200)
        self.tickets.close(1)
        self.say("📊 Статус", user_id=200)
        self.assertIn("закрыта", self.api.texts(200)[-1])

    def test_start_after_closed_ticket_mentions_it(self):
        # /start после закрытия заявки напоминает о закрытии
        self.say("📝 Заявка", user_id=200)
        self.say("не работает вход", user_id=200)
        self.tickets.close(1)
        self.say("/start", user_id=200)
        self.assertIn("заявка #1 закрыта", self.api.photos[0][2].lower())
        self.assertIn("создайте новую заявку", self.api.photos[0][2])

    def test_start_without_tickets_no_closed_notice(self):
        # Без заявок напоминания о закрытии нет
        self.say("/start", user_id=200)
        self.assertNotIn("закрыта", self.api.photos[0][2].lower())

    def test_user_callback_ignored(self):
        # Не-модератор нажал старую/поддельную кнопку — заявка не создаётся
        self.users.handle(make_update(999, 200, "", callback_query_id=5, callback_data="mod:close:1"))
        self.assertEqual(self.api.to(200), [])
        self.assertEqual(self.tickets.get_all(), [])

    def test_user_reply_without_mod_answer_rejected(self):
        # Пока модератор не ответил, сообщения пользователя в диалог не попадают
        self.say("📝 Заявка", user_id=200)
        self.say("проблема А", user_id=200)
        self.api.sent.clear()
        self.say("уточнение", user_id=200)
        self.assertEqual(self.tickets.find_by_id(1).messages, [])
        self.assertEqual(self.api.to(100), [])
        self.assertIn("нажмите кнопку", self.api.texts(200)[0].lower())

    def test_user_reply_after_mod_answer_goes_to_ticket(self):
        # После ответа модератора пользователь пишет в ту же заявку —
        # ответ уходит только назначенному модератору
        self.moderators.add(300)
        self.say("📝 Заявка", user_id=200)
        self.say("проблема А", user_id=200)
        self.press("mod:answer:1", user_id=100)
        self.say("вот решение", user_id=100)
        self.api.sent.clear()
        self.say("спасибо, помогло", user_id=200)
        ticket = self.tickets.find_by_id(1)
        self.assertEqual(len(ticket.messages), 2)
        self.assertEqual(ticket.messages[1]["author"], "user")
        self.assertEqual(ticket.messages[1]["text"], "спасибо, помогло")
        # Ответ пришёл только назначенному модератору 100
        reply = self.api.to(100)[0]
        self.assertIn("спасибо, помогло", reply.text)
        self.assertEqual(reply.buttons[0][0]["callback_data"], "mod:answer:1")
        # Другой модератор не получает переписку
        self.assertEqual(self.api.to(300), [])

    def test_user_reply_without_assignee_broadcast(self):
        # Заявка не закреплена — ответ пользователя уходит всем модераторам
        self.moderators.add(300)
        self.say("📝 Заявка", user_id=200)
        self.say("проблема А", user_id=200)
        # назначаем без режима ответа: модератор взял и тут же ответил
        self.tickets.assign(1, 100)
        self.tickets.release(1)
        self.api.sent.clear()
        # Пользователь не может писать до ответа модератора — имитируем диалог
        self.press("mod:answer:1", user_id=100)
        self.say("вот решение", user_id=100)
        self.api.sent.clear()
        self.say("спасибо", user_id=200)
        self.assertIn("спасибо", self.api.texts(100)[0])

    def test_pending_ticket_reset_by_dialog_reply(self):
        # Нажал «Заявка», но написал в существующий диалог —
        # режим ввода описания сбрасывается, лишняя заявка не создаётся
        self.say("📝 Заявка", user_id=200)
        self.say("проблема А", user_id=200)
        self.press("mod:answer:1")
        self.say("вот решение")
        self.say("📝 Заявка", user_id=200)  # случайно нажал снова
        self.say("уточнение по проблеме", user_id=200)
        # Сообщение ушло в диалог, а не создало заявку #2
        self.assertEqual(len(self.tickets.get_all()), 1)
        ticket = self.tickets.find_by_id(1)
        self.assertEqual(ticket.messages[-1]["text"], "уточнение по проблеме")
        self.api.sent.clear()
        self.say("ещё сообщение", user_id=200)
        # Режим ввода сброшен — второе сообщение не создаёт заявку
        self.assertEqual(len(self.tickets.get_all()), 1)

    def test_user_reply_after_ticket_closed_rejected(self):
        # После закрытия заявки диалог недоступен
        self.say("📝 Заявка", user_id=200)
        self.say("проблема А", user_id=200)
        self.press("mod:answer:1")
        self.say("вот решение")
        self.press("mod:close:1")
        self.api.sent.clear()
        self.say("ещё вопрос", user_id=200)
        self.assertEqual(self.api.to(100), [])
        self.assertIn("нажмите кнопку", self.api.texts(200)[0].lower())

    def test_user_second_reply_blocked_until_mod_answers(self):
        # После отправки ответа пользователь не может писать, пока не ответит модератор
        self.say("📝 Заявка", user_id=200)
        self.say("проблема А", user_id=200)
        self.press("mod:answer:1")
        self.say("вот решение")
        self.say("первый ответ", user_id=200)
        self.api.sent.clear()
        self.say("второе сообщение", user_id=200)
        # Сообщение не ушло модераторам и в диалог не записано
        self.assertEqual(self.api.to(100), [])
        ticket = self.tickets.find_by_id(1)
        self.assertEqual(len(ticket.messages), 2)
        self.assertIn("Ждите ответ оператора", self.api.texts(200)[0])
        # После нового ответа модератора пользователь снова может писать
        self.press("mod:answer:1")
        self.say("уточнение")
        self.api.sent.clear()
        self.say("ответ после ответа модератора", user_id=200)
        ticket = self.tickets.find_by_id(1)
        self.assertEqual(ticket.messages[-1]["author"], "user")
        reply = self.api.to(100)[0]
        self.assertIn("ответ после ответа модератора", reply.text)


# --- Тесты модератора: команды ---

class TestModCommands(BaseTest):
    def test_mod_opens_menu(self):
        self.say("/mod")
        msg = self.api.to(100)[0]
        self.assertIn("Меню модератора", msg.text)
        datas = [b["callback_data"] for row in msg.buttons for b in row]
        self.assertIn("mod:list", datas)
        self.assertIn("mod:mods", datas)

    def test_menu_button_opens_menu(self):
        self.say("🛠 Меню")
        self.assertIn("Меню модератора", self.api.texts(100)[0])

    def test_start_shows_logo_for_moderator(self):
        self.say("/start")
        self.assertIn("ИТМеханизатор — Support", self.api.photos[0][2])
        self.assertIn("модератора", self.api.photos[0][2])

    def test_myid_for_moderator(self):
        self.say("/myid")
        self.assertIn("Ваш ID в Telegram: 100", self.api.texts(100)[0])

    def test_unknown_text_shows_menu(self):
        self.say("абракадабра")
        self.assertIn("Не понял сообщение", self.api.texts(100)[0])
        self.assertIsNotNone(self.api.to(100)[0].buttons)

    def test_list_empty(self):
        self.press("mod:list")
        self.assertIn("Открытых заявок нет", self.api.texts(100)[0])

    def test_list_shows_tickets_with_buttons(self):
        self.say("📝 Заявка", user_id=200)
        self.say("проблема А", user_id=200)
        self.api.sent.clear()
        self.press("mod:list")
        self.assertIn("Открытые заявки: 1", self.api.texts(100)[0])
        ticket_msg = self.api.to(100)[1]
        self.assertIn("проблема А", ticket_msg.text)
        self.assertEqual(ticket_msg.buttons[0][0]["callback_data"], "mod:answer:1")


# --- Тесты модератора: кнопки ---

class TestModButtons(BaseTest):
    def setUp(self):
        super().setUp()
        self.say("📝 Заявка", user_id=200)
        self.say("проблема А", user_id=200)  # заявка #1 от пользователя 200
        self.api.sent.clear()

    def test_answer_flow(self):
        self.press("mod:answer:1")
        self.assertIn("Напишите ответ по заявке #1", self.api.texts(100)[0])
        self.say("вот решение")
        self.assertIn("Ответ поддержки по заявке #1", self.api.texts(200)[0])
        self.assertIn("вот решение", self.api.texts(200)[0])
        # Ответ модератора с reply-кнопкой «Статус» для пользователя
        status_msg = self.api.to(200)[0]
        self.assertEqual(status_msg.reply_buttons, [["📊 Статус"]])
        # Ответ модератора записан в диалог заявки
        ticket = self.tickets.find_by_id(1)
        self.assertEqual(ticket.messages[0]["author"], "mod")
        self.assertEqual(ticket.messages[0]["text"], "вот решение")
        # Автор получил подтверждение отправки, а не дубль ответа
        self.assertIn("Ответ отправлен автору заявки #1", self.api.texts(100)[-1])

    def test_close_notice_has_status_button(self):
        self.press("mod:close:1")
        close_msg = self.api.to(200)[0]
        self.assertIn("закрыта", close_msg.text)
        # Reply-кнопки: новая заявка + статус
        self.assertEqual(close_msg.reply_buttons, [["📝 Заявка", "📊 Статус"]])

    def test_close_not_broadcast_to_other_mods(self):
        # Закрытие заявки не рассылается другим модераторам
        self.moderators.add(300)
        self.press("mod:close:1")
        self.assertEqual(self.api.to(300), [])

    def test_answer_on_closed_ticket(self):
        self.tickets.close(1)
        self.press("mod:answer:1")
        self.assertIn("не найдена или уже закрыта", self.api.texts(100)[0])

    def test_answer_text_on_closed_ticket_not_sent(self):
        # Режим ответа активен, но заявку закрыл другой модератор
        self.press("mod:answer:1")
        self.tickets.close(1)
        self.say("вот решение")
        self.assertIn("уже закрыта — ответ не отправлен", self.api.texts(100)[-1])
        self.assertEqual(self.api.to(200), [])

    def test_close_flow(self):
        self.press("mod:close:1")
        self.assertEqual(self.tickets.find_by_id(1).status, "CLOSED")
        self.assertIn("закрыта", self.api.texts(200)[0])

    def test_double_close_no_duplicate_notice(self):
        self.press("mod:close:1")
        self.api.sent.clear()
        self.press("mod:close:1")
        self.assertIn("уже закрыта", self.api.texts(100)[0])
        # Автору не ушло повторное уведомление о закрытии
        self.assertEqual(self.api.to(200), [])

    def test_close_after_answer_button(self):
        self.press("mod:answer:1")
        self.say("вот решение")
        self.press("mod:close:1")
        self.assertEqual(self.tickets.find_by_id(1).status, "CLOSED")

    def test_second_mod_cannot_take_taken_ticket(self):
        # Пока один модератор печатает ответ, другой не может взять заявку
        self.moderators.add(300)
        self.press("mod:answer:1", user_id=100)
        self.press("mod:answer:1", user_id=300)
        self.assertIn("уже ведёт", self.api.texts(300)[0])
        # Модератор 100 всё ещё может ответить
        self.say("вот решение", user_id=100)
        self.assertIn("Ответ поддержки по заявке #1", self.api.texts(200)[0])

    def test_ticket_stays_assigned_after_answer(self):
        # После отправки ответа заявка остаётся за модератором —
        # он ведёт диалог до закрытия (один-на-один)
        self.moderators.add(300)
        self.press("mod:answer:1", user_id=100)
        self.say("вот решение", user_id=100)
        self.assertEqual(self.tickets.get_assignee(1), 100)
        self.press("mod:answer:1", user_id=300)
        self.assertIn("уже ведёт", self.api.texts(300)[0])
        # Назначенный модератор продолжает диалог без промпта:
        # после ответа пользователя его текст уходит в заявку напрямую
        self.api.sent.clear()
        self.say("не помогло", user_id=200)
        self.assertIn("не помогло", self.api.texts(100)[0])
        self.api.sent.clear()
        self.say("уточнение по заявке", user_id=100)
        self.assertIn("уточнение по заявке", self.api.texts(200)[0])

    def test_ticket_released_on_cancel(self):
        # Отмена ввода освобождает заявку для другого модератора
        self.moderators.add(300)
        self.press("mod:answer:1", user_id=100)
        self.say("/cancel", user_id=100)
        self.press("mod:answer:1", user_id=300)
        self.assertIn("Напишите ответ по заявке #1", self.api.texts(300)[0])

    def test_same_mod_can_repress_answer(self):
        # Повторное нажатие «Ответить» тем же модератором не блокирует его
        self.press("mod:answer:1")
        self.press("mod:answer:1")
        self.say("вот решение")
        self.assertIn("Ответ поддержки по заявке #1", self.api.texts(200)[0])

    def test_close_releases_taken_ticket(self):
        # Закрытие заявки снимает закрепление у модератора, взявшего её
        self.press("mod:answer:1")
        self.press("mod:close:1")
        self.api.sent.clear()
        # Взявший заявку модератор пишет ответ — получает отказ, а не отправку
        self.say("вот решение")
        self.assertIn("Не понял сообщение", self.api.texts(100)[-1])
        self.assertEqual(self.api.to(200), [])
        self.assertIsNone(self.tickets.get_assignee(1))

    def test_unknown_ticket(self):
        self.press("mod:close:99")
        self.assertIn("не найдена", self.api.texts(100)[0])

    def test_unknown_button(self):
        self.press("mod:nonsense")
        self.assertIn("Неизвестная кнопка", self.api.texts(100)[0])

    def test_malformed_callback_data_not_crash(self):
        self.press("mod:answer:abc")
        self.assertIn("Некорректная кнопка", self.api.texts(100)[0])
        self.press("mod:close:xyz")
        self.assertIn("Некорректная кнопка", self.api.texts(100)[1])

    def test_callback_is_answered(self):
        self.press("mod:list", qid=42)
        self.assertIn(42, self.api.callback_answers)

    def test_answer_pending_cancelled_by_menu(self):
        self.press("mod:answer:1")
        self.say("🛠 Меню")  # открыл меню вместо ответа
        self.assertIn("Меню модератора", self.api.texts(100)[-1])
        # Режим ответа сброшен: следующее сообщение — не ответ
        self.api.sent.clear()
        self.say("просто текст")
        self.assertIn("Не понял сообщение", self.api.texts(100)[0])
        self.assertEqual(self.api.to(200), [])

    def test_answer_cancelled_by_cancel_command(self):
        self.press("mod:answer:1")
        self.say("/cancel")
        self.assertIn("Меню модератора", self.api.texts(100)[-1])
        self.api.sent.clear()
        self.say("просто текст")
        self.assertIn("Не понял сообщение", self.api.texts(100)[0])
        self.assertEqual(self.api.to(200), [])

    def test_answer_prompt_has_no_buttons(self):
        # Промпт «Напишите ответ» — только текст, без кнопок
        self.press("mod:answer:1")
        prompt = self.api.to(100)[0]
        self.assertIn("Напишите ответ по заявке #1", prompt.text)
        self.assertEqual(prompt.buttons, [])

    def test_answer_prompt_deleted_after_answer(self):
        # Промпт «Напишите ответ» удаляется после отправки ответа
        self.press("mod:answer:1")
        self.assertEqual(self.api.deleted, [])
        self.say("вот решение")
        self.assertEqual(len(self.api.deleted), 1)
        self.assertEqual(self.api.deleted[0][0], 100)

    def test_answer_prompt_deleted_on_cancel(self):
        # Промпт удаляется и при отмене режима ответа
        self.press("mod:answer:1")
        self.say("/cancel")
        self.assertEqual(len(self.api.deleted), 1)
        # Повторная отмена не пытается удалять уже удалённый промпт
        self.say("/cancel")
        self.assertEqual(len(self.api.deleted), 1)


# --- Тесты модераторов: добавление/удаление ---

class TestModeratorManagement(BaseTest):
    def test_mods_list_with_buttons(self):
        self.press("mod:mods")
        texts = self.api.texts(100)
        self.assertIn("Модераторы", texts[0])
        self.assertIn("100", texts[1])
        add_msg = self.api.to(100)[-1]
        self.assertEqual(add_msg.buttons[0][0]["callback_data"], "mod:add")

    def test_mods_list_goes_to_requester_chat(self):
        # Список модераторов приходит в чат запросившего, а не каждому модератору
        self.moderators.add(300)
        self.api.sent.clear()
        self.press("mod:mods")
        self.assertEqual(self.api.to(300), [])
        self.assertIn("100", self.api.texts(100)[1])

    def test_add_moderator_flow(self):
        self.press("mod:add")
        self.assertIn("Отправьте Telegram ID", self.api.texts(100)[0])
        self.say("300")
        self.assertIn("Модератор 300 добавлен", self.api.texts(100)[-1])
        self.assertTrue(self.moderators.is_moderator(300))

    def test_add_moderator_invalid_id_retries(self):
        self.press("mod:add")
        self.say("абракадабра")
        self.assertIn("ID должен быть числом", self.api.texts(100)[-1])
        self.say("400")
        self.assertIn("Модератор 400 добавлен", self.api.texts(100)[-1])

    def test_add_negative_moderator_rejected(self):
        self.press("mod:add")
        self.say("-999")
        self.assertIn("положительным числом", self.api.texts(100)[-1])
        self.assertEqual(self.moderators.get_all(), [100])

    def test_add_duplicate_moderator(self):
        self.press("mod:add")
        self.say("100")
        self.assertIn("уже модератор", self.api.texts(100)[-1])

    def test_remove_moderator(self):
        self.moderators.add(300)
        self.press("mod:remove:300")
        self.assertIn("Модератор 300 удалён", self.api.texts(100)[0])
        self.assertFalse(self.moderators.is_moderator(300))

    def test_remove_non_moderator(self):
        self.moderators.add(300)
        self.press("mod:remove:999")
        self.assertIn("не является модератором", self.api.texts(100)[0])

    def test_remove_last_moderator_forbidden(self):
        self.press("mod:remove:100")
        self.assertIn("последнего модератора", self.api.texts(100)[0])
        self.assertTrue(self.moderators.is_moderator(100))

    def test_remove_ok_when_two_mods(self):
        self.moderators.add(300)
        self.press("mod:remove:100")
        self.assertIn("Модератор 100 удалён", self.api.texts(100)[0])
        self.assertEqual(self.moderators.get_all(), [300])


# --- Тесты заявок ---

class TestTicketService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = FakeConfig(Path(self.tmp.name))
        self.svc = TicketService(self.config)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_ids_increment(self):
        t1 = self.svc.create(1, "А", "текст1")
        t2 = self.svc.create(2, "Б", "текст2")
        self.assertEqual((t1.id, t2.id), (1, 2))
        self.assertEqual(t1.status, "NEW")

    def test_persistence(self):
        self.svc.create(1, "А", "текст1")
        svc2 = TicketService(self.config)
        self.assertEqual(svc2.find_by_id(1).text, "текст1")

    def test_close_and_find_new(self):
        self.svc.create(1, "А", "текст1")
        self.svc.create(2, "Б", "текст2")
        self.svc.close(1)
        self.assertEqual([t.id for t in self.svc.find_new()], [2])
        self.svc.close(99)  # не падает

    def test_add_message_persists(self):
        t = self.svc.create(1, "А", "текст1")
        self.svc.add_message(t.id, "mod", "Мод", "ответ", sender_id=5)
        svc2 = TicketService(self.config)
        self.assertEqual(svc2.find_by_id(t.id).messages[0]["text"], "ответ")

    def test_find_last_open_by_user(self):
        self.svc.create(7, "А", "текст1")
        self.svc.create(7, "А", "текст2")
        self.svc.close(1)
        last = self.svc.find_last_open_by_user(7)
        self.assertEqual(last.id, 2)

    def test_assign_and_release(self):
        t = self.svc.create(1, "А", "текст1")
        self.assertTrue(self.svc.assign(t.id, 100))
        # Повторное закрепление тем же модератором — ок
        self.assertTrue(self.svc.assign(t.id, 100))
        # Другой модератор закрепить не может
        self.assertFalse(self.svc.assign(t.id, 300))
        self.assertEqual(self.svc.get_assignee(t.id), 100)
        # Чужой релиз не действует
        self.svc.release(t.id, 300)
        self.assertEqual(self.svc.get_assignee(t.id), 100)
        # Свой релиз снимает закрепление
        self.svc.release(t.id, 100)
        self.assertIsNone(self.svc.get_assignee(t.id))
        # После снятия другой модератор может закрепить
        self.assertTrue(self.svc.assign(t.id, 300))

    def test_assign_closed_ticket_rejected(self):
        t = self.svc.create(1, "А", "текст1")
        self.svc.close(t.id)
        self.assertFalse(self.svc.assign(t.id, 100))

    def test_assign_persists(self):
        t = self.svc.create(1, "А", "текст1")
        self.svc.assign(t.id, 100)
        svc2 = TicketService(self.config)
        self.assertEqual(svc2.get_assignee(t.id), 100)


# --- Тесты TelegramApi (без сети) ---

class TestTelegramApiParsing(unittest.TestCase):
    """Парсинг getUpdates и формирование запросов sendMessage."""

    def _api(self):
        from bot.telegram_api import TelegramApi
        api = TelegramApi.__new__(TelegramApi)
        api._base_url = "https://api.telegram.org/botTEST"
        return api

    def _parse(self, payload):
        api = self._api()
        with patch.object(api, "_send_get", return_value=payload):
            return api.get_updates(0)

    def test_message_parsing(self):
        updates = self._parse({"result": [{
            "update_id": 1,
            "message": {"chat": {"id": 10}, "from": {"id": 20, "first_name": "Иван", "username": "ivan"},
                        "text": "привет"},
        }]})
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].user_id, 20)
        self.assertEqual(updates[0].chat_id, 10)
        self.assertIn("Иван", updates[0].user_name)
        self.assertIn("@ivan", updates[0].user_name)

    def test_callback_parsing(self):
        updates = self._parse({"result": [{
            "update_id": 2,
            "callback_query": {
                "id": "cb1", "data": "mod:list",
                "from": {"id": 30, "first_name": "Мод"},
                "message": {"chat": {"id": 30}, "text": "старое"},
            },
        }]})
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].callback_data, "mod:list")
        self.assertEqual(updates[0].user_id, 30)
        self.assertEqual(updates[0].chat_id, 30)
        self.assertEqual(updates[0].text, "")

    def test_unknown_update_skipped(self):
        updates = self._parse({"result": [{"update_id": 3, "edited_message": {}}]})
        self.assertEqual(updates, [])

    def test_send_message_returns_message_id(self):
        api = self._api()
        with patch.object(api, "_send_post", return_value={"ok": True, "result": {"message_id": 77}}):
            self.assertEqual(api.send_message(5, "текст"), 77)

    def test_send_message_body(self):
        api = self._api()
        posts = []

        def fake_post(path, body):
            posts.append((path, body))
            return {"ok": True, "result": {"message_id": 1}}

        with patch.object(api, "_send_post", side_effect=fake_post):
            api.send_message(5, "текст", buttons=[[{"text": "b", "callback_data": "x"}]])
            api.send_message(6, "текст2", reply_buttons=[["🛠 Меню"]])
            api.answer_callback(7)
        self.assertEqual(posts[0][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "x")
        self.assertEqual(posts[1][1]["reply_markup"]["keyboard"][0][0]["text"], "🛠 Меню")
        self.assertEqual(posts[2][0], "/answerCallbackQuery")

    def test_delete_message_body(self):
        api = self._api()
        posts = []

        def fake_post(path, body):
            posts.append((path, body))
            return {"ok": True}

        with patch.object(api, "_send_post", side_effect=fake_post):
            self.assertTrue(api.delete_message(5, 123))
        path, body = posts[0]
        self.assertEqual(path, "/deleteMessage")
        self.assertEqual(body, {"chat_id": 5, "message_id": 123})

    def test_delete_message_without_id(self):
        api = self._api()
        with patch.object(api, "_send_post", return_value={"ok": True}) as p:
            self.assertFalse(api.delete_message(5, 0))
        p.assert_not_called()

    def test_long_text_truncated(self):
        api = self._api()
        with patch.object(api, "_send_post", return_value={"ok": True}) as p:
            api.send_message(5, "а" * 5000)
        body = p.call_args[0][1]
        self.assertLessEqual(len(body["text"]), 4025)
        self.assertIn("обрезано", body["text"])

    def test_send_error_not_raised(self):
        api = self._api()
        with patch.object(api, "_send_post", return_value={"ok": False}):
            api.send_message(5, "текст")  # не должно упасть

    def test_auth_error_raised_on_401(self):
        import urllib.error
        from bot.telegram_api import AuthError
        api = self._api()
        with patch("bot.telegram_api.urllib.request.urlopen") as urlopen:
            urlopen.side_effect = urllib.error.HTTPError(
                "url", 401, "Unauthorized", {}, io.BytesIO(b'{"ok": false}'))
            with self.assertRaises(AuthError):
                api._send_get("/getUpdates")

    def test_http_error_returns_empty_dict(self):
        import urllib.error
        api = self._api()
        with patch("bot.telegram_api.urllib.request.urlopen") as urlopen:
            urlopen.side_effect = urllib.error.HTTPError(
                "url", 500, "Server Error", {}, io.BytesIO(b'{"ok": false}'))
            self.assertEqual(api._send_get("/getUpdates"), {})

    def test_bot_run_stops_on_auth_error(self):
        # При невалидном токене бот останавливается, а не ретраит вечно
        from bot.bot import Bot
        from bot.telegram_api import AuthError
        bot = Bot.__new__(Bot)
        bot._api = None
        bot._moderators = None
        calls = {"n": 0}

        def fail(offset):
            calls["n"] += 1
            raise AuthError("токен отклонён")

        bot._get_updates = fail
        with self.assertRaises(SystemExit):
            bot.run()
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)