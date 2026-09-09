"""
Тесты для модуля os_craft.config.
"""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from os_craft import load_config


@dataclass
class SampleConfig:
    port: int = 8000
    debug: bool = False
    hosts: list[str] = field(default_factory=lambda: ["localhost"])


@dataclass
class PathConfig:
    data_dir: Path = Path("/tmp/data")


def test_load_config_defaults():
    """Проверяем, что значения по умолчанию работают без файлов и ENV."""
    config = load_config(SampleConfig, env_prefix="SAMPLE")
    assert config.port == 8000
    assert config.debug is False
    assert config.hosts == ["localhost"]


def test_load_config_from_toml(tmp_path: Path):
    """Проверяем загрузку и парсинг TOML-файла."""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('port = 9090\ndebug = true\nhosts = ["10.0.0.1", "10.0.0.2"]')

    config = load_config(SampleConfig, env_prefix="SAMPLE", file_path=toml_file)

    assert config.port == 9090
    assert config.debug is True
    assert config.hosts == ["10.0.0.1", "10.0.0.2"]


def test_toml_wrong_type_raises(tmp_path: Path):
    """Некорректный тип значения из TOML должен давать понятную ошибку."""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('port = "not_a_number"')

    with pytest.raises(ValueError, match="Неверное значение в TOML для поля port"):
        load_config(SampleConfig, env_prefix="SAMPLE", file_path=toml_file)


def test_load_config_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Проверяем, что переменные окружения имеют высший приоритет
    и корректно приводят типы.
    """
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('port = 9090\ndebug = true')

    monkeypatch.setenv("SAMPLE_PORT", "3000")
    monkeypatch.setenv("SAMPLE_DEBUG", "0")
    monkeypatch.setenv("SAMPLE_HOSTS", "api.com, admin.com ")

    config = load_config(SampleConfig, env_prefix="SAMPLE", file_path=toml_file)

    assert config.port == 3000
    assert config.debug is False
    assert config.hosts == ["api.com", "admin.com"]


def test_path_type_from_env(monkeypatch: pytest.MonkeyPatch):
    """Поле Path корректно приводится из ENV."""
    monkeypatch.setenv("PATHCFG_DATA_DIR", "/etc/opt")

    config = load_config(PathConfig, env_prefix="PATHCFG")

    assert config.data_dir == Path("/etc/opt")
    assert isinstance(config.data_dir, Path)


def test_list_int_from_env(monkeypatch: pytest.MonkeyPatch):
    """Элементы списка приводятся к внутреннему типу (list[int])."""

    @dataclass
    class IntListConfig:
        ports: list[int] = field(default_factory=list)

    monkeypatch.setenv("ILC_PORTS", "8000, 9000, 7000")

    config = load_config(IntListConfig, env_prefix="ILC")

    assert config.ports == [8000, 9000, 7000]
    assert all(isinstance(p, int) for p in config.ports)


def test_unsupported_type_raises(monkeypatch: pytest.MonkeyPatch):
    """Неподдерживаемый тип (tuple) не должен нарушаться молча."""

    @dataclass
    class TupleConfig:
        coords: tuple = (0, 0)

    monkeypatch.setenv("TUP_CFG_COORDS", "1,2")

    with pytest.raises(ValueError, match="не поддерживается"):
        load_config(TupleConfig, env_prefix="TUP_CFG")


def test_required_field_without_value_raises():
    """Обязательное поле без дефолта должно давать TypeError, а не MISSING-значение."""

    @dataclass
    class RequiredConfig:
        port: int

    with pytest.raises(TypeError, match="port"):
        load_config(RequiredConfig, env_prefix="REQ")


def test_required_field_from_env(monkeypatch: pytest.MonkeyPatch):
    """Обязательное поле заполняется из ENV."""

    @dataclass
    class RequiredConfig:
        port: int

    monkeypatch.setenv("REQ_PORT", "8080")

    config = load_config(RequiredConfig, env_prefix="REQ")

    assert config.port == 8080


def test_load_config_type_error(monkeypatch: pytest.MonkeyPatch):
    """Проверяем, что невалидный тип в ENV вызывает понятную ошибку."""
    monkeypatch.setenv("SAMPLE_PORT", "not_a_number")

    with pytest.raises(ValueError) as exc_info:
        load_config(SampleConfig, env_prefix="SAMPLE")

    assert "Не удалось привести значение ENV SAMPLE_PORT='not_a_number' к типу <class 'int'>" in str(exc_info.value)


def test_non_dataclass_raises():
    """Передача не-dataclass класса должна давать TypeError."""
    with pytest.raises(TypeError, match="Ожидался dataclass"):
        load_config(dict, env_prefix="NOPE")