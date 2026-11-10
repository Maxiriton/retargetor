"""Where the models' environments, the tools and the weights go. No bpy.

<root>/                         default_root(), or the folder set in the add-on preferences
    tools/uv-<version>/uv       the uv tool (uv.py)
    python/                     the Python builds uv installs (one per version, shared by the environments)
    cache/uv/                   uv's download cache
    models/<backend id>/        one folder per backend, made by the installer
        install.json            what was installed (its presence marks the folder as the add-on's own)
        install.log
        env/                    the Python environment
        <weights folders>       weights that don't go to the Hugging Face cache (Weights.folder)

Weights with no folder go to the standard Hugging Face cache (hf_cache_dir()), shared with the user's other tools.
"""
import os

from .spec import LINUX, MACOS, WINDOWS

# Renamed with the extension's final name (Phase 8)
APP_FOLDER = "Retargetor"
STATE_FILE = "install.json"
LOG_FILE = "install.log"


def default_root(system, environ=None, home=None):
    """The default folder for the models on this system: %LOCALAPPDATA%\\Retargetor on Windows,
    $XDG_DATA_HOME/retargetor (~/.local/share/retargetor) on Linux, ~/Library/Application Support/Retargetor on
    macOS. Outside Blender's own configuration, so it is kept across Blender versions and add-on updates."""
    environ = os.environ if environ is None else environ
    home = home or os.path.expanduser("~")
    if system == WINDOWS:
        base = environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(base, APP_FOLDER)
    if system == MACOS:
        return os.path.join(home, "Library", "Application Support", APP_FOLDER)
    base = environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, APP_FOLDER.lower())


def env_python(env_dir, system):
    """The Python executable of a virtual environment"""
    if system == WINDOWS:
        return os.path.join(env_dir, "Scripts", "python.exe")
    return os.path.join(env_dir, "bin", "python")


def env_script(env_dir, name, system):
    """A command-line tool installed in a virtual environment (hf...)"""
    if system == WINDOWS:
        return os.path.join(env_dir, "Scripts", name + ".exe")
    return os.path.join(env_dir, "bin", name)


def env_root(python):
    """The environment folder of a Python executable inside a virtual environment (Scripts/ or bin/), or ''"""
    folder = os.path.dirname(os.path.abspath(python))
    if os.path.basename(folder).lower() in ("scripts", "bin"):
        root = os.path.dirname(folder)
        if os.path.isfile(os.path.join(root, "pyvenv.cfg")):
            return root
    return ""


def hf_cache_dir(environ=None, home=None):
    """The Hugging Face hub cache, as huggingface_hub finds it (HF_HUB_CACHE, HF_HOME/hub, ~/.cache/huggingface/hub)"""
    environ = os.environ if environ is None else environ
    if environ.get("HF_HUB_CACHE"):
        return environ["HF_HUB_CACHE"]
    if environ.get("HUGGINGFACE_HUB_CACHE"):
        return environ["HUGGINGFACE_HUB_CACHE"]
    home = home or os.path.expanduser("~")
    hf_home = environ.get("HF_HOME") or os.path.join(environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"),
                                                     "huggingface")
    return os.path.join(hf_home, "hub")


def hf_repo_dir(repo_id, cache_dir):
    """A model repository's folder in the Hugging Face cache"""
    return os.path.join(cache_dir, "models--" + repo_id.replace("/", "--"))


def folder_size(path):
    """Bytes in a folder (files counted once: the Hugging Face cache links snapshots to blobs)"""
    total = 0
    seen = set()
    for folder, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(folder, name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            key = (stat.st_dev, stat.st_ino) if stat.st_ino else full
            if key in seen or os.path.islink(full):
                continue
            seen.add(key)
            total += stat.st_size
    return total


class Layout:
    """The folders of one backend under the root. weights_root: where the weights with a folder go, when not the
    backend's folder (an existing environment made by another tool keeps its weights next to it)."""

    def __init__(self, root, backend_id, system, weights_root=None):
        self.root = os.path.abspath(root)
        self.backend_id = backend_id
        self.system = system
        self.weights_root = weights_root

    @property
    def backend_dir(self):
        return os.path.join(self.root, "models", self.backend_id)

    @property
    def env_dir(self):
        return os.path.join(self.backend_dir, "env")

    @property
    def python(self):
        return env_python(self.env_dir, self.system)

    @property
    def state_file(self):
        return os.path.join(self.backend_dir, STATE_FILE)

    @property
    def log_file(self):
        return os.path.join(self.backend_dir, LOG_FILE)

    @property
    def tools_dir(self):
        return os.path.join(self.root, "tools")

    @property
    def python_dir(self):
        return os.path.join(self.root, "python")

    @property
    def uv_cache_dir(self):
        return os.path.join(self.root, "cache", "uv")

    def weights_dir(self, weights):
        """Where a Weights goes: its folder under the backend's, or None for the Hugging Face cache"""
        if not weights.folder:
            return None
        return os.path.join(self.weights_root or self.backend_dir, weights.folder)

    def is_own_folder(self):
        """The backend's folder was made by the installer (it holds its state file): safe to remove"""
        return os.path.isfile(self.state_file)


__all__ = ["APP_FOLDER", "Layout", "default_root", "env_python", "env_root", "env_script", "folder_size",
           "hf_cache_dir", "hf_repo_dir", "LINUX", "MACOS", "WINDOWS"]
