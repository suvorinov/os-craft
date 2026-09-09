"""
Модуль для легковесного профилирования производительности и памяти.

Предоставляет декоратор @track_perf и контекстный менеджер track_block,
которые измеряют время выполнения и потребление памяти через tracemalloc.
Работает с нулевым оверхедом, если не включен через переменную окружения.
"""

import functools
import inspect
import logging
import os
import time
import tracemalloc
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypedDict, cast

logger = logging.getLogger(__name__)

# Глобальный флаг: читаем один раз при импорте для максимальной скорости.
# По умолчанию выключено, чтобы не влиять на продакшн.
_IS_ENABLED = os.environ.get("OS_CRAFT_ENABLE_PERF", "0").lower() in ("1", "true", "yes")
_MEMORY_WARN_THRESHOLD_MB = float(os.environ.get("OS_CRAFT_PERF_MEM_WARN_MB", "10.0"))


class PerfMetrics(TypedDict):
    """Метрики блока/функции, передаваемые в коллбэк профилировщика."""

    name: str
    duration_ms: float
    mem_diff_mb: float
    peak_mem_mb: float


def _format_memory(bytes_val: int) -> str:
    """Форматирует байты в читаемый вид (KB, MB)."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.2f} KB"
    return f"{bytes_val / (1024 * 1024):.2f} MB"


def _get_top_allocations(limit: int = 3) -> str:
    """
    Возвращает топ-N строк кода по потреблению памяти.

    Фильтрует внутренние аллокации tracemalloc, logging и самого модуля perf.
    """
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')

    lines = []
    count = 0
    for stat in top_stats:
        if count >= limit:
            break
        if not stat.traceback:
            continue
        frame = stat.traceback[0]
        filename = frame.filename
        # ФИЛЬТРАЦИЯ: Убираем мусор от внутренних аллокаций
        if (
            'tracemalloc.py' in filename
            or 'logging/__init__.py' in filename
            or 'perf.py' in filename
        ):
            continue
        lines.append(f"  - {filename}:{frame.lineno} ({_format_memory(stat.size)})")
        count += 1

    return "\n".join(lines) if lines else "  (нет значимых аллокаций)"


@contextmanager
def track_block(name: str, callback: Callable[[PerfMetrics], None] | None = None) -> Iterator[None]:
    """
    Контекстный менеджер для замера времени и памяти блока кода.

    Args:
        name: Имя блока для логирования.
        callback: Опциональная функция, которая получит dict с метриками
                  (для интеграции с Prometheus/StatsD).
    """
    if not _IS_ENABLED:
        yield
        return

    if not tracemalloc.is_tracing():
        tracemalloc.start()

    start_time = time.perf_counter()
    start_mem, _ = tracemalloc.get_traced_memory()

    try:
        yield
    finally:
        end_time = time.perf_counter()
        end_mem, end_peak = tracemalloc.get_traced_memory()

        duration_ms = (end_time - start_time) * 1000
        mem_diff = end_mem - start_mem

        metrics: PerfMetrics = {
            "name": name,
            "duration_ms": round(duration_ms, 2),
            "mem_diff_mb": round(mem_diff / (1024 * 1024), 2),
            # Пик traced-аллокаций процесса (не RSS, а именно то, что ловит tracemalloc)
            "peak_mem_mb": round(end_peak / (1024 * 1024), 2),
        }

        # Логирование
        log_level = logging.WARNING if metrics["peak_mem_mb"] > _MEMORY_WARN_THRESHOLD_MB else logging.INFO
        logger.log(
            log_level,
            f"[PERF] {name} | Время: {metrics['duration_ms']}ms | "
            f"Дельта памяти: {metrics['mem_diff_mb']} MB | Пик: {metrics['peak_mem_mb']} MB",
        )

        if metrics["peak_mem_mb"] > _MEMORY_WARN_THRESHOLD_MB:
            logger.warning(f"[PERF] Высокое потребление памяти в '{name}'. Топ аллокаций:\n{_get_top_allocations()}")

        if callback:
            try:
                callback(metrics)
            except Exception as e:
                logger.error(f"Ошибка в callback профилировщика: {e}")


def track_perf(
    func: Callable[..., Any] | None = None,
    *,
    callback: Callable[[PerfMetrics], None] | None = None,
) -> Callable[..., Any]:
    """
    Декоратор для замера производительности функций и методов.

    Может также применяться к классу (обернет все публичные методы).
    """

    def decorator(wrapped: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.isclass(wrapped):
            # Если декоратор повешен на класс, мы оборачиваем только его
            # публичные callable-атрибуты (методы) в теле самого класса.
            cls = cast(type[Any], wrapped)
            for attr_name, attr_value in cls.__dict__.items():
                if not attr_name.startswith("_") and callable(attr_value):
                    setattr(cls, attr_name, decorator(attr_value))
            return wrapped

        @functools.wraps(wrapped)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _IS_ENABLED:
                return wrapped(*args, **kwargs)

            # Формируем читаемое имя: ClassName.method_name или function_name
            qualname = getattr(wrapped, "__qualname__", "") or getattr(wrapped, "__name__", "unknown")
            with track_block(f"FUNC:{qualname}", callback=callback):
                return wrapped(*args, **kwargs)

        return wrapper

    if func is None:
        return decorator
    return decorator(func)