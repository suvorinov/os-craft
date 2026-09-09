"""
os-craft: Легковесные утилиты для взаимодействия Python-приложений с ОС.
"""

from importlib.metadata import PackageNotFoundError, version

from .shutdown import ShutdownHook, ShutdownManager

# Явно указываем, что экспортируется при `from os_craft import *`
__all__ = [
    "ShutdownHook",
    "ShutdownManager",
]


def _get_version() -> str:
    """
    Возвращает версию пакета из установленных metadata (PEP 440).

    В dev-режиме (editable install) version() читает актуальную версию
    из pyproject.toml, поэтому рассинхрон между __version__ и pyproject
    невозможен. Если пакет не установлен (например, запуск из исходников),
    используем заглушку.
    """
    try:
        return version("os-craft")
    except PackageNotFoundError:
        return "0.1.0"


__version__ = _get_version()