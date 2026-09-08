"""
os-craft: Легковесные утилиты для взаимодействия Python-приложений с ОС.
"""

from .shutdown import ShutdownHook, ShutdownManager

# Явно указываем, что экспортируется при `from os_craft import *`
__all__ = [
    "ShutdownHook",
    "ShutdownManager",
]

# Версия пакета (автоматически подтягивается из pyproject.toml при сборке, 
# но для dev-режима зададим заглушку, если не используется hatch-vcs)
__version__ = "0.1.0"