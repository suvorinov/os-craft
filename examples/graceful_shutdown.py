import asyncio
import logging
import sys

from os_craft import ShutdownManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def close_database():
    """Пример хука: безопасное закрытие соединения с БД."""
    logger.info("Закрываем соединения с БД...")
    await asyncio.sleep(1)  # Имитация работы
    logger.info("БД безопасно отключена.")

async def stop_background_worker():
    """Пример хука: остановка фонового воркера."""
    logger.info("Останавливаем фоновый воркер...")
    await asyncio.sleep(0.5)  # Имитация завершения текущей задачи
    logger.info("Воркер остановлен.")

async def main():
    # 1. Создаем менеджер с общим таймаутом 5 секунд
    manager = ShutdownManager(total_timeout=5.0)

    # 2. Регистрируем хуки. Они выполняются в обратном порядке (LIFO).
    # Сначала остановим воркера, потом закроем БД.
    manager.add_hook(close_database)
    manager.add_hook(stop_background_worker)

    # 3. Подписываемся на сигналы ОС (SIGINT, SIGTERM)
    # Активный event loop определяется внутри автоматически.
    manager.attach_to_signals()

    logger.info("Приложение запущено. Нажмите Ctrl+C для корректного завершения.")

    # Имитация долгой работы приложения.
    # При получении сигнала менеджер корректно отменит эту задачу.
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass  # Ожидаем, пока manager завершит все хуки

    return manager

if __name__ == "__main__":
    manager = asyncio.run(main())
    sys.exit(manager.exit_code)