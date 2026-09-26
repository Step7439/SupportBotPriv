from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Optional

from bot.update import Update

if TYPE_CHECKING:
    from bot import Config


class AuthError(RuntimeError):
    """Токен бота отклонён Telegram (401/404) — продолжать работу бессмысленно."""


class TelegramApi:
    """Тонкая обёртка над Telegram Bot API.

    Умеет только два действия: получить новые сообщения и отправить сообщение.
    """

    def __init__(self, config: "Config") -> None:
        self._base_url = f"https://api.telegram.org/bot{config.bot_token}"

    def get_updates(self, offset: int) -> list[Update]:
        """Long polling: ждёт новые сообщения (до 25 секунд)."""
        root = self._send_get(f"/getUpdates?timeout=25&offset={offset}")

        updates: list[Update] = []
        for node in root.get("result", []):
            message = node.get("message")
            callback = node.get("callback_query")
            if message is not None:
                sender = message.get("from", {})
                user_name = sender.get("first_name", "Пользователь")
                if sender.get("username"):
                    user_name += f" (@{sender['username']})"
                updates.append(Update(
                    update_id=node["update_id"],
                    chat_id=message["chat"]["id"],
                    user_id=sender["id"],
                    user_name=user_name,
                    text=message.get("text", ""),
                ))
            elif callback is not None:
                sender = callback.get("from", {})
                user_name = sender.get("first_name", "Пользователь")
                if sender.get("username"):
                    user_name += f" (@{sender['username']})"
                chat = callback.get("message", {}).get("chat", {})
                updates.append(Update(
                    update_id=node["update_id"],
                    chat_id=chat.get("id", sender.get("id", 0)),
                    user_id=sender["id"],
                    user_name=user_name,
                    text="",
                    callback_query_id=callback.get("id"),
                    callback_data=callback.get("data", ""),
                ))
        return updates

    def send_message(
        self,
        chat_id: int,
        text: str,
        buttons: Optional[list[list[dict]]] = None,
        reply_buttons: Optional[list[list[str]]] = None,
    ) -> Optional[int]:
        """Отправляет текстовое сообщение в чат.

        buttons — inline-кнопки под сообщением.
        reply_buttons — кнопки в поле ввода (постоянная клавиатура чата).
        Возвращает message_id отправленного сообщения (для последующего
        удаления) или None, если Telegram не вернул идентификатор.
        """
        if len(text) > 4000:
            text = text[:4000] + "\n…(сообщение обрезано)"
        body: dict = {"chat_id": chat_id, "text": text}
        if buttons:
            body["reply_markup"] = {"inline_keyboard": buttons}
        elif reply_buttons:
            body["reply_markup"] = {
                "keyboard": [[{"text": b} for b in row] for row in reply_buttons],
                "resize_keyboard": True,
            }
        root = self._send_post("/sendMessage", body)
        if not root.get("ok", False):
            print(f"Telegram не принял сообщение: {root}")
            return None
        return root.get("result", {}).get("message_id")

    def delete_message(self, chat_id: int, message_id: int) -> bool:
        """Удаляет сообщение, отправленное ботом (метод deleteMessage)."""
        if not message_id:
            return False
        root = self._send_post("/deleteMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
        })
        if not root.get("ok", False):
            print(f"Telegram не удалил сообщение: {root}")
            return False
        return True

    def send_photo(self, chat_id: int, photo_path, caption: str = "") -> None:
        """Отправляет картинку с подписью (multipart/form-data)."""
        from uuid import uuid4

        boundary = uuid4().hex
        with open(photo_path, "rb") as f:
            file_data = f.read()

        parts: list[bytes] = []
        text_caption = caption[:1000]
        for name, value in (("chat_id", str(chat_id)), ("caption", text_caption)):
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode("utf-8")
            )
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo"; filename="logo.png"\r\n'
            f"Content-Type: image/png\r\n\r\n".encode("utf-8")
            + file_data + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)

        request = urllib.request.Request(
            self._base_url + "/sendPhoto",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        root = self._read_response(request)
        if not root.get("ok", False):
            print(f"Telegram не принял фото: {root}")

    def set_my_commands(self, commands: list[tuple[str, str]]) -> None:
        """Регистрирует меню команд бота (кнопка ≡ слева от поля ввода)."""
        body = {"commands": [{"command": c, "description": d} for c, d in commands]}
        root = self._send_post("/setMyCommands", body)
        if not root.get("ok", False):
            print(f"Telegram не принял список команд: {root}")

    def answer_callback(self, callback_query_id: int) -> None:
        """Подтверждает нажатие кнопки, чтобы у модератора не крутились часы."""
        if callback_query_id is None:
            return
        self._send_post("/answerCallbackQuery", {"callback_query_id": callback_query_id})

    def send_message_to_all(
        self,
        chat_ids: list[int],
        text: str,
        buttons: Optional[list[list[dict]]] = None,
    ) -> None:
        """Отправляет сообщение всем из списка (например, всем модераторам)."""
        for chat_id in chat_ids:
            self.send_message(chat_id, text, buttons)

    def _send_get(self, path: str) -> dict:
        request = urllib.request.Request(self._base_url + path, method="GET")
        return self._read_response(request)

    def _send_post(self, path: str, body: dict) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._read_response(request)

    @staticmethod
    def _read_response(request: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (401, 404):
                # Токен недействителен — ретраи не помогут, останавливаемся
                raise AuthError(
                    f"Telegram отклонил токен бота (HTTP {e.code}). "
                    "Проверьте BOT_TOKEN в .env (получить у @BotFather)."
                )
            # Прочие сбои — точечный отказ, бот продолжает работу
            print(f"Ошибка Telegram API ({e.code}) на {request.full_url}: {detail}")
            return {}