"""
Тесты для модуля os_craft.shutdown.
Проверяем порядок выполнения, обработку async/sync хуков, таймауты,
идемпотентность и устойчивость к ошибкам.
"""

import asyncio
import os
import signal
import threading
import time
from functools import partial

import pytest

from os_craft import ShutdownManager


@pytest.mark.asyncio
async def test_lifo_execution_order():
    """
    Проверяем, что хуки выполняются строго в обратном порядке (LIFO).
    Это критично для корректного освобождения ресурсов.
    """
    manager = ShutdownManager(total_timeout=5.0)
    execution_order = []

    def hook_1():
        execution_order.append("hook_1")

    async def hook_2():
        execution_order.append("hook_2")

    def hook_3():
        execution_order.append("hook_3")

    manager.add_hook(hook_1)
    manager.add_hook(hook_2)
    manager.add_hook(hook_3)

    # Запускаем выполнение вручную для теста
    await manager._execute_hooks()

    # Ожидаем обратный порядок: 3, затем 2, затем 1
    assert execution_order == ["hook_3", "hook_2", "hook_1"]


@pytest.mark.asyncio
async def test_timeout_prevents_hanging():
    """
    Проверяем, что общий таймаут реально обрывает выполнение,
    если один из хуков зависает, и не дает следующему хуку выполниться,
    если время вышло.
    """
    # Ставим очень маленький таймаут для теста
    manager = ShutdownManager(total_timeout=0.6)
    execution_order = []

    async def fast_hook():
        execution_order.append("fast")

    async def hanging_hook():
        execution_order.append("hanging_start")
        await asyncio.sleep(5.0) # Имитация зависания
        execution_order.append("hanging_end") # Это не должно выполниться

    manager.add_hook(hanging_hook)
    manager.add_hook(fast_hook) # Добавлен последним, выполнится первым

    start = time.monotonic()
    await manager._execute_hooks()
    elapsed = time.monotonic() - start

    # Проверяем, что мы уложились в таймаут (с небольшим запасом на накладные расходы)
    assert elapsed < 1.5, f"Shutdown занял слишком много времени: {elapsed}s"

    # fast_hook выполнился, hanging_hook начался, но не закончился
    assert execution_order == ["fast", "hanging_start"]

    # Таймаут означает неуспешный shutdown
    # (примечание: результат проверяется в следующем тесте)


@pytest.mark.asyncio
async def test_timeout_marks_shutdown_as_failed():
    """Ожидание таймаута хука должно помечать shutdown как неуспешный."""
    manager = ShutdownManager(total_timeout=0.5)

    async def hanging_hook():
        await asyncio.sleep(5.0)

    manager.add_hook(hanging_hook)

    success = await manager._execute_hooks()
    assert success is False


@pytest.mark.asyncio
async def test_hook_exception_marks_failure_but_continues():
    """
    Ошибка в одном хуке не должна прерывать выполнение остальных,
    но должна помечать shutdown как неуспешный.
    """
    manager = ShutdownManager(total_timeout=5.0)
    execution_order = []

    def failing_hook():
        execution_order.append("fail_start")
        raise RuntimeError("boom")

    def after_hook():
        execution_order.append("after")

    manager.add_hook(failing_hook)
    manager.add_hook(after_hook) # Выполнится первым (LIFO)

    success = await manager._execute_hooks()

    # Оба хука должны отработать, несмотря на исключение
    assert execution_order == ["after", "fail_start"]
    assert success is False


@pytest.mark.asyncio
async def test_sync_hook_runs_in_executor():
    """Синхронный хук выполняется (в пуле потоков) и не блокирует loop."""
    manager = ShutdownManager(total_timeout=5.0)
    ran = []

    def blocking_sync_hook():
        ran.append("done")
        return "result"

    manager.add_hook(blocking_sync_hook)

    success = await manager._execute_hooks()
    assert ran == ["done"]
    assert success is True


@pytest.mark.asyncio
async def test_partial_hook_without_name():
    """
    Хук без атрибута __name__ (например, functools.partial) не должен
    ронять add_hook или выполнение.
    """
    manager = ShutdownManager(total_timeout=5.0)
    calls = []

    def target(arg):
        calls.append(arg)

    manager.add_hook(partial(target, "x"))

    success = await manager._execute_hooks()
    assert calls == ["x"]
    assert success is True


@pytest.mark.asyncio
async def test_add_hook_during_shutdown_raises():
    """Добавление хука во время/после shutdown должно бросать RuntimeError."""
    manager = ShutdownManager(total_timeout=5.0)

    def h():
        pass

    manager.add_hook(h)
    await manager._execute_hooks()

    with pytest.raises(RuntimeError):
        manager.add_hook(h)


@pytest.mark.asyncio
async def test_execute_hooks_is_idempotent():
    """
    Повторный вызов _execute_hooks не должен выполнять хуки заново
    и должен возвращать результат первого запуска.
    """
    manager = ShutdownManager(total_timeout=5.0)
    calls = []

    def h():
        calls.append("x")

    manager.add_hook(h)

    first = await manager._execute_hooks()
    second = await manager._execute_hooks()

    assert calls == ["x"], "Хук не должен выполняться повторно"
    assert first is True
    assert second is True  # Идемпотентно возвращает тот же результат


@pytest.mark.asyncio
async def test_execute_hooks_idempotent_preserves_failure_result():
    """
    Если первый запуск завершился с ошибкой, повторный вызов должен
    вернуть тот же (неуспешный) результат, не выполняя хуки заново.
    """
    manager = ShutdownManager(total_timeout=5.0)
    calls = []

    def failing_hook():
        calls.append("x")
        raise RuntimeError("boom")

    manager.add_hook(failing_hook)

    first = await manager._execute_hooks()
    second = await manager._execute_hooks()

    assert calls == ["x"], "Хук не должен выполняться повторно"
    assert first is False
    assert second is False


def _run_app_with_hooks(hooks, raise_in_hook=False):
    """
    Вспомогательная функция: запускает "приложение" с зарегистрированными
    хуками в отдельном asyncio.run и отправляет SIGINT себе в процессе.
    Возвращает exit_code менеджера после завершения.
    """
    async def main():
        manager = ShutdownManager(total_timeout=5.0)

        def make_hook(h, raise_now):
            def wrapped():
                if raise_now:
                    raise RuntimeError("hook failed")
                return h()
            return wrapped

        for h in hooks:
            manager.add_hook(make_hook(h, raise_in_hook))
        manager.attach_to_signals()

        # Отправляем SIGINT через короткое время, пока работает loop
        def send_signal():
            time.sleep(0.3)
            os.kill(os.getpid(), signal.SIGINT)

        threading.Thread(target=send_signal, daemon=True).start()

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass  # Менеджер корректно отменил главную задачу после shutdown

        return manager

    return asyncio.run(main())


def test_signal_triggers_graceful_shutdown_success():
    """
    Интеграционный тест: реальный SIGINT вызывает хуки, корректно завершает
    главную задачу без "Task exception was never retrieved" и возвращает
    exit_code = 0.
    """
    ran = []

    def hook():
        ran.append("x")

    manager = _run_app_with_hooks([hook])

    assert ran == ["x"]
    assert manager.exit_code == 0


def test_signal_failure_sets_exit_code_1():
    """
    Если хук упал при получении SIGINT, exit_code должен быть 1,
    чтобы оркестратор узнал о неудачной очистке.
    """
    manager = _run_app_with_hooks([lambda: None], raise_in_hook=True)

    assert manager.exit_code == 1
