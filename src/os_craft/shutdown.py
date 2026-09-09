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
from typing import Any

# Настраиваем логгер модуля. 
# Использование __name__ позволяет легко фильтровать логи по пространству имен 'os_craft'.
logger = logging.getLogger(__name__)

# Минимальный таймаут для одного хука (в секундах).
# Защищает от мгновенных таймаутов первого хука из-за погрешности таймера,
# но не даёт хуку превысить общий бюджет больше, чем на эту величину.
_MIN_HOOK_TIMEOUT = 0.5

# Определяем тип для хука завершения. 
# Мы поддерживаем как обычные (синхронные) функции, так и async-функции.
ShutdownHook = Callable[[], None | Awaitable[None]]


def _hook_name(hook: ShutdownHook) -> str:
    """Возвращает человекочитаемое имя хука для логов.

    Хук может не иметь ``__name__`` (например, ``functools.partial`` или
    callable-класс), поэтому не полагаемся на него без fallback.
    """
    return getattr(hook, "__name__", repr(hook))


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
    # Результат последнего запуска _execute_hooks (для идемпотентных повторных вызовов).
    _last_success: bool = field(default=True, init=False, repr=False)
    # Код выхода для завершения процесса после graceful shutdown.
    _exit_code: int = field(default=0, init=False, repr=False)
    # Ссылка на "главную" задачу приложения (обычно корутина, в которой
    # был вызван attach_to_signals). Её мы корректно отменяем после хуков,
    # чтобы asyncio.run() вернулся без ошибок.
    _main_task: asyncio.Task[Any] | None = field(default=None, init=False, repr=False)

    @property
    def exit_code(self) -> int:
        """
        Код выхода, с которым следует завершить процесс после shutdown.

        Равен 0 при успешной очистке и 1, если какой-либо хук упал или
        превысил таймаут. Должен читаться после завершения главной корутины
        (например, после ``asyncio.run(main())``).
        """
        return self._exit_code

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
        logger.debug(f"Зарегистрирован хук завершения: {_hook_name(hook)}")

    async def _execute_hooks(self) -> bool:
        """
        Внутренний метод: последовательное выполнение хуков с контролем общего таймаута.
        
        Мы используем один общий таймаут на все хуки, а не на каждый отдельно, 
        чтобы гарантировать, что весь процесс shutdown уложится в окно, 
        отведенное оркестратором (например, Kubernetes terminationGracePeriodSeconds).
        
        Метод идемпотентен: повторный вызов (например, при повторном сигнале) 
        не выполняет хуки заново, а возвращает результат уже завершённого запуска.
        
        Returns:
            True, если все хуки выполнились без ошибок и в пределах таймаута.
            False, если хотя бы один хук упал, превысил таймаут или был прерван
            общим истечением времени.
        """
        # Идемпотентность: если shutdown уже идёт или завершился, ничего не делаем заново.
        if self._is_shutting_down:
            logger.warning("Graceful shutdown уже запущен. Повторный вызов игнорируется.")
            return self._last_success

        self._is_shutting_down = True
        logger.info(f"Начинаем graceful shutdown. Зарегистрировано хуков: {len(self._hooks)}")

        success = True
        start_time = time.monotonic()

        # Выполняем хуки в обратном порядке (LIFO - Last In, First Out)
        for hook in reversed(self._hooks):
            elapsed = time.monotonic() - start_time

            # Проверяем, не истек ли общий лимит времени
            if elapsed >= self.total_timeout:
                logger.error(
                    f"Превышен общий таймаут shutdown ({self.total_timeout:.2f}s). "
                    "Оставшиеся хуки пропускаются."
                )
                success = False
                break

            # Вычисляем оставшееся время для текущего хука.
            # Минимум _MIN_HOOK_TIMEOUT, чтобы не падать мгновенно на первом хуке
            # из-за погрешности таймера.
            hook_timeout = max(_MIN_HOOK_TIMEOUT, self.total_timeout - elapsed)

            try:
                logger.info(
                    f"Выполняем хук: {_hook_name(hook)} (доступно {hook_timeout:.2f}s)"
                )

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
                        timeout=hook_timeout,
                    )

            except asyncio.TimeoutError:
                logger.error(
                    f"Хук {_hook_name(hook)} не уложился в таймаут {hook_timeout:.2f}s. Пропускаем."
                )
                success = False
            except Exception:
                # КРИТИЧНО ВАЖНО: Мы НИКОГДА не прерываем цикл shutdown из-за ошибки в одном хуке.
                # Мы логируем исключение и переходим к следующему хуку, чтобы дать шанс очиститься остальным ресурсам.
                logger.exception(f"Необработанная ошибка в хуке {_hook_name(hook)}. Продолжаем.")
                success = False

        self._last_success = success

        if success:
            logger.info("Процесс graceful shutdown успешно завершен.")
        else:
            logger.error("Graceful shutdown завершен с ошибками (см. логи выше).")
        return success

    def attach_to_signals(self) -> None:
        """
        Подписывается на сигналы ОС (SIGINT, SIGTERM) для инициирования shutdown.

        Должен вызываться изнутри запущенного event loop. Активный loop берётся
        автоматически через ``asyncio.get_running_loop()``, поэтому передавать
        его явно не нужно.

        После завершения хуков процесс корректно завершается: с кодом 0, если
        очистка прошла успешно, и с кодом 1, если какой-либо хук упал или
        превысил таймаут. Повторные сигналы не запускают shutdown заново.

        Важно: этот метод должен вызываться изнутри основной корутины приложения
        (например, из ``main()``). В этом случае менеджер запоминает её как
        "главную задачу" и после выполнения хуков корректно завершает её,
        чтобы ``asyncio.run(main())`` вернулся без ошибок, а код выхода можно
        было получить через :attr:`exit_code`.
        """
        def _signal_handler() -> None:
            # Игнорируем повторные сигналы: shutdown уже идёт или завершён.
            if self._is_shutting_down:
                logger.info("Повторный сигнал остановки получен, но shutdown уже запущен.")
                return

            logger.info("Получен сигнал остановки ОС. Инициируем graceful shutdown...")

            async def _shutdown_task() -> None:
                """Выполняет хуки и затем чисто завершает работу приложения."""
                success = await self._execute_hooks()
                self._exit_code = 0 if success else 1

                # Корректно завершаем главную задачу приложения, чтобы
                # asyncio.run() вернулся штатно (без "Task exception was never retrieved").
                task = self._main_task
                if task is not None and not task.done():
                    task.cancel()
                else:
                    # Fallback: если главная задача неизвестна (или уже завершена),
                    # просто останавливаем event loop.
                    asyncio.get_running_loop().stop()

            asyncio.create_task(_shutdown_task(), name="os-craft-shutdown-task")

        # Определяем главную задачу: ту, в которой вызван этот метод.
        # Обычно это и есть корутина main(), запущенная через asyncio.run().
        self._main_task = asyncio.current_task()
        loop = asyncio.get_running_loop()
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
