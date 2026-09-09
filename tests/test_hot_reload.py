"""
Тесты для HotReloadConfig: горячая перезагрузка конфигурации из файла.
"""

import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from os_craft import ConfigError, HotReloadConfig, load_config


@dataclass
class SampleConfig:
    app_name: str
    max_workers: int = 4
    feature_flag_new_ui: bool = False


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    """Ждёт выполнения условия с дедлайном (для асинхронного watcher-потока)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text('app_name = "App"\nmax_workers = 4\nfeature_flag_new_ui = false')
    return path


def test_missing_file_raises_config_error(tmp_path: Path):
    missing = tmp_path / "nope.toml"
    with pytest.raises(ConfigError, match="Файл конфигурации не найден"):
        HotReloadConfig(SampleConfig, file_path=missing, env_prefix="TEST")


def test_initial_config_loaded(config_file: Path):
    manager = HotReloadConfig(SampleConfig, file_path=config_file, env_prefix="TEST", poll_interval=0.05)
    try:
        assert manager.config.app_name == "App"
        assert manager.config.max_workers == 4
        assert manager.config.feature_flag_new_ui is False
    finally:
        manager.stop()


def test_config_reloads_on_file_change(config_file: Path):
    manager = HotReloadConfig(SampleConfig, file_path=config_file, env_prefix="TEST", poll_interval=0.05)
    callbacks_called = []

    def on_change(new_config: SampleConfig):
        callbacks_called.append(new_config)

    manager.add_callback(on_change)

    try:
        # Меняем файл: увеличиваем workers и включаем флаг
        time.sleep(0.2)  # гарантируем, что mtime станет новее
        config_file.write_text('app_name = "App"\nmax_workers = 8\nfeature_flag_new_ui = true')

        assert _wait_until(lambda: callbacks_called), "Коллбэк должен был сработать"
        updated = callbacks_called[-1]
        assert updated.max_workers == 8
        assert updated.feature_flag_new_ui is True

        # Актуальная конфигурация тоже обновилась
        assert _wait_until(lambda: manager.config.max_workers == 8)
    finally:
        manager.stop()


def test_callback_failure_does_not_kill_watcher(config_file: Path):
    manager = HotReloadConfig(SampleConfig, file_path=config_file, env_prefix="TEST", poll_interval=0.05)

    def failing_callback(_new_config):
        raise RuntimeError("callback boom")

    manager.add_callback(failing_callback)

    try:
        time.sleep(0.2)
        config_file.write_text('app_name = "App"\nmax_workers = 16')

        # Падающий коллбэк не должен остановить watcher: последующие изменения
        # всё ещё обрабатываются.
        assert _wait_until(lambda: manager.config.max_workers == 16)
    finally:
        manager.stop()


def test_broken_config_keeps_previous_values(config_file: Path):
    manager = HotReloadConfig(SampleConfig, file_path=config_file, env_prefix="TEST", poll_interval=0.05)
    try:
        time.sleep(0.2)
        # Пишем невалидный TOML: перезагрузка должна провалиться,
        # но старая конфигурация должна остаться.
        config_file.write_text("this is not [valid toml")

        time.sleep(0.5)
        assert manager.config.max_workers == 4
        assert manager.config.app_name == "App"
    finally:
        manager.stop()


def test_env_override_applies_on_reload(config_file: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEST_MAX_WORKERS", "12")
    manager = HotReloadConfig(SampleConfig, file_path=config_file, env_prefix="TEST", poll_interval=0.05)
    try:
        # ENV имеет высший приоритет уже при первоначальной загрузке
        assert manager.config.max_workers == 12

        time.sleep(0.2)
        config_file.write_text('app_name = "App2"\nmax_workers = 9')
        assert _wait_until(lambda: manager.config.app_name == "App2")
        # ENV переопределение сохраняется поверх нового файла
        assert manager.config.max_workers == 12
    finally:
        manager.stop()


def test_stop_terminates_watcher_thread(config_file: Path):
    manager = HotReloadConfig(SampleConfig, file_path=config_file, env_prefix="TEST", poll_interval=0.05)
    watcher = manager._thread
    assert watcher.is_alive()

    manager.stop()
    assert not watcher.is_alive()


def test_multiple_callbacks_all_fire(config_file: Path):
    manager = HotReloadConfig(SampleConfig, file_path=config_file, env_prefix="TEST", poll_interval=0.05)
    fired = []

    def cb_a(new_config):
        fired.append(("a", new_config.max_workers))

    def cb_b(new_config):
        fired.append(("b", new_config.max_workers))

    manager.add_callback(cb_a)
    manager.add_callback(cb_b)

    try:
        time.sleep(0.2)
        config_file.write_text('app_name = "App"\nmax_workers = 6')

        assert _wait_until(lambda: len(fired) == 2)
        assert ("a", 6) in fired
        assert ("b", 6) in fired
    finally:
        manager.stop()


def test_config_return_type_matches_load_config(config_file: Path):
    """HotReloadConfig загружает конфиг тем же путём, что и load_config."""
    expected = load_config(SampleConfig, env_prefix="TEST", file_path=config_file)
    manager = HotReloadConfig(SampleConfig, file_path=config_file, env_prefix="TEST", poll_interval=0.05)
    try:
        assert manager.config == expected
    finally:
        manager.stop()