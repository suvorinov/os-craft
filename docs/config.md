# Config Manager — строгая загрузка конфигурации

> [← README](../README.md) · [Примеры: config_usage.py / hot_reload_usage.py](../examples/)

## Почему это важно?

Большинство приложений берут настройки из трёх источников: значения по умолчанию, конфиг-файл и переменные окружения. Ручное склеивание этих источников быстро превращается в простыню из `os.getenv` с ручным приведением типов (`int(os.getenv("PORT")) or 8080`). Результат — баги типов, нечитаемый код и магические значения.

`load_config` из os-craft решает это одним вызовом:

* **Схема = dataclass.** Описываете конфигурацию как обычный типизированный dataclass — и получаете автодополнение в IDE и проверку типов через mypy.
* **Три источника с честным приоритетом.** Значения по умолчанию → TOML-файл → переменные окружения (ENV побеждает).
* **Автоматическое приведение типов.** Строки из ENV превращаются в `int`, `float`, `bool`, `Path` и даже `list[...]` без единого `int(...)` в вашем коде.
* **Ноль тяжёлых зависимостей.** Используется только стандартная библиотека (на Python 3.10 — официальный backport `tomli`).

## Быстрый старт

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

## Приоритет источников (от низшего к высшему)

1. Значения по умолчанию в dataclass.
2. Значения из TOML-файла (если `path` указан и файл существует).
3. Переменные окружения с префиксом `{env_prefix}_` (например, `APP_PORT`).

Переменные окружения имеют наивысший приоритет — это ключевой паттерн для контейнеров (Docker/Kubernetes), где конфиг-файл лежит в образе, а специфичные для окружения значения передаются через ENV.

## Поддерживаемые типы

| Тип поля    | Из TOML           | Из ENV (строка → тип)                                                                  |
|-------------|-------------------|----------------------------------------------------------------------------------------|
| `str`       | строка            | как есть                                                                               |
| `bool`      | `true` / `false`  | `"true"`, `"1"`, `"yes"`, `"on"` → `True`; всё остальное → `False`                     |
| `int`       | число             | `"8080"` → `8080`                                                                      |
| `float`     | число             | `"5.0"` → `5.0`                                                                        |
| `Path`      | путь (строка)     | `"/var/lib"` → `Path("/var/lib")`                                                      |
| `list[...]` | список            | `"a,b,c"` → `["a", "b", "c"]` (элементы приводятся к внутреннему типу, например `list[int]`) |

Если тип поля не входит в этот список (например, `tuple`), загрузка завершится **понятной ошибкой** — неподдерживаемый тип не нарушается молча.

## Ошибки (гарантии библиотеки)

* Обязательное поле (без дефолта), не заполненное нигде → корректный `TypeError` от dataclass, а не мусорное значение.
* Неверный тип в ENV или TOML → `ValueError` с именем поля и причиной:
  ```
  Не удалось привести значение ENV APP_PORT='not_a_number' к типу <class 'int'>.
  ```
* Передан не dataclass → `TypeError`.

## Реальный пример

Полный пример — `examples/config_usage.py`, демо-конфиг — `examples/config.toml`:

```bash
uv run python examples/config_usage.py
```

Проверка переопределения через ENV (значения из TOML должны перезаписаться):

```bash
APP_PORT=9090 APP_DEBUG=false \
APP_ALLOWED_ORIGINS="https://api.com,https://admin.com" \
uv run python examples/config_usage.py
```

Ожидаемый результат: `Port: 9090`, `Debug: False`, а строка из ENV автоматически превратилась в список `['https://api.com', 'https://admin.com']`.

---

## Горячая перезагрузка конфигурации (Hot-Reload)

`ConfigError` + `HotReloadConfig` добавляют к статичной загрузке возможность **менять настройки на лету, без перезапуска процесса**. Это критично для продолжительных сервисов (воркеров, ботов, демонов), где рестарт дорог или нежелателен.

### Как это работает

* `HotReloadConfig` при создании загружает конфигурацию через `load_config` и запускает **фоновый поток-watcher**.
* Каждые `poll_interval` секунд поток проверяет `mtime` файла.
* При изменении файла конфигурация перезагружается (с теми же приоритетами default → TOML → ENV) и вызываются все зарегистрированные коллбэки.
* Рабочий код читает актуальные значения через свойство `.config` — без блокировок и без ручных проверок.
* Watcher отказоустойчив: сбой перезагрузки или ошибка в коллбэке не убивают поток — старая конфигурация сохраняется, а проблема логируется.

### Быстрый старт

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

### Поведение и гарантии

* **Отсутствующий файл при создании** → `ConfigError`.
* **Файл удалили во время работы** → watcher ждёт восстановления, используя последнюю загруженную конфигурацию.
* **Некорректные значения в изменённом файле** → перезагрузка не применяется, остаётся прежняя конфигурация.
* **ENV по-прежнему имеет высший приоритет** и учитывается при каждой перезагрузке.
* **`stop()`** останавливает поток-watcher (с join-timeout 2 секунды).

### Пример

Пример целиком — `examples/hot_reload_usage.py` (демо-конфиг — свой `examples/hot_reload.toml`, чтобы не конфликтовать с примером `config_usage.py`).

Запуск:

```bash
uv run python examples/hot_reload_usage.py
```

Проверка: откройте `examples/hot_reload.toml`, поменяйте `max_workers` на другое значение и сохраните — через пару секунд в консоли появится лог `🔄 КОНФИГ ОБНОВЛЕН!` с новыми значениями.

## Тесты

* `tests/test_config.py` — значения по умолчанию без файлов и ENV; загрузка и парсинг TOML; неверный тип в TOML → `ValueError`; ENV-переопределение с приведением типов (включая `list[str]`); `Path` и `list[int]` из ENV; обязательное поле без значения → `TypeError` (никакого MISSING-sentinel); неподдерживаемый тип → `ValueError` с понятным сообщением; не-dataclass → `TypeError`.
* `tests/test_hot_reload.py` — отсутствие файла → `ConfigError`; перезагрузка при изменении файла + срабатывание коллбэков; падающий коллбэк не убивает watcher; битый TOML — прежняя конфигурация сохраняется; ENV-переопределение применяется при перезагрузке; `stop()` корректно останавливает поток.