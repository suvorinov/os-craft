"""
Пример использования Hot-Reload конфигурации в os-craft.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from os_craft import ConfigError, HotReloadConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")

@dataclass
class AppSettings:
    # Обязательное поле (нет дефолта)
    app_name: str
    # Поля с дефолтами
    max_workers: int = 4
    feature_flag_new_ui: bool = False

def on_config_change(new_config: AppSettings):
    """Этот коллбэк сработает автоматически при изменении config.toml"""
    logging.info(f"🔄 КОНФИГ ОБНОВЛЕН! Новые значения: workers={new_config.max_workers}, new_ui={new_config.feature_flag_new_ui}")

def main():
    # Используем СВОЙ файл конфигурации, а не общий examples/config.toml,
    # чтобы не мешать примеру config_usage.py (у него другая схема).
    config_file = Path(__file__).parent / "hot_reload.toml"
    
    # Создаём файл с совместимой схемой, если его ещё нет
    if not config_file.exists():
        config_file.write_text('app_name = "MyAwesomeApp"\nmax_workers = 4\nfeature_flag_new_ui = false')
        logging.info(f"Создан тестовый файл {config_file}")

    try:
        # Инициализируем менеджер. Он сразу загрузит конфиг и запустит фоновый поток.
        config_manager = HotReloadConfig(
            config_cls=AppSettings,
            file_path=config_file,
            env_prefix="APP",
            poll_interval=2.0  # Проверяем файл каждые 2 секунды
        )
        
        # Регистрируем коллбэк
        config_manager.add_callback(on_config_change)
        
        logging.info("🚀 Приложение запущено. Попробуйте изменить файл config.toml в другом редакторе!")
        logging.info("Например, поменяйте max_workers на 8 или feature_flag_new_ui на true и сохраните файл.")
        
        # Имитация долгой работы приложения
        while True:
            # Мы всегда читаем актуальные данные через .config
            current_cfg = config_manager.config
            # logging.debug(f"Текущие workers: {current_cfg.max_workers}")
            time.sleep(1)
            
    except ConfigError as e:
        logging.error(f"❌ Ошибка конфигурации: {e}")
    except KeyboardInterrupt:
        logging.info("\n🛑 Получен сигнал остановки. Корректное завершение...")
    finally:
        # Важно: останавливаем фоновый поток при выходе
        if 'config_manager' in locals():
            config_manager.stop()

if __name__ == "__main__":
    main()