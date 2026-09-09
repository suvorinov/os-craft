"""
Пример использования os_craft.perf для профилирования.
"""

import logging
import time

from os_craft import track_block, track_perf

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s | %(message)s")

# 1. Декоратор для обычной функции
@track_perf
def heavy_computation():
    """Имитация тяжелой функции, которая много аллоцирует."""
    # Создаем большой список (это вызовет WARNING, если > 10 MB)
    data = [i * 2 for i in range(2_000_000)] 
    time.sleep(0.1)
    return sum(data)

# 2. Декоратор для класса (обернет все публичные методы!)
@track_perf
class DataProcessor:
    def __init__(self):
        self.data = []

    def load_data(self):
        time.sleep(0.05)
        self.data = list(range(1_000_000))
        return len(self.data)

    def process_data(self):
        time.sleep(0.05)
        return sum(self.data)

# 3. Контекстный менеджер для произвольного блока
def custom_block_example():
    with track_block("CUSTOM:DB_QUERY_SIMULATION"):
        time.sleep(0.08)
        # Имитация аллокации результата запроса
        _ = {f"key_{i}": i for i in range(500_000)}

def main():
    print("\n" + "="*60)
    print("Запуск без OS_CRAFT_ENABLE_PERF=1 (оверхед = 0)")
    print("="*60)
    heavy_computation()
    
    processor = DataProcessor()
    processor.load_data()
    processor.process_data()
    
    custom_block_example()
    
    print("\n" + "="*60)
    print("💡 Чтобы увидеть отчеты, запусти скрипт так:")
    print("OS_CRAFT_ENABLE_PERF=1 OS_CRAFT_PERF_MEM_WARN_MB=5.0 uv run python examples/perf_usage.py")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()