# os-craft

![Python Versions](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12%20|%203.13%20|%203.14-blue)
![License](https://img.shields.io/badge/license-MIT-green)
[![PyPI Version](https://img.shields.io/pypi/v/os-craft)](https://pypi.org/project/os-craft/)
![Tests](https://img.shields.io/badge/tests-passing-brightgreen)

**RU:** Легковесные, надежные и типизированные утилиты для взаимодействия Python-приложений с операционной системой.  
**EN:** Lightweight, robust, and strictly typed utilities for seamless Python-to-OS interaction.

---

## 📦 Modules / Модули

| Модуль | Назначение | Документация |
|--------|------------|--------------|
| `ShutdownManager` | Graceful shutdown: LIFO-хуки, единый таймаут, корректные exit-коды | [docs/shutdown.md](https://github.com/suvorinov/os-craft/blob/main/docs/shutdown.md) |
| `load_config` | Типизированная загрузка конфига: default → TOML → ENV | [docs/config.md](https://github.com/suvorinov/os-craft/blob/main/docs/config.md) |
| `HotReloadConfig` | Горячая перезагрузка конфигурации без рестарта процесса | [docs/config.md](https://github.com/suvorinov/os-craft/blob/main/docs/config.md) |
| `track_perf` / `track_block` | Профилирование времени и памяти (tracemalloc) | [docs/perf.md](https://github.com/suvorinov/os-craft/blob/main/docs/perf.md) |

Подробная документация по каждому модулю живёт в `docs/` — там полные примеры, гарантии и технические детали.

## 🚀 Installation / Установка

```bash
# Рекомендуемый способ (через uv - молниеносный пакетный менеджер)
uv add os-craft

# Классический способ
pip install os-craft
```

## ⚡ Quick Start / Быстрый старт

```python
import asyncio
import sys
from dataclasses import dataclass, field

from os_craft import ShutdownManager, load_config

@dataclass
class AppConfig:
    port: int = 8000
    debug: bool = False
    allowed_origins: list[str] = field(default_factory=list)

async def close_database():
    print("  Закрываем соединения с БД...")
    await asyncio.sleep(1)

async def main() -> ShutdownManager:
    # Конфигурация: default -> config.toml -> переменные окружения (APP_*)
    config = load_config(AppConfig, env_prefix="APP")
    print(f"  PORT={config.port}, DEBUG={config.debug}")

    # Graceful shutdown: хуки выполняются в обратном порядке (LIFO)
    manager = ShutdownManager(total_timeout=5.0)
    manager.add_hook(close_database)
    manager.attach_to_signals()  # SIGINT / SIGTERM

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass  # менеджер уже завершает хуки

    return manager

if __name__ == "__main__":
    manager = asyncio.run(main())
    sys.exit(manager.exit_code)  # 0 - успех, 1 - ошибка в хуке
```

## 🏗️ Project Structure / Структура проекта

    os-craft/
    ├── .github/
    │   └── workflows/
    │       └── ci.yml           # CI: ruff, mypy strict, pytest (Python 3.10-3.12)
    ├── docs/
    │   ├── shutdown.md          # Документация ShutdownManager
    │   ├── config.md            # Документация load_config + HotReloadConfig
    │   └── perf.md              # Документация track_perf / track_block
    ├── pyproject.toml           # Конфигурация проекта, зависимостей и инструментов
    ├── uv.lock                  # Lock-файл для воспроизводимых сборок
    ├── README.md                # Этот файл (индекс документации)
    ├── LICENSE                  # MIT License
    ├── .gitignore               # Исключения для git (вкл. editor swap-файлы)
    ├── .python-version          # Версия Python для uv
    ├── src/
    │   └── os_craft/
    │       ├── __init__.py      # Публичный API пакета (версия из metadata)
    │       ├── shutdown.py      # ShutdownManager (graceful shutdown)
    │       ├── config.py        # load_config + HotReloadConfig (конфигурация)
    │       ├── perf.py          # track_perf + track_block (профилирование)
    │       └── py.typed         # Маркер для mypy (PEP 561)
    ├── tests/
    │   ├── test_shutdown.py     # Тесты для ShutdownManager
    │   ├── test_config.py       # Тесты для load_config
    │   ├── test_hot_reload.py   # Тесты для HotReloadConfig
    │   └── test_perf.py         # Тесты для track_perf / track_block
    └── examples/
        ├── fastapi_graceful_shutdown.py  # Пример интеграции с FastAPI
        ├── graceful_shutdown.py          # Пример graceful shutdown без FastAPI
        ├── config_usage.py               # Пример load_config
        ├── config.toml                   # Демо-конфиг для config_usage
        ├── hot_reload_usage.py           # Пример HotReloadConfig
        ├── hot_reload.toml               # Демо-конфиг для hot_reload_usage
        └── perf_usage.py                 # Пример track_perf / track_block

Все 40 тестов запускаются одной командой: `uv run pytest -v`

## 🧪 Development / Разработка

Мы используем uv для молниеносного управления зависимостями и сборки.

### Установка окружения

```bash
# Клонирование репозитория
git clone https://github.com/suvorinov/os-craft.git
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
* `tests/test_perf.py` — время и память через tracemalloc, декоратор функций и классов, коллбэки-метрики.

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

Это создаст папку `dist/` с `.tar.gz` и `.whl` файлами, готовыми для публикации на PyPI.

## 🤝 Contributing / Участие в разработке

Мы приветствуем вклад в развитие проекта! Если вы нашли баг или хотите добавить новую утилиту:

1. Форкните репозиторий.
2. Создайте ветку для вашей фичи: `git checkout -b feature/amazing-feature`
3. Убедитесь, что все тесты проходят: `uv run pytest`
4. Проверьте линтер и типы: `uv run ruff check . && uv run mypy src/os_craft`
5. Сделайте коммит: `git commit -m 'Add amazing feature'`
6. Отправьте в main: `git push origin feature/amazing-feature`
7. Откройте Pull Request.

## 📄 License / Лицензия

MIT License. Свободно используйте в коммерческих и open-source проектах.
См. файл LICENSE для подробностей.

## 🙏 Acknowledgments / Благодарности

Проект создан с любовью к чистому коду, принципу KISS и уважению к разработчикам, которые хотят писать надежные Python-приложения.
Спасибо сообществу Python за потрясающие инструменты: asyncio, contextvars, uv, ruff, mypy.

**RU:** Если у вас есть вопросы или предложения, открывайте Issue или пишите в обсуждения.

**EN:** If you have any questions or suggestions, feel free to open an Issue or start a Discussion.