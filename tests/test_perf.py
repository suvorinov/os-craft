"""
Тесты для модуля os_craft.perf.

Профилирование выключено по умолчанию, но флаг _IS_ENABLED — глобальный
модуля, поэтому тесты включают его через monkeypatch без перезапуска процесса.
"""

import tracemalloc

import pytest

from os_craft import perf


@pytest.fixture(autouse=True)
def _clean_tracemalloc():
    yield
    tracemalloc.stop()


def test_format_memory():
    assert perf._format_memory(512) == "512 B"
    assert perf._format_memory(1024) == "1.00 KB"
    assert perf._format_memory(5 * 1024 * 1024) == "5.00 MB"


def test_get_top_allocations_returns_str():
    tracemalloc.start()
    data = [i for i in range(10_000)]  # noqa: F841
    result = perf._get_top_allocations()
    assert isinstance(result, str)
    assert result


def test_track_perf_disabled_runs_without_callback(monkeypatch):
    monkeypatch.setattr(perf, "_IS_ENABLED", False)
    captured: list[perf.PerfMetrics] = []

    @perf.track_perf(callback=captured.append)
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
    assert captured == []


def test_track_perf_enabled_metrics(monkeypatch):
    monkeypatch.setattr(perf, "_IS_ENABLED", True)
    monkeypatch.setattr(perf, "_MEMORY_WARN_THRESHOLD_MB", 1e9)
    captured: list[perf.PerfMetrics] = []

    @perf.track_perf(callback=captured.append)
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
    assert len(captured) == 1
    metrics = captured[0]
    assert metrics["name"].endswith("add")
    assert metrics["duration_ms"] >= 0
    assert "mem_diff_mb" in metrics
    assert metrics["peak_mem_mb"] >= 0


def test_track_perf_bare_decorator(monkeypatch):
    monkeypatch.setattr(perf, "_IS_ENABLED", True)

    @perf.track_perf
    def add(a, b):
        return a + b

    assert add(2, 3) == 5


def test_track_perf_class_wraps_public_methods(monkeypatch):
    monkeypatch.setattr(perf, "_IS_ENABLED", True)
    monkeypatch.setattr(perf, "_MEMORY_WARN_THRESHOLD_MB", 1e9)
    captured: list[perf.PerfMetrics] = []

    @perf.track_perf(callback=captured.append)
    class Foo:
        def bar(self):
            return 42

        def _hidden(self):
            return 0

    foo = Foo()
    assert foo.bar() == 42
    assert foo._hidden() == 0
    assert len(captured) == 1
    assert captured[0]["name"].endswith("Foo.bar")


def test_track_block_disabled_runs_without_callback(monkeypatch):
    monkeypatch.setattr(perf, "_IS_ENABLED", False)
    captured: list[perf.PerfMetrics] = []

    with perf.track_block("BLOCK:test", callback=captured.append):
        pass

    assert captured == []


def test_track_block_enabled_callback(monkeypatch):
    monkeypatch.setattr(perf, "_IS_ENABLED", True)
    monkeypatch.setattr(perf, "_MEMORY_WARN_THRESHOLD_MB", 1e9)
    captured: list[perf.PerfMetrics] = []

    with perf.track_block("BLOCK:test", callback=captured.append):
        pass

    assert len(captured) == 1
    assert captured[0]["name"] == "BLOCK:test"
    assert captured[0]["duration_ms"] >= 0


def test_track_perf_callback_exception_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(perf, "_IS_ENABLED", True)
    monkeypatch.setattr(perf, "_MEMORY_WARN_THRESHOLD_MB", 1e9)

    def boom(_: perf.PerfMetrics) -> None:
        raise RuntimeError("callback boom")

    @perf.track_perf(callback=boom)
    def add(a, b):
        return a + b

    with caplog.at_level("ERROR", logger="os_craft.perf"):
        assert add(1, 2) == 3

    assert "Ошибка в callback профилировщика" in caplog.text