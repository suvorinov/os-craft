"""
Тесты для модуля os_craft.shutdown.
Проверяем порядок выполнения, обработку async/sync хуков и таймауты.
"""

import asyncio

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

    start = asyncio.get_event_loop().time()
    await manager._execute_hooks()
    elapsed = asyncio.get_event_loop().time() - start

    # Проверяем, что мы уложились в таймаут (с небольшим запасом на накладные расходы)
    assert elapsed < 1.5, f"Shutdown занял слишком много времени: {elapsed}s"
    
    # fast_hook выполнился, hanging_hook начался, но не закончился
    assert execution_order == ["fast", "hanging_start"]