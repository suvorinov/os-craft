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
 
## 📋 Config Manager: строгая загрузка конфигурации

### Почему это важно? (Why it matters)

Большинство приложений берут настройки из трёх источников: значения по умолчанию, конфиг-файл и переменные окружения. Ручное склеивание этих источников быстро превращается в простыню из `os.getenv` с ручным приведением типов (`int(os.getenv("PORT")) or 8080`). Результат — баги типов, нечитаемый код и магические значения.

`load_config` из os-craft решает это одним вызовом:

* **Схема = dataclass.** Описываете конфигурацию как обычный типизированный dataclass — и получаете автодополнение в IDE и проверку типов через mypy.
* **Три источника с честным приоритетом.** Значения по умолчанию → TOML-файл → переменные окружения (ENV побеждает).
* **Автоматическое приведение типов.** Строки из ENV превращаются в `int`, `float`, `bool`, `Path` и даже `list[...]` без единого `int(...)` в вашем коде.
* **Ноль тяжёлых зависимостей.** Используется только стандартная библиотека (на Python 3.10 — официальный backport `tomli`).

### Quick Start / Быстрый старт

```python
import logging
from dataclasses import dataclass, field
from pathlib import Path

from os_craft import load_config

logging.basicConfig(level=logging.INFO)

# 1. Описываем схему как обычный dataclass
@dataclass
class AppConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    allowed_origins: list[str] = field(default_factory=list)
    db_timeout: float = 5.0
    data_dir: Path = Path("/var/lib/app")

# 2. Загружаем: default -> config.toml -> переменные окружения
config = load_config(
    config_cls=AppConfig,
    env_prefix="APP",          # ищем APP_HOST, APP_PORT, APP_DEBUG...
    file_path=Path("config.toml"),
)

print(config.port)             # тип int
print(config.allowed_origins)  # тип list[str]
```

Пример файла `config.toml`:

```toml
# config.toml
host = "127.0.0.1"
port = 8000
debug = true
allowed_origins = ["http://localhost:3000"]
```

### Приоритет источников (от низшего к высшему)

    1. Значения по умолчанию в dataclass.
    2. Значения из TOML-файла (если path указан и файл существует).
    3. Переменные окружения с префиксом {env_prefix}_ (например, APP_PORT).

Переменные окружения имеют наивысший приоритет — это ключевой паттерн для
контейнеров (Docker/Kubernetes), где конфиг-файл лежит в образе, а специфичные
для окружения значения передаются через ENV.

### Поддерживаемые типы

| Тип поля           | Из TOML                    | Из ENV (строка → тип)                        |
|--------------------|----------------------------|----------------------------------------------|
| `str`              | строка                     | как есть                                     |
| `bool`             | `true` / `false`           | `"true"`, `"1"`, `"yes"`, `"on"` → `True`; всё остальное → `False` |
| `int`              | число                      | `"8080"` → `8080`                            |
| `float`            | число                      | `"5.0"` → `5.0`                              |
| `Path`             | путь (строка)              | `"/var/lib"` → `Path("/var/lib")`            |
| `list[...]`        | список                     | `"a,b,c"` → `["a", "b", "c"]` (элементы приводятся к внутреннему типу, например `list[int]`) |

Если тип поля не входит в этот список (например, `tuple`), загрузка завершится
**понятной ошибкой** — неподдерживаемый тип не нарушается молча.

### Ошибки (гарантии библиотеки)

* Обязательное поле (без дефолта), не заполненное нигде → корректный
  `TypeError` от dataclass, а не мусорное значение.
* Неверный тип в ENV или TOML → `ValueError` с именем поля и причиной:
  ```
  Не удалось привести значение ENV APP_PORT='not_a_number' к типу <class 'int'>.
  ```
* Передан не dataclass → `TypeError`.

### Real-World Example / Пример

Полный пример доступен в `examples/config_usage.py`, демо-конфиг — в `examples/config.toml`:

```bash
uv run python examples/config_usage.py
```

Проверка переопределения через ENV (значения из TOML должны перезаписаться):

```bash
APP_PORT=9090 APP_DEBUG=false \
APP_ALLOWED_ORIGINS="https://api.com,https://admin.com" \
uv run python examples/config_usage.py
```

Ожидаемый результат: `Port: 9090`, `Debug: False`, а строка из ENV автоматически
превратилась в список `['https://api.com', 'https://admin.com']`.

### Тесты / Checks

Модуль покрыт тестами в `tests/test_config.py`:

* значения по умолчанию без файлов и ENV;
* загрузка и парсинг TOML;
* неверный тип в TOML → `ValueError`;
* ENV-переопределение с приведением типов (включая `list[str]`);
* `Path` и `list[int]` из ENV;
* обязательное поле без значения → `TypeError` (никакого MISSING-sentinel);
* неподдерживаемый тип → `ValueError` с понятным сообщением;
* не-dataclass → `TypeError`.

Запуск всех тестов проекта (31 тест: shutdown + config + hot_reload):

```bash
uv run pytest -v
```

### 🔄 Hot-Reload: горячая перезагрузка конфигурации

`ConfigError` + `HotReloadConfig` добавляют к статичной загрузке возможность
**менять настройки на лету, без перезапуска процесса**. Это критично для
продолжительных сервисов (воркеров, ботов, демонов), где рестарт дорог или
нежелателен.

Как это работает:

* `HotReloadConfig` при создании загружает конфигурацию через `load_config`
  и запускает **фоновый поток-watcher**.
* Каждые `poll_interval` секунд поток проверяет `mtime` файла.
* При изменении файла конфигурация перезагружается (с теми же приоритетами
  default → TOML → ENV) и вызываются все зарегистрированные коллбэки.
* Рабочий код читает актуальные значения через свойство `.config` — без
  блокировок и без ручных проверок.
* Watcher отказоустойчив: сбой перезагрузки или ошибка в коллбэке не убивают
  поток — старая конфигурация сохраняется, а проблема логируется.

Quick Start / Быстрый старт:

```python
import logging
from dataclasses import dataclass
from pathlib import Path

from os_craft import HotReloadConfig

logging.basicConfig(level=logging.INFO)

@dataclass
class AppSettings:
    app_name: str                    # обязательное поле
    max_workers: int = 4
    feature_flag_new_ui: bool = False

# Коллбэк вызовется автоматически при каждом изменении файла
def on_change(new_config: AppSettings):
    logging.info(f"config updated: workers={new_config.max_workers}")

manager = HotReloadConfig(
    config_cls=AppSettings,
    file_path=Path("config.toml"),
    env_prefix="APP",
    poll_interval=2.0,               # проверка каждые 2 секунды
)
manager.add_callback(on_change)

# В основном цикле всегда читаем актуальную конфигурацию через .config:
while True:
    current = manager.config         # всегда свежие значения
    ...

# При завершении приложения обязательно останавливаем фоновый поток:
manager.stop()
```

Поведение и гарантии:

* **Отсутствующий файл при создании** → `ConfigError`.
* **Файл удалили во время работы** → watcher ждёт восстановления, используя
  последнюю загруженную конфигурацию.
* **Некорректные значения в изменённом файле** → перезагрузка не применяется,
  остаётся прежняя конфигурация.
* **ENV по-прежнему имеет высший приоритет** и учитывается при каждой
  перезагрузке.
* **`stop()`** останавливает поток-watcher (с join-timeout 2 секунды).

Пример целиком: `examples/hot_reload_usage.py` (демо-конфиг — свой
`examples/hot_reload.toml`, чтобы не конфликтовать с примером `config_usage.py`).

Запуск:

```bash
uv run python examples/hot_reload_usage.py
```

Проверка: откройте `examples/hot_reload.toml`, поменяйте `max_workers` на
другое значение и сохраните — через пару секунд в консоли появится лог
`🔄 КОНФИГ ОБНОВЛЕН!` с новыми значениями.

Тесты горячей перезагрузки — в `tests/test_hot_reload.py`:

* отсутствие файла → `ConfigError`;
* перезагрузка при изменении файла + срабатывание коллбэков;
* падающий коллбэк не убивает watcher;
* битый TOML — прежняя конфигурация сохраняется;
* ENV-переопределение применяется при перезагрузке;
* `stop()` корректно останавливает поток.

---

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
Тесты покрывают все модули:
* `tests/test_shutdown.py` — порядок LIFO, таймауты, sync/async хуки, идемпотентность, обработка реальных сигналов SIGINT.
* `tests/test_config.py` — значения по умолчанию, TOML, ENV-переопределения, приведение типов, обработка ошибок.
* `tests/test_hot_reload.py` — горячая перезагрузка конфигурации, коллбэки, отказоустойчивость watcher.

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
    │       ├── shutdown.py     # ShutdownManager (graceful shutdown)
    │       ├── config.py       # load_config (типизированная загрузка конфига)
    │       └── py.typed        # Маркер для mypy (PEP 561)
    ├── tests/
    │   ├── test_shutdown.py    # Тесты для ShutdownManager
    │   ├── test_config.py      # Тесты для load_config
    │   └── test_hot_reload.py  # Тесты для HotReloadConfig
    └── examples/
        ├── fastapi_graceful_shutdown.py  # Пример интеграции с FastAPI
        ├── graceful_shutdown.py          # Пример graceful shutdown без FastAPI
        ├── config_usage.py               # Пример использования load_config
        ├── config.toml                   # Демо-конфигурация для config_usage
        ├── hot_reload_usage.py           # Пример hot-reload конфигурации
        └── hot_reload.toml               # Демо-конфигурация для hot_reload_usage

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
