from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Update:
    """Упрощённое представление события от Telegram.

    TelegramApi сам распарсивает JSON и складывает сюда только то, что нужно боту.
    Для нажатия inline-кнопки заполняются callback_query_id и callback_data.
    """

    update_id: int
    chat_id: int    # куда отвечать
    user_id: int    # кто написал (важно для проверки прав)
    user_name: str
    text: str
    callback_query_id: Optional[int] = None  # если это нажатие кнопки
    callback_data: str = ""                  # данные нажатой кнопки
