"""Тесты бота техподдержки: пользователи, модераторы, кнопки, заявки."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from bot.moderator_service import ModeratorService
from bot.mod_handler import ModHandler
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
        self.callback_answers: list[int] = []
        self.photos: list[tuple] = []

    def send_message(self, chat_id, text, buttons=None, reply_buttons=None):
        self.sent.append(Sent(chat_id, text, buttons, reply_buttons))

    def send_photo(self, chat_id, photo_path, caption=""):
        self.photos.append((chat_id, str(photo_path), caption))

    def answer_callback(self, callback_query_id):
        self.callback_answers.append(callback_query_id)

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
    def test_start_shows_reply_buttons(self):
        self.say("/start", user_id=200)
        # Приветствие с логотипом (фото + подпись) и сообщение с кнопками
        self.assertIn("ИТМеханизатор — Support", self.api.photos[0][2])
        buttons_msg = [s for s in self.api.sent if s.reply_buttons]
        self.assertEqual(buttons_msg[0].reply_buttons, [["📝 Заявка", "📊 Статус", "❓ FAQ"]])

    def test_faq_button(self):
        self.say("❓ FAQ", user_id=200)
        self.assertIn("Частые вопросы", self.api.texts(200)[0])

    def test_ticket_button_asks_description(self):
        self.say("📝 Заявка", user_id=200)
        self.assertIn("Опишите", self.api.texts(200)[0])

    def test_status_no_tickets(self):
        self.say("📊 Статус", user_id=200)
        self.assertIn("нет заявок", self.api.texts(200)[0])

    def test_plain_text_creates_ticket(self):
        self.say("не работает вход", user_id=200)
        self.assertIn("Заявка #1 создана", self.api.texts(200)[0])
        # Модератор получил уведомление с кнопками
        mod_msg = self.api.to(100)[0]
        self.assertIn("Новая заявка #1", mod_msg.text)
        self.assertEqual(mod_msg.buttons[0][0]["callback_data"], "mod:answer:1")
        self.assertEqual(mod_msg.buttons[0][1]["callback_data"], "mod:close:1")

    def test_status_after_ticket(self):
        self.say("не работает вход", user_id=200)
        self.say("📊 Статус", user_id=200)
        self.assertIn("в работе", self.api.texts(200)[-1])

    def test_status_closed_ticket(self):
        self.say("не работает вход", user_id=200)
        self.tickets.close(1)
        self.say("📊 Статус", user_id=200)
        self.assertIn("закрыта", self.api.texts(200)[-1])


# --- Тесты модератора: команды ---

class TestModCommands(BaseTest):
    def test_mod_opens_menu_with_reply_button(self):
        self.say("/mod")
        msg = self.api.to(100)[0]
        self.assertIn("Меню модератора", msg.text)
        self.assertEqual(msg.reply_buttons, [["🛠 Меню"]])
        self.assertEqual(len(msg.buttons), 2)  # заявки + модераторы

    def test_menu_button_opens_menu(self):
        self.say("🛠 Меню")
        self.assertIn("Меню модератора", self.api.texts(100)[0])

    def test_start_opens_menu_for_moderator(self):
        self.say("/start")
        # Страница приветствия с логотипом: «ИТМеханизатор — Support»
        self.assertIn("ИТМеханизатор — Support", self.api.photos[0][2])
        self.assertIn("модератора", self.api.photos[0][2])

    def test_mod_menu_still_works(self):
        self.say("/mod")
        self.assertIn("Меню модератора", self.api.texts(100)[0])
        self.assertEqual(self.api.photos, [])  # без логотипа

    def test_unknown_text_shows_menu(self):
        self.say("абракадабра")
        texts = self.api.texts(100)
        self.assertIn("Не понял сообщение", texts[0])
        self.assertIn("Меню модератора", texts[1])

    def test_list_empty(self):
        self.press("mod:list")
        self.assertIn("Открытых заявок нет", self.api.texts(100)[0])

    def test_list_shows_tickets_with_buttons(self):
        self.say("проблема А", user_id=200)
        self.api.sent.clear()
        self.press("mod:list")
        self.assertIn("Открытые заявки: 1", self.api.texts(100)[0])
        ticket_msg = self.api.to(100)[1]
        self.assertIn("проблема А", ticket_msg.text)
        self.assertEqual(ticket_msg.buttons[0][0]["text"], "💬 Ответить")
        self.assertEqual(ticket_msg.buttons[0][1]["text"], "✅ Закрыть")


# --- Тесты модератора: кнопки ---

class TestModButtons(BaseTest):
    def setUp(self):
        super().setUp()
        self.say("проблема А", user_id=200)  # заявка #1 от пользователя 200
        self.api.sent.clear()

    def test_answer_flow(self):
        self.press("mod:answer:1")
        self.assertIn("Напишите ответ по заявке #1", self.api.texts(100)[0])
        self.say("вот решение")
        self.assertIn("Ответ поддержки по заявке #1", self.api.texts(200)[0])
        self.assertIn("вот решение", self.api.texts(200)[0])
        self.assertIn("Ответ отправлен", self.api.texts(100)[-1])

    def test_answer_on_closed_ticket(self):
        self.tickets.close(1)
        self.press("mod:answer:1")
        self.assertIn("не найдена или уже закрыта", self.api.texts(100)[0])

    def test_close_flow(self):
        self.press("mod:close:1")
        self.assertEqual(self.tickets.find_by_id(1).status, "CLOSED")
        self.assertIn("закрыта", self.api.texts(200)[0])
        self.assertIn("Заявка #1 закрыта", self.api.texts(100)[0])

    def test_close_after_answer_button(self):
        self.press("mod:answer:1")
        self.say("вот решение")
        # кнопка «Закрыть заявку» в сообщении после ответа
        close_btn = self.api.to(100)[-1].buttons[0][0]["callback_data"]
        self.press(close_btn)
        self.assertEqual(self.tickets.find_by_id(1).status, "CLOSED")

    def test_unknown_ticket(self):
        self.press("mod:close:99")
        self.assertIn("не найдена", self.api.texts(100)[0])

    def test_unknown_button(self):
        self.press("mod:nonsense")
        self.assertIn("Неизвестная кнопка", self.api.texts(100)[0])

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


# --- Тесты модераторов: добавление/удаление ---

class TestModeratorManagement(BaseTest):
    def test_mods_list_with_buttons(self):
        self.press("mod:mods")
        texts = self.api.texts(100)
        self.assertIn("Модераторы", texts[0])
        self.assertIn("100", texts[1])
        add_msg = self.api.to(100)[-1]
        self.assertEqual(add_msg.buttons[0][0]["callback_data"], "mod:add")

    def test_add_moderator_flow(self):
        self.press("mod:add")
        self.assertIn("Отправьте Telegram ID", self.api.texts(100)[0])
        self.say("300")
        self.assertIn("Модератор 300 добавлен", self.api.texts(100)[-1])
        self.assertTrue(self.moderators.is_moderator(300))
        # Новый модератор получил приветствие с кнопкой меню
        welcome = self.api.to(300)[0]
        self.assertIn("добавили в модераторы", welcome.text)
        self.assertEqual(welcome.reply_buttons, [["🛠 Меню"]])

    def test_add_moderator_invalid_id_retries(self):
        self.press("mod:add")
        self.say("абракадабра")
        self.assertIn("ID должен быть числом", self.api.texts(100)[-1])
        self.say("400")
        self.assertIn("Модератор 400 добавлен", self.api.texts(100)[-1])

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

    def test_add_negative_moderator_rejected(self):
        self.press("mod:add")
        self.say("-999")
        self.assertIn("положительным числом", self.api.texts(100)[-1])
        self.assertEqual(self.moderators.get_all(), [100])

    def test_malformed_callback_data_not_crash(self):
        self.press("mod:answer:abc")
        self.assertIn("Некорректная кнопка", self.api.texts(100)[0])
        self.press("mod:close:xyz")
        self.assertIn("Некорректная кнопка", self.api.texts(100)[1])
        self.press("mod:remove:!!!")
        self.assertIn("Некорректная кнопка", self.api.texts(100)[2])

    def test_user_callback_ignored(self):
        # Не-модератор нажал старую/поддельную кнопку — заявка не создаётся
        self.users.handle(make_update(999, 200, "", callback_query_id=5, callback_data="mod:close:1"))
        self.assertEqual(self.api.to(200), [])
        self.assertEqual(len(self.tickets.get_all()), 0)


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
        # Повторное закрытие несуществующей — не падает
        self.svc.close(99)

    def test_created_at_set(self):
        t = self.svc.create(1, "А", "текст")
        self.assertIsNotNone(t.created_at)


# --- Тесты TelegramApi (без сети) ---

class TestTelegramApiParsing(unittest.TestCase):
    """Парсинг getUpdates и формирование запросов sendMessage."""

    def _api(self):
        from bot.telegram_api import TelegramApi
        return TelegramApi.__new__(TelegramApi)

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

    def test_send_message_body(self):
        api = self._api()
        posts = []

        def fake_post(path, body):
            posts.append((path, body))
            return {"ok": True}

        with patch.object(api, "_send_post", side_effect=fake_post):
            api.send_message(5, "текст", buttons=[[{"text": "b", "callback_data": "x"}]])
            api.send_message(6, "текст2", reply_buttons=[["🛠 Меню"]])
            api.answer_callback(7)
        self.assertEqual(posts[0][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "x")
        self.assertEqual(posts[1][1]["reply_markup"]["keyboard"][0][0]["text"], "🛠 Меню")
        self.assertEqual(posts[2][0], "/answerCallbackQuery")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
