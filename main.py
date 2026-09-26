"""Точка входа. Создаёт все сервисы и запускает бота."""
from bot import Bot, Config, ModeratorService, TelegramApi, TicketService


def main() -> None:
    try:
        config = Config()
        api = TelegramApi(config)
        tickets = TicketService(config)
        moderators = ModeratorService(config)

        # При первом запуске автоматически добавляем оператора модератором,
        # чтобы не редактировать moderators.json вручную.
        if not moderators.get_all() and config.operator_id is not None:
            moderators.add(config.operator_id)
            print(f"Оператор {config.operator_id} добавлен модератором.")

        bot = Bot(config, api, tickets, moderators)

        # Меню команд (кнопка ≡ слева от поля ввода в Telegram)
        api.set_my_commands([
            ("start", "Открыть приветствие"),
            ("myid", "Узнать свой ID"),
            ("faq", "Частые вопросы"),
            ("mod", "Панель модератора"),
        ])
        bot.run()
    except Exception as e:
        print(f"Не удалось запустить бота: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
