"""
Пример использования os_craft.config для строгой типизированной загрузки настроек.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from os_craft import load_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

# 1. Описываем схему конфигурации как обычный dataclass.
# Это дает нам автодополнение в IDE и строгую типизацию через mypy.
@dataclass
class AppConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    # Поддержка списков из коробки!
    allowed_origins: list[str] = field(default_factory=list)
    # Можно добавить и более сложные типы, если расширить _cast_value
    db_timeout: float = 5.0

def main():
    # Определяем путь к файлу конфигурации относительно этого скрипта
    config_file = Path(__file__).parent / "config.toml"
    
    # 2. Загружаем конфиг. 
    # Префикс "APP" означает, что мы будем искать переменные вроде APP_PORT, APP_DEBUG и т.д.
    config = load_config(
        config_cls=AppConfig,
        env_prefix="APP",
        file_path=config_file
    )
    
    print("\n" + "="*50)
    print("✅ ЗАГРУЖЕННАЯ КОНФИГУРАЦИЯ:")
    print(f"Host: {config.host} (type: {type(config.host).__name__})")
    print(f"Port: {config.port} (type: {type(config.port).__name__})")
    print(f"Debug: {config.debug} (type: {type(config.debug).__name__})")
    print(f"Allowed Origins: {config.allowed_origins} (type: {type(config.allowed_origins).__name__})")
    print(f"DB Timeout: {config.db_timeout} (type: {type(config.db_timeout).__name__})")
    print("="*50 + "\n")

    # Демонстрация того, как ENV переопределяет файл:
    # Если бы мы запустили этот скрипт так:
    # APP_PORT=9090 APP_DEBUG=false APP_ALLOWED_ORIGINS="https://api.com,https://admin.com" uv run python examples/config_usage.py
    # Мы бы увидели, что значения из config.toml были полностью перезаписаны, 
    # а строка "https://api.com,https://admin.com" автоматически превратилась в list[str]!

if __name__ == "__main__":
    main()