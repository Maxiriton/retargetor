"""A backend's setup check: what is ready and what is not, each problem with its fix. No bpy.

run_env_check() runs env_check.py with the environment's Python (it imports the model's packages and PyTorch: a few
seconds); evaluate() turns its report, the machine and the weights on disk into CheckItems. The model loading itself
is checked by starting the backend (its Load button), not here.
"""
import json
import os
import subprocess
import sys
from dataclasses import dataclass

from . import installer, weights as weights_status
from .spec import MACOS

OK = "OK"
WARNING = "WARNING"
ERROR = "ERROR"

# Fixes the UI offers (CheckItem.fix)
FIX_INSTALL = "INSTALL"          # install (or resume the install)
FIX_REPAIR = "REPAIR"            # repair the install
FIX_SIGN_IN = "SIGN_IN"          # sign in to Hugging Face (and request access on CheckItem.url)
FIX_URL = "URL"                  # open CheckItem.url
FIX_PYTHON = "PYTHON"            # choose another Python executable (existing environment)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
CHECK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "env_check.py")
DRIVERS_URL = "https://www.nvidia.com/drivers"


@dataclass
class CheckItem:
    id: str
    label: str
    level: str
    message: str
    fix: str = ""
    url: str = ""


class CheckError(Exception):
    pass


def run_env_check(python, requirements, access=(), timeout=300.0, environ=None):
    """The environment's report (env_check.py's dict). access: gated repositories whose access is checked online.
    Raises CheckError if the Python doesn't run or answer."""
    spec = {"imports": list(requirements.imports),
            "optional_imports": [name for name, _why in requirements.optional_imports],
            "torch": True, "access": list(access)}
    env = dict(os.environ if environ is None else environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        env.pop(name, None)
    env.update({"PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_TELEMETRY": "1"})
    if not access:
        env["HF_HUB_OFFLINE"] = "1"
    try:
        result = subprocess.run([python, "-I", CHECK_SCRIPT, json.dumps(spec)], capture_output=True, timeout=timeout,
                                env=env, creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise CheckError(f"The environment's Python doesn't run: {e}") from e
    stdout = result.stdout.decode("utf-8", errors="replace")
    for line in reversed(stdout.splitlines()):
        if line.startswith("RESULT "):
            try:
                return json.loads(line[len("RESULT "):])
            except ValueError:
                break
    stderr = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
    raise CheckError(f"The environment's Python didn't answer (exit code {result.returncode}). "
                     + " ".join(stderr[-3:]))


def _gb(megabytes):
    return megabytes / 1024.0


def environment_items(requirements, layout, python, managed, report, error=""):
    """The environment itself: its Python, the install's completion"""
    if not python or not os.path.isfile(python):
        if managed:
            return [CheckItem("environment", "Environment", ERROR, "Not installed.", FIX_INSTALL)]
        return [CheckItem("environment", "Environment", ERROR,
                          f"The Python executable doesn't exist: {python or '(none set)'}.", FIX_PYTHON)]
    if report is None:
        return [CheckItem("environment", "Environment", ERROR, error or "The environment's Python doesn't run.",
                          FIX_REPAIR if managed else FIX_PYTHON)]
    items = []
    version = report.get("python", "")
    wanted = requirements.python
    if version and not version.startswith(wanted + ".") and version != wanted:
        items.append(CheckItem("environment", "Environment", WARNING,
                               f"Python {version}; this model is installed with Python {wanted}.",
                               FIX_REPAIR if managed else ""))
    elif managed and not installer.is_complete(layout):
        items.append(CheckItem("environment", "Environment", ERROR, "The install stopped before the end.",
                               FIX_INSTALL))
    else:
        where = layout.env_dir if managed else os.path.dirname(os.path.dirname(python))
        items.append(CheckItem("environment", "Environment", OK, f"Python {version}, {where}"))
    return items


def package_items(requirements, report, managed):
    imports = report.get("imports", {})
    broken = [(name, imports.get(name, {})) for name in requirements.imports if not imports.get(name, {}).get("ok")]
    if broken:
        name, info = broken[0]
        names = ", ".join(n for n, _ in broken)
        items = [CheckItem("packages", "Packages", ERROR,
                           f"Missing or broken: {names} ({info.get('error', 'not found')}).",
                           FIX_REPAIR if managed else "")]
    else:
        versions = [f"{name} {imports[name].get('version')}".strip() for name in requirements.imports
                    if imports.get(name, {}).get("version")]
        items = [CheckItem("packages", "Packages", OK, ", ".join(versions) or "All there.")]
    for name, why in requirements.optional_imports:
        if not imports.get(name, {}).get("ok"):
            items.append(CheckItem(f"optional:{name}", "Packages", WARNING, f"No {name}: {why}",
                                   FIX_REPAIR if managed else ""))
    return items


def gpu_items(requirements, machine, report, managed):
    torch = report.get("torch") or {}
    if not requirements.cuda or not torch.get("ok"):
        return []
    gpu = machine.gpu
    if not torch.get("available"):
        if gpu is None:
            if machine.system == MACOS and torch.get("mps"):
                message = "No NVIDIA GPU: the model runs on the Apple GPU (MPS) or the CPU, slowly."
            else:
                message = "No NVIDIA GPU found: the model runs on the CPU, very slowly."
            return [CheckItem("gpu", "GPU", WARNING, message)]
        if not torch.get("cuda"):
            return [CheckItem("gpu", "GPU", ERROR, f"PyTorch {torch.get('version')} was installed without CUDA: it "
                                                   f"can't use the {gpu.name}.", FIX_REPAIR if managed else "")]
        return [CheckItem("gpu", "GPU", ERROR,
                          f"PyTorch can't use the {gpu.name} (driver {gpu.driver or 'unknown'}, PyTorch built for CUDA "
                          f"{torch.get('cuda')}): update the NVIDIA driver.", FIX_URL, DRIVERS_URL)]
    devices = torch.get("devices") or []
    if not devices:
        return [CheckItem("gpu", "GPU", WARNING, "PyTorch sees CUDA but no device.")]
    device = max(devices, key=lambda d: d.get("memory_mb", 0))
    major, minor = (device.get("capability") or [0, 0])[:2]
    arch_list = torch.get("arch_list") or []
    if arch_list and f"sm_{major}{minor}" not in arch_list and not _ptx_covers(arch_list, major, minor):
        return [CheckItem("gpu", "GPU", ERROR,
                          f"This PyTorch build ({torch.get('version')}) has no code for the {device['name']} "
                          f"(sm_{major}{minor}).", FIX_REPAIR if managed else "")]
    memory = _gb(device.get("memory_mb", 0))
    if requirements.min_vram_gb and memory + 0.25 < requirements.min_vram_gb:
        return [CheckItem("gpu", "GPU", WARNING,
                          f"{device['name']}, {memory:.0f} GB: the model needs about {requirements.min_vram_gb:g} GB "
                          f"of video memory and may fail or run slowly.")]
    return [CheckItem("gpu", "GPU", OK, f"{device['name']}, {memory:.0f} GB, PyTorch {torch.get('version')}")]


def _ptx_covers(arch_list, major, minor):
    """A compute_XY entry (PTX) at or below the GPU's capability runs on it"""
    for arch in arch_list:
        if arch.startswith("compute_"):
            try:
                version = int(arch[len("compute_"):])
            except ValueError:
                continue
            if version <= major * 10 + minor:
                return True
    return False


def weights_items(requirements, layout, report, cache_dir=None):
    items = []
    access = (report or {}).get("access", {})
    signed_in = (report or {}).get("signed_in")
    for weights in requirements.weights:
        status = weights_status.status(weights, layout, cache_dir)
        item_id = f"weights:{weights.repo_id}"
        if status.present:
            items.append(CheckItem(item_id, weights.label, OK, f"{weights.repo_id}, {status.folder}"))
            continue
        partial = weights_status.repo_size_on_disk(weights, layout, cache_dir)
        missing = "Partly downloaded" if partial > 1e6 else "Not downloaded"
        if not weights.gated:
            items.append(CheckItem(item_id, weights.label, ERROR, f"{missing} ({weights.size_gb:.1f} GB).",
                                   FIX_INSTALL))
            continue
        state = access.get(weights.repo_id)
        if state == "ok":
            message = (f"{missing} ({weights.size_gb:.1f} GB). Your Hugging Face account has access: Install "
                       f"downloads it.")
            items.append(CheckItem(item_id, weights.label, ERROR, message, FIX_INSTALL))
        elif state == "gated" or (state is None and signed_in):
            message = (f"{missing}: it needs your Hugging Face access. Request it on its page (granted after a "
                       f"while), then Install.")
            items.append(CheckItem(item_id, weights.label, ERROR, message, FIX_URL, weights.page_url))
        else:
            message = (f"{missing}: it needs your Hugging Face access. Request it on its page, then sign in to "
                       f"Hugging Face and Install.")
            items.append(CheckItem(item_id, weights.label, ERROR, message, FIX_SIGN_IN, weights.page_url))
    return items


def evaluate(requirements, machine, layout, python, managed, report, error="", cache_dir=None):
    """Every CheckItem of a backend. report: run_env_check()'s dict, or None if it couldn't run (error says why)."""
    items = environment_items(requirements, layout, python, managed, report, error)
    if report is not None:
        items += package_items(requirements, report, managed)
        items += gpu_items(requirements, machine, report, managed)
    items += weights_items(requirements, layout, report, cache_dir)
    return items


def ready(items):
    return not any(item.level == ERROR for item in items)
