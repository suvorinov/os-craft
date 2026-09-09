"""
Модуль для строгой, но простой загрузки конфигураций.

Использует стандартные dataclasses для определения схемы, 
поддерживает загрузку значений из TOML-файла и их перезапись 
через переменные окружения (ENV).
"""

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar, get_args, get_origin

# Поддержка Python 3.10 (tomli) и 3.11+ (встроенный tomllib).
# tomli объявлен в зависимостях с маркером python_version < '3.11'.
try:
    import tomllib  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - зависит от версии интерпретатора
    import tomli as tomllib  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

T = TypeVar("T")

class ConfigError(Exception):
    """Исключение, возникающее при ошибках валидации или загрузки конфигурации."""
    pass

def _cast_value(value: Any, target_type: Any) -> Any:
    """
    Приводит значение (строку из ENV или значение из TOML) к типу поля dataclass.

    Неподдерживаемые типы полей не нарушаются молча: вместо этого мы бросаем
    понятную ошибку со списком поддерживаемых типов. Это гарантирует, что
    "строгая" загрузка конфигурации действительно остаётся строгой.
    """
    # TOML уже отдаёт типизированные значения — если тип совпал, отдаём как есть
    if target_type is Any:
        return value
    if target_type is str:
        return value if isinstance(value, str) else str(value)
    if target_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
    elif target_type is int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value)
    elif target_type is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            return float(value)
    elif target_type is Path:
        if isinstance(value, Path):
            return value
        if isinstance(value, str):
            return Path(value)

    # Поддержка list[...] (например, list[str], list[int], list[Path]):
    # строка "a,b,c" из ENV превращается в ["a", "b", "c"], элементы при этом
    # приводятся к внутреннему типу списка.
    origin = get_origin(target_type)
    if origin is list:
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, list):
            items = list(value)
        else:
            raise ValueError(
                f"Ожидался список или строка со значениями через запятую, получено: {value!r}"
            )
        args = get_args(target_type)
        return [_cast_value(item, args[0]) for item in items] if args else items

    raise ValueError(
        f"Тип {target_type!r} не поддерживается для поля конфигурации. "
        "Поддерживаются: str, bool, int, float, Path, list[...]."
    )


def load_config(config_cls: type[T], env_prefix: str = "APP", file_path: Path | None = None) -> T:
    """
    Загружает и валидирует конфигурацию на основе dataclass.

    Порядок приоритета значений (от низшего к высшему):
    1. Значения по умолчанию в dataclass.
    2. Значения из TOML-файла (если указан file_path).
    3. Переменные окружения с префиксом {env_prefix}_ (например, APP_DB_HOST).

    Args:
        config_cls: Класс dataclass, описывающий схему конфигурации.
        env_prefix: Префикс для переменных окружения (по умолчанию "APP").
        file_path: Путь к TOML-файлу с конфигурацией (опционально).

    Returns:
        Экземпляр config_cls, полностью заполненный и типизированный.

    Raises:
        ValueError: Если тип значения не может быть приведён к целевому типу.
        TypeError: Если переданный класс не является dataclass или обязательное
                   поле не задано ни дефолтом, ни TOML, ни ENV.
    """
    if not is_dataclass(config_cls):
        raise TypeError(f"Ожидался dataclass, получен: {type(config_cls)}")

    # 1. Значения по умолчанию. Поля без дефолта (обязательные) пропускаем:
    # если они не придут ни из TOML, ни из ENV, dataclass сам бросит
    # корректный TypeError о пропущенном аргументе — вместо молчаливого
    # прокрадывания sentinel-значения MISSING в конфигурацию.
    config_dict: dict[str, Any] = {}
    for item in fields(config_cls):
        if item.default_factory is not MISSING:
            config_dict[item.name] = item.default_factory()
        elif item.default is not MISSING:
            config_dict[item.name] = item.default

    # 2. Перезаписываем значениями из TOML-файла (если он существует)
    if file_path and file_path.exists():
        logger.info(f"Загрузка конфигурации из файла: {file_path}")
        with open(file_path, "rb") as f:
            toml_data = tomllib.load(f)

        for item in fields(config_cls):
            if item.name not in toml_data:
                continue
            try:
                config_dict[item.name] = _cast_value(toml_data[item.name], item.type)
            except (ValueError, TypeError) as e:
                raise ValueError(
                    f"Неверное значение в TOML для поля {item.name}: {e}"
                ) from None
            logger.debug(f"Применено значение из TOML: {item.name}={config_dict[item.name]}")

    # 3. Перезаписываем значениями из переменных окружения (наивысший приоритет)
    prefix = f"{env_prefix}_"
    env_overrides = 0

    for item in fields(config_cls):
        env_key = f"{prefix}{item.name.upper()}"
        env_value = os.environ.get(env_key)

        if env_value is None:
            continue

        try:
            config_dict[item.name] = _cast_value(env_value, item.type)
            env_overrides += 1
            logger.debug(f"Перезаписано из ENV: {env_key}={config_dict[item.name]}")
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Не удалось привести значение ENV {env_key}='{env_value}' "
                f"к типу {item.type}. Ошибка: {e}"
            ) from None

    if env_overrides > 0:
        logger.info(f"Применено {env_overrides} переопределений из переменных окружения.")

    # 4. Создаем и возвращаем финальный экземпляр конфигурации
    return config_cls(**config_dict)

class HotReloadConfig(Generic[T]):
    """
    Менеджер конфигурации с поддержкой горячего обновления (Hot-Reload).
    
    Периодически опрашивает файл конфигурации. При обнаружении изменений
    перезагружает конфигурацию и вызывает зарегистрированные коллбэки.
    """
    
    def __init__(
        self, 
        config_cls: type[T], 
        file_path: Path, 
        env_prefix: str = "APP", 
        poll_interval: float = 2.0
    ):
        if not file_path.exists():
            raise ConfigError(f"Файл конфигурации не найден: {file_path}")
            
        self._config_cls = config_cls
        self._file_path = file_path
        self._env_prefix = env_prefix
        self._poll_interval = poll_interval
        
        self._current_config: T = load_config(config_cls, env_prefix, file_path)
        self._last_mtime = self._file_path.stat().st_mtime
        self._callbacks: list[Callable[[T], None]] = []
        
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._watcher, daemon=True, name="os-craft-config-watcher")
        self._thread.start()
        
        logger.info(f"Hot-Reload менеджер запущен для {file_path} (интервал: {poll_interval}s)")

    def _watcher(self) -> None:
        """Фоновый поток для отслеживания изменений файла."""
        while not self._stop_event.is_set():
            # Ждем либо сигнала остановки, либо истечения интервала
            if self._stop_event.wait(self._poll_interval):
                break
                
            try:
                current_mtime = self._file_path.stat().st_mtime
                if current_mtime > self._last_mtime:
                    logger.info(f"Обнаружено изменение в {self._file_path}. Перезагрузка конфигурации...")
                    self._last_mtime = current_mtime
                    
                    # Перезагружаем конфиг
                    new_config = load_config(self._config_cls, self._env_prefix, self._file_path)
                    self._current_config = new_config
                    
                    # Триггерим коллбэки (по снапшоту, чтобы add_callback
                    # во время итерации не ронял RuntimeError)
                    for cb in list(self._callbacks):
                        try:
                            cb(new_config)
                        except Exception as e:
                            logger.exception(f"Ошибка в коллбэке конфигурации: {e}")
                            
            except FileNotFoundError:
                logger.warning(f"Файл конфигурации {self._file_path} был удален. Ожидание восстановления...")
            except Exception as e:
                logger.exception(f"Ошибка при проверке конфигурации: {e}")

    def add_callback(self, callback: Callable[[T], None]) -> None:
        """Регистрирует функцию, которая будет вызвана при обновлении конфигурации."""
        self._callbacks.append(callback)

    @property
    def config(self) -> T:
        """Возвращает текущую актуальную конфигурацию (thread-safe в рамках GIL Python)."""
        return self._current_config

    def stop(self) -> None:
        """Останавливает фоновый поток (вызывать при завершении приложения)."""
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        logger.info("Hot-Reload менеджер остановлен.")