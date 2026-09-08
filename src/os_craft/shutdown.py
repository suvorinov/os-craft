"""
Модуль управления грациозным завершением работы приложения.

Предоставляет инструменты для перехвата сигналов ОС (SIGTERM, SIGINT)
и упорядоченного освобождения ресурсов с соблюдением таймаутов.
"""

import asyncio
import inspect
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

# Настраиваем логгер модуля. 
# Использование __name__ позволяет легко фильтровать логи по пространству имен 'os_craft'.
logger = logging.getLogger(__name__)

# Определяем тип для хука завершения. 
# Мы поддерживаем как обычные (синхронные) функции, так и async-функции.
ShutdownHook = Callable[[], None | Awaitable[None]]


@dataclass
class ShutdownManager:
    """
    Менеджер грациозного завершения работы приложения.

    Позволяет зарегистрировать хуки (функции очистки), которые будут вызваны 
    в обратном порядке (LIFO) при получении сигнала остановки от ОС.
    
    Принцип LIFO критически важен: мы должны сначала остановить прием новых 
    запросов, затем дождаться завершения текущих, и только потом закрывать 
    соединения с базами данных или кэшем.

    Attributes:
        total_timeout: Максимальное время (в секундах) на выполнение всех хуков.
                       По истечении этого времени процесс будет прерван, чтобы 
                       не мешать ОС убить зависшее приложение (например, через SIGKILL).
    """
    
    total_timeout: float = 10.0
    
    # Внутреннее состояние. Используем field(default_factory=...), 
    # чтобы список не разделялся между разными экземплярами класса.
    _hooks: list[ShutdownHook] = field(default_factory=list, init=False, repr=False)
    _is_shutting_down: bool = field(default=False, init=False, repr=False)

    def add_hook(self, hook: ShutdownHook) -> None:
        """
        Добавляет хук в очередь завершения.

        Args:
            hook: Функция (синхронная или асинхронная) без аргументов, 
                  выполняющая очистку ресурсов.

        Raises:
            RuntimeError: Если попытаться добавить хук во время уже идущего процесса завершения.
        """
        if self._is_shutting_down:
            raise RuntimeError("Невозможно добавить хук: процесс завершения уже запущен.")
        
        self._hooks.append(hook)
        logger.debug(f"Зарегистрирован хук завершения: {hook.__name__}")

    async def _execute_hooks(self) -> None:
        """
        Внутренний метод: последовательное выполнение хуков с контролем общего таймаута.
        
        Мы используем один общий таймаут на все хуки, а не на каждый отдельно, 
        чтобы гарантировать, что весь процесс shutdown уложится в окно, 
        отведенное оркестратором (например, Kubernetes terminationGracePeriodSeconds).
        """
        self._is_shutting_down = True
        logger.info(f"Начинаем graceful shutdown. Зарегистрировано хуков: {len(self._hooks)}")
        
        start_time = time.monotonic()
        
        # Выполняем хуки в обратном порядке (LIFO - Last In, First Out)
        for hook in reversed(self._hooks):
            elapsed = time.monotonic() - start_time
            
            # Проверяем, не истек ли общий лимит времени
            if elapsed >= self.total_timeout:
                logger.error(f"Превышен общий таймаут shutdown ({self.total_timeout}s). Прерываем выполнение.")
                break

            # Вычисляем оставшееся время для текущего хука. 
            # Минимум 0.5 секунды, чтобы избежать мгновенных таймаутов из-за погрешностей таймера.
            hook_timeout = max(0.5, self.total_timeout - elapsed)
            
            try:
                logger.info(f"Выполняем хук: {hook.__name__} (доступно {hook_timeout:.2f}s)")
                
                # НЕОЧЕВИДНОЕ РЕШЕНИЕ: Мы должны поддерживать и sync, и async хуки.
                # Если хук асинхронный, мы просто ждем его с таймаутом.
                if inspect.iscoroutinefunction(hook):
                    await asyncio.wait_for(hook(), timeout=hook_timeout)
                else:
                    # Если хук синхронный, мы НЕ вызываем его напрямую в event loop, 
                    # потому что он может заблокировать весь цикл (например, долгий close() сокета).
                    # Вместо этого мы выполняем его в пуле потоков по умолчанию.
                    loop = asyncio.get_running_loop()
                    await asyncio.wait_for(
                        loop.run_in_executor(None, hook), 
                        timeout=hook_timeout
                    )
                    
            except asyncio.TimeoutError:
                logger.error(f"Хук {hook.__name__} не уложился в таймаут {hook_timeout}s. Пропускаем.")
            except Exception as e:
                # КРИТИЧНО ВАЖНО: Мы НИКОГДА не прерываем цикл shutdown из-за ошибки в одном хуке.
                # Мы логируем исключение и переходим к следующему хуку, чтобы дать шанс очиститься остальным ресурсам.
                logger.exception(f"Необработанная ошибка в хуке {hook.__name__}: {e}")

        logger.info("Процесс graceful shutdown успешно завершен.")

    def attach_to_signals(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Подписывается на сигналы ОС (SIGINT, SIGTERM) для инициирования shutdown.

        Args:
            loop: Активный экземпляр asyncio event loop.
        """
    def _signal_handler() -> None:
        logger.info("Получен сигнал остановки ОС. Инициируем graceful shutdown...")
        
        async def _shutdown_and_exit() -> None:
            """Выполняет хуки и затем завершает процесс."""
            await self._execute_hooks()
            # Принудительно завершаем процесс после успешного shutdown
            import sys
            sys.exit(0)
        
        asyncio.create_task(_shutdown_and_exit(), name="os-craft-shutdown-task")
        # Пытаемся подписаться на стандартные сигналы завершения.
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # На Windows (особенно с ProactorEventLoop) add_signal_handler не поддерживается.
                # Мы не падаем, а просто предупреждаем. Для Windows fallback можно сделать через signal.signal,
                # но для серверных Linux-приложений (наш основной таргет) этого достаточно.
                logger.warning(f"Сигнал {sig.name} не поддерживается текущим event loop'ом (возможно, Windows).")
            except Exception as e:
                logger.error(f"Не удалось подписаться на сигнал {sig.name}: {e}")
