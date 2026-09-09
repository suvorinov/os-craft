"""
Пример интеграции os-craft с FastAPI для грациозного завершения работы.

Этот скрипт демонстрирует, как корректно завершать:
1. HTTP-сервер (Uvicorn).
2. Фоновые периодические задачи (например, воркеры или очистка кэша).
3. "Соединения с базой данных" (имитация).

Запуск:
    uv run python examples/fastapi_graceful_shutdown.py

Проверка работы:
    1. Запустите скрипт.
    2. В другом терминале выполните: curl http://127.0.0.1:8000/
    3. Нажмите Ctrl+C в терминале со скриптом.
    4. Наблюдайте за логами: вы увидите, как система дожидается завершения 
       текущих операций перед полным остановом, вместо резкого обрыва.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

# Импортируем наш менеджер. В реальном проекте это будет: from os_craft import ShutdownManager
# import sys
# from pathlib import Path
# sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from os_craft import ShutdownManager

# Настраиваем красивое логирование, чтобы видеть процесс shutdown в реальном времени
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("example_app")


# --- Имитация внешних ресурсов ---

class MockDatabase:
    """Имитация пула соединений с базой данных."""
    def __init__(self):
        self.is_connected = False

    async def connect(self):
        logger.info("🔌 Подключение к базе данных...")
        await asyncio.sleep(0.5) # Имитация задержки сети
        self.is_connected = True
        logger.info("✅ База данных подключена.")

    async def disconnect(self):
        logger.info("🔌 Закрытие соединений с базой данных...")
        await asyncio.sleep(1.0) # Имитация безопасного закрытия транзакций
        self.is_connected = False
        logger.info("✅ База данных отключена безопасно.")

db = MockDatabase()


async def background_worker():
    """
    Имитация фоновой задачи (например, обработка очереди сообщений).
    Эта задача должна корректно завершиться при получении сигнала остановки,
    а не быть убита посередине обработки.
    """
    logger.info("⚙️ Фоновый воркер запущен.")
    try:
        while True:
            logger.info("🔄 Воркер обрабатывает задачу...")
            await asyncio.sleep(2.0) # Имитация полезной работы
    except asyncio.CancelledError:
        # НЕОЧЕВИДНОЕ РЕШЕНИЕ: Мы ловим CancelledError, чтобы завершить 
        # текущую "итерацию" чисто, прежде чем выйти из цикла.
        logger.info("🛑 Воркер получил сигнал отмены. Завершаем текущую задачу...")
        await asyncio.sleep(0.5) # Имитация сохранения прогресса
        logger.info("✅ Воркер корректно остановлен.")
        raise # Пробрасываем дальше, чтобы asyncio знал, что задача отменена


# --- Интеграция с FastAPI и os-craft ---

# Создаем экземпляр менеджера. 
# Таймаут 5 секунд: если за это время не успеем закрыться, ОС нас убьет (SIGKILL).
shutdown_manager = ShutdownManager(total_timeout=5.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan контекст FastAPI (замена устаревшим @app.on_event("startup")).
    Здесь мы инициализируем ресурсы и регистрируем хуки завершения.
    """
    # 1. Инициализация при старте
    await db.connect()
    
    # Запускаем фоновую задачу и сохраняем ссылку на неё, чтобы потом отменить
    worker_task = asyncio.create_task(background_worker(), name="background_worker")
    
    # 2. Регистрация хуков завершения (ВАЖНО: порядок имеет значение!)
    # Хуки выполняются в обратном порядке (LIFO). 
    # Сначала мы должны остановить воркера, потом закрыть БД.
    
    # Хук 2 (выполнится вторым): закрытие БД
    shutdown_manager.add_hook(db.disconnect)
    
    # Хук 1 (выполнится первым): отмена фоновой задачи
    def cancel_worker():
        logger.info("🛑 Инициируем отмену фонового воркера...")
        worker_task.cancel()
    
    shutdown_manager.add_hook(cancel_worker)

    # 3. Подписка на сигналы НЕ требуется: uvicorn сам перехватывает
    # SIGINT/SIGTERM и корректно запускает teardown lifespan, где мы
    # выполняем хуки через shutdown_manager._execute_hooks().
    # Это исключает конфликт двух обработчиков сигналов и двойное выполнение хуков.

    logger.info("🚀 Приложение полностью готово к работе!")

    yield # Здесь управление передается FastAPI/Uvicorn

    # Реальная очистка делегируется shutdown_manager, чтобы централизовать
    # логику и таймауты. Вызывается один раз — при завершении lifespan.
    logger.info("🔄 Завершение работы приложения через lifespan...")
    await shutdown_manager._execute_hooks()


# Инициализация приложения с нашим lifespan
app = FastAPI(
    title="os-craft FastAPI Example",
    description="Демонстрация грациозного завершения работы с помощью os-craft",
    version="0.1.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Простой эндпоинт для проверки работоспособности."""
    if db.is_connected:
        return {"status": "ok", "message": "Сервер работает и подключен к БД"}
    return {"status": "error", "message": "База данных недоступна"}


if __name__ == "__main__":
    # Запускаем Uvicorn. 
    # workers=1 важен для примера, чтобы логи не перемешивались и shutdown был предсказуемым.
    # В продакшене с os-craft лучше использовать gunicorn с uvicorn workers, 
    # но логика graceful shutdown на уровне процесса останется той же.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
        workers=1
    )