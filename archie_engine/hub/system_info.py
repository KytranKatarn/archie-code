"""System info gathering for node registration and heartbeat metrics."""

import os
import platform
import logging

import psutil

logger = logging.getLogger(__name__)


def get_system_info() -> dict:
    """Gather static system info for node registration."""
    info = {
        "hostname": platform.node(),
        "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "cpu_model": _get_cpu_model(),
        "ram_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "os_info": f"{platform.system()} {platform.release()}",
        "gpu_model": None,
        "gpu_vram_gb": None,
    }
    gpu = _detect_gpu()
    if gpu:
        info["gpu_model"] = gpu["model"]
        info["gpu_vram_gb"] = gpu["vram_gb"]
    return info


def get_heartbeat_metrics() -> dict:
    """Gather dynamic system metrics for heartbeat updates."""
    return {
        "cpu_usage": psutil.cpu_percent(interval=0.1),
        "memory_usage": psutil.virtual_memory().percent,
        "gpu_usage": None,
        "current_load": 0,
    }


def _get_cpu_model() -> str:
    """Get CPU model string."""
    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":")[1].strip()
        elif platform.system() == "Darwin":
            import subprocess
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
    except Exception as e:
        logger.debug("Could not detect CPU model: %s", e)
    return platform.processor() or "Unknown"


def _detect_gpu() -> dict | None:
    """Detect GPU model and VRAM. Returns None if no GPU found."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) >= 2:
                return {
                    "model": parts[0].strip(),
                    "vram_gb": round(float(parts[1].strip()) / 1024, 1),
                }
    except (FileNotFoundError, Exception) as e:
        logger.debug("GPU detection skipped: %s", e)
    return None
