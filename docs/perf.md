# perf — профилирование производительности и памяти

> [← README](../README.md) · [Пример: perf_usage.py](../examples/perf_usage.py)

## Что это и зачем

`track_perf` (декоратор) и `track_block` (контекстный менеджер) измеряют **время выполнения** и **потребление памяти** через стандартный `tracemalloc`. Минимум зависимостей (нулевые), ноль оверхеда в проде — профилирование включается только явно.

### Включение

По умолчанию всё выключено. Флаг читается при импорте модуля:

| Переменная окружения                 | Значение по умолчанию | Назначение                                                        |
|--------------------------------------|----------------------|------------------------------------------------------------------|
| `OS_CRAFT_ENABLE_PERF`               | `0`                  | `1` / `true` / `yes` — включить замеры                            |
| `OS_CRAFT_PERF_MEM_WARN_MB`          | `10.0`               | Порог пиковой памяти (MB), выше которого пишется WARNING с топ-аллокациями |

```bash
OS_CRAFT_ENABLE_PERF=1 uv run python your_app.py
```

## track_block — замер произвольного блока кода

```python
import logging
logging.basicConfig(level=logging.INFO)

from os_craft import track_block

def handle_request():
    with track_block("HTTP:/api/users"):
        result = fetch_users()   # какая-то работа
        _ = {f"key_{i}": i for i in range(1_000_000)}
        return result
```

По завершении блока в лог пишется:

```
INFO | [PERF] HTTP:/api/users | Время: 12.5ms | Дельта памяти: 0.2 MB | Пик: 4.1 MB
```

Если пик памяти превысил `OS_CRAFT_PERF_MEM_WARN_MB`, уровень повышается до WARNING и дополнительно печатаются топ-3 строк кода по аллокациям (внутренние аллокации `tracemalloc`, `logging` и самого `perf.py` отфильтровываются).

## track_perf — замер функций и классов

Обёртка над `track_block` для функций и методов:

```python
from os_craft import track_perf

@track_perf
def heavy_computation():
    data = [i * 2 for i in range(2_000_000)]
    return sum(data)
```

Имя блока — `FUNC:<qualname>` (например, `FUNC:heavy_computation`).

### Применение к классу

Декоратор можно повесить на класс — он обернёт **все публичные методы** (не начинающиеся с `_`), объявленные прямо в теле класса:

```python
@track_perf
class DataProcessor:
    def load_data(self): ...
    def process_data(self): ...

    def _internal(self):    # не попадёт под замер
        ...
```

`__init__` и приватные методы не оборачиваются. Наследуемые методы тоже — оборачиваются только объявленные в самом классе.

## Коллбэк-метрики (Prometheus / StatsD)

Оба инструмента принимают `callback: Callable[[PerfMetrics], None]` — функция получит словарь с метриками после каждого замера:

```python
from os_craft import track_perf

def send_to_statsd(metrics):
    statsd.gauge(f"perf.{metrics['name']}", metrics["duration_ms"])

@track_perf(callback=send_to_statsd)
def handle_request():
    ...
```

Тип `PerfMetrics` (TypedDict):

| Поле           | Тип    | Описание                                           |
|----------------|--------|----------------------------------------------------|
| `name`         | `str`  | Имя блока/функции                                  |
| `duration_ms`  | `float`| Время выполнения, мс                                |
| `mem_diff_mb`  | `float`| Дельта traced-аллокаций за время блока, MB          |
| `peak_mem_mb`  | `float`| Пик traced-аллокаций процесса, MB                   |

> Обратите внимание: `peak_mem_mb` — это пик **traced-аллокаций** (`tracemalloc`), а не полный RSS процесса. Для оценки полного footprint смотрите `psutil`/`resource` при необходимости.
>
> Ошибка в коллбэке не роняет приложение: она логируется и замер продолжается.

## Пример

Полный пример — `examples/perf_usage.py`:

```bash
# без профилирования — оверхед нулевой
uv run python examples/perf_usage.py

# с профилированием и пониженным порогом предупреждений
OS_CRAFT_ENABLE_PERF=1 OS_CRAFT_PERF_MEM_WARN_MB=5.0 uv run python examples/perf_usage.py
```

## Тесты

Модуль покрыт тестами в `tests/test_perf.py`: форматирование памяти, топ аллокаций, отключённый и включённый режимы, декоратор функций и классов, коллбэки-метрики, обработка ошибок коллбэка.