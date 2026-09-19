from __future__ import annotations

import time
from typing import TYPE_CHECKING

from bot.mod_handler import ModHandler
from bot.update import Update
from bot.user_handler import UserHandler

if TYPE_CHECKING:
    from bot import Config, ModeratorService, TelegramApi, TicketService


class Bot:
    """Роутер: получает сообщения от Telegram и раздаёт их обработчикам."""

    def __init__(
        self,
        config: "Config",
        api: "TelegramApi",
        tickets: "TicketService",
        moderators: "ModeratorService",
    ) -> None:
        self._api = api
        self._moderators = moderators
        self.user_handler = UserHandler(api, tickets, moderators)
        self.mod_handler = ModHandler(api, tickets, moderators)

    def run(self) -> None:
        print("Бот техподдержки запущен.")
        offset = 0
        while True:
            try:
                updates = self._get_updates(offset)
                for update in updates:
                    offset = update.update_id + 1
                    self._handle(update)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"Сбой связи с Telegram, повтор через 5 секунд: {e}")
                time.sleep(5)

    def _get_updates(self, offset: int) -> list[Update]:
        return self._api.get_updates(offset)

    def _handle(self, update: Update) -> None:
        if not update.text.strip() and update.callback_query_id is None:
            return
        try:
            if self._moderators.is_moderator(update.user_id):
                self.mod_handler.handle(update)
            else:
                self.user_handler.handle(update)
        except Exception as e:
            print(f"Ошибка при обработке сообщения от {update.user_id}: {e}")
