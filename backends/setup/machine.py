"""The machine the models run on: its system, its processor and its NVIDIA GPUs (from nvidia-smi). No bpy."""
import os
import platform
import shutil
import subprocess
import sys

from .spec import LINUX, MACOS, WINDOWS, Gpu, Machine

_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
_cached = None


def system_name(platform_name=None):
    platform_name = platform_name or sys.platform
    if platform_name.startswith("win"):
        return WINDOWS
    if platform_name == "darwin":
        return MACOS
    return LINUX


def arch_name(machine=None):
    machine = (machine or platform.machine()).lower()
    if machine in ("arm64", "aarch64", "armv8l"):
        return "arm64"
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    return machine


def parse_nvidia_smi(text):
    """GPUs from `nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap --format=csv,noheader,nounits`
    (one line per GPU). Lines that don't parse are skipped."""
    gpus = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3 or not parts[0]:
            continue
        try:
            memory = int(float(parts[1]))
        except ValueError:
            continue
        capability = None
        if len(parts) > 3:
            try:
                major, minor = parts[3].split(".")
                capability = (int(major), int(minor))
            except ValueError:
                pass
        gpus.append(Gpu(parts[0], memory, capability, parts[2]))
    return tuple(gpus)


def nvidia_gpus():
    """The NVIDIA GPUs nvidia-smi sees (none when it's missing or fails)"""
    smi = shutil.which("nvidia-smi")
    if smi is None and sys.platform == "win32":
        candidate = r"C:\Windows\System32\nvidia-smi.exe"
        smi = candidate if os.path.isfile(candidate) else None
    if smi is None:
        return ()
    try:
        result = subprocess.run(
            [smi, "--query-gpu=name,memory.total,driver_version,compute_cap", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, **_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return ()
    return parse_nvidia_smi(result.stdout) if result.returncode == 0 else ()


def detect(refresh=False):
    """This machine (detected once, then cached)"""
    global _cached
    if _cached is None or refresh:
        _cached = Machine(system_name(), arch_name(), nvidia_gpus())
    return _cached
