"""Tests for system info gathering."""

import pytest
from archie_engine.hub.system_info import get_system_info


def test_system_info_returns_required_fields():
    info = get_system_info()
    assert "hostname" in info
    assert "cpu_cores" in info
    assert "ram_gb" in info
    assert "os_info" in info
    assert isinstance(info["cpu_cores"], int)
    assert info["cpu_cores"] > 0
    assert isinstance(info["ram_gb"], (int, float))
    assert info["ram_gb"] > 0


def test_system_info_hostname_is_string():
    info = get_system_info()
    assert isinstance(info["hostname"], str)
    assert len(info["hostname"]) > 0


def test_system_info_gpu_field_present():
    """GPU fields should always be present (None if no GPU detected)."""
    info = get_system_info()
    assert "gpu_model" in info
    assert "gpu_vram_gb" in info


def test_get_heartbeat_metrics_returns_usage():
    from archie_engine.hub.system_info import get_heartbeat_metrics
    metrics = get_heartbeat_metrics()
    assert "cpu_usage" in metrics
    assert "memory_usage" in metrics
    assert isinstance(metrics["cpu_usage"], (int, float))
    assert isinstance(metrics["memory_usage"], (int, float))
