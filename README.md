# os-craft

![Python Versions](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12%20|%203.13%20|%203.14-blue)
![License](https://img.shields.io/badge/license-MIT-green)
[![PyPI Version](https://img.shields.io/pypi/v/os-craft)](https://pypi.org/project/os-craft/)
![Tests](https://img.shields.io/badge/tests-passing-brightgreen)

**RU:** Легковесные, надежные и типизированные утилиты для взаимодействия Python-приложений с операционной системой.  
**EN:** Lightweight, robust, and strictly typed utilities for seamless Python-to-OS interaction.

---

## 🚀 Installation / Установка

```bash
# Рекомендуемый способ (через uv - молниеносный пакетный менеджер)
uv add os-craft

# Классический способ
pip install os-craft
```

## 🛡️ Core Feature: Graceful Shutdown Manager
### Почему это важно? (Why it matters)
Когда оркестратор (Kubernetes, systemd) или пользователь нажимает Ctrl+C, ОС отправляет процессу сигнал SIGTERM или SIGINT. По умолчанию Python просто прерывает выполнение. Если в этот момент ваша программа:

    Писала данные в базу данных → транзакция оборвется, данные могут повредиться.
    Обрабатывала фоновую задачу → результат будет потерян.
    Держала открытые файловые дескрипторы → возможны утечки ресурсов.

ShutdownManager из os-craft перехватывает эти сигналы и гарантирует упорядоченное (LIFO), ограниченное по времени (timeout) и безопасное освобождение ресурсов. После завершения всех хуков процесс автоматически завершается с кодом выхода 0.

### Quick Start / Быстрый старт

```python
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
    # Очистка завершена, получаем код выхода (0 - успех, 1 - ошибка в хуке)
    manager = asyncio.run(main())
    sys.exit(manager.exit_code)
```
#### Что произойдет при нажатии Ctrl+C:

    1. INFO | Получен сигнал остановки ОС. Инициируем graceful shutdown...
    2. INFO | Начинаем graceful shutdown. Зарегистрировано хуков: 2
    3. INFO | Выполняем хук: stop_background_worker (доступно 5.00s)
    4. INFO | Останавливаем фоновый воркер...
    5. INFO | Воркер остановлен.
    6. INFO | Выполняем хук: close_database (доступно 4.50s)
    7. INFO | Закрываем соединения с БД...
    8. INFO | БД безопасно отключена.
    9. INFO | Процесс graceful shutdown успешно завершен.

После этого `asyncio.run(main())` корректно вернёт управление в `__main__`,
и процесс завершится с кодом выхода 0. Если какой-либо хук упал или превысил
таймаут — `manager.exit_code` будет равен 1, и оркестратор (Kubernetes, systemd)
узнает о проблеме.

#### Что произойдет при сбое хука:

    1. INFO | Выполняем хук: bad_hook (доступно 5.00s)
    2. ... | Необработанная ошибка в хуке bad_hook. Продолжаем.
    3. ERROR | Graceful shutdown завершен с ошибками (см. логи выше).
    4. →  Оставшиеся хуки всё равно выполнятся, процесс выйдет с кодом 1.

## 📖 Real-World Example: FastAPI Integration

Полный пример интеграции с FastAPI (с фоновыми задачами и имитацией БД) доступен в директории examples/fastapi_graceful_shutdown.py.
Запуск:

```bash
    uv run python examples/fastapi_graceful_shutdown.py
```

Проверка:

    1. Откройте другой терминал: curl http://127.0.0.1:8000/
    2. Вернитесь в терминал с сервером и нажмите Ctrl+C
    3. Наблюдайте за корректным завершением всех ресурсов
 
## ⚙️ Технические детали (Technical Details)

1. LIFO Execution Order (Порядок LIFO)

    Хуки выполняются в порядке "последний добавлен — первый выполнен". Это критично для корректного освобождения ресурсов:

    * Сначала останавливаем прием новых задач (закрываем порт веб-сервера).
    * Затем дожидаемся завершения текущих операций.
    * Только потом закрываем соединения с базами данных и кэшем.


1. Unified Timeout (Единый таймаут)

    Вместо таймаута на каждый хук используется общий таймаут на весь процесс shutdown. Это предотвращает ситуацию, когда первый хук "съедает" все время, а на важные последние хуки (закрытие БД) времени не остается.
    Если общий таймаут превышен, выполнение оставшихся хуков прерывается, и процесс завершается.

1. Async/Sync Agnostic (Поддержка синхронного и асинхронного кода)

    Менеджер автоматически определяет тип функции через inspect.iscoroutinefunction:

    * Async-хуки выполняются напрямую с await.
    * Sync-хуки выполняются в loop.run_in_executor, чтобы никогда не блокировать asyncio event loop, даже если разработчик написал тяжелую синхронную операцию.

1. Fail-Safe Design (Отказоустойчивость)
    
    Если один из хуков выбрасывает исключение или превышает таймаут, ShutdownManager:

    * Логирует ошибку.
    * Продолжает выполнение следующих хуков.
    * Никогда не прерывает весь процесс очистки из-за одной ошибки.
    * Помечает shutdown как неуспешный: `manager.exit_code` после завершения
      будет равен 1, чтобы оркестратор (Kubernetes, systemd) получил сигнал
      о проблеме вместо "тихого" кода 0.

1. Idempotency & Clean Exit (Идемпотентность и чистое завершение)

    Повторный сигнал или повторный вызов выполнения хуков не запускает
    их заново. После завершения хуков менеджер корректно отменяет главную
    задачу приложения, поэтому `asyncio.run(main())` возвращается штатно —
    без `Task exception was never retrieved` в логах — и код выхода можно
    прочитать через `manager.exit_code`.

1. Automatic Process Termination (Автоматическое завершение процесса)

    Процесс завершается сам: достаточно вернуть `manager` из `main()` и
    вызвать `sys.exit(manager.exit_code)`.

1. OS Signal Handling (Обработка сигналов ОС)

    Менеджер подписывается на:

    * SIGINT (Ctrl+C) — для локальной разработки.
    * SIGTERM (сигнал 15) — для продакшена (Kubernetes, systemd, Docker).

    > ⚠️ Важно: Сигнал SIGKILL (сигнал 9, kill -9) невозможно перехватить. Это защита ОС от зависших процессов. Всегда проектируйте систему так, чтобы она могла пережить внезапное завершение (например, используйте транзакции в БД).
    
    
## 🧪 Development / Разработка

Мы используем uv для молниеносного управления зависимостями и сборки.

### Установка окружения

```bash
# Клонирование репозитория
git clone <repository_url>
cd os-craft

# Установка зависимостей (создаст .venv и установит все пакеты)
uv sync

# Установка пакета в editable-режиме (для локальной разработки)
uv pip install -e .
```

### Запуск тестов
```bash
uv run pytest -v
```

### Проверка типов и линтинг
```bash
# Проверка типов (строгий режим)
uv run mypy src/os_craft

# Линтер (автоматическое исправление проблем)
uv run ruff check . --fix
```
### Сборка пакета
```bash
uv build
```
Это создаст папку dist/ с .tar.gz и .whl файлами, готовыми для публикации на PyPI.

## 🏗️ Project Structure / Структура проекта

    os-craft/
    ├── pyproject.toml          # Конфигурация проекта, зависимостей и инструментов
    ├── uv.lock                 # Lock-файл для воспроизводимых сборок
    ├── README.md               # Этот файл
    ├── LICENSE                 # MIT License
    ├── src/
    │   └── os_craft/
    │       ├── __init__.py     # Публичный API пакета
    │       ├── shutdown.py     # ShutdownManager
    │       └── py.typed        # Маркер для mypy (PEP 561)
    ├── tests/
    │   └── test_shutdown.py    # Тесты для ShutdownManager
    └── examples/
        └── fastapi_graceful_shutdown.py  # Пример интеграции с FastAPI

## 🤝 Contributing / Участие в разработке

Мы приветствуем вклад в развитие проекта! Если вы нашли баг или хотите добавить новую утилиту:

    1. Форкните репозиторий.
    2. Создайте ветку для вашей фичи: git checkout -b feature/amazing-feature
    3. Убедитесь, что все тесты проходят: uv run pytest
    4. Проверьте линтер и типы: uv run ruff check . && uv run mypy src/os_craft
    5. Сделайте коммит: git commit -m 'Add amazing feature'
    6. Отправьте в main: git push origin feature/amazing-feature
    7. Откройте Pull Request.
    
## 📄 License / Лицензия

MIT License. Свободно используйте в коммерческих и open-source проектах.
См. файл LICENSE для подробностей.

## 🙏 Acknowledgments / Благодарности

Проект создан с любовью к чистому коду, принципу KISS и уважению к разработчикам, которые хотят писать надежные Python-приложения.
Спасибо сообществу Python за потрясающие инструменты: asyncio, contextvars, uv, ruff, mypy.

**RU:** Если у вас есть вопросы или предложения, открывайте Issue или пишите в обсуждения.

**EN:** If you have any questions or suggestions, feel free to open an Issue or start a Discussion.
