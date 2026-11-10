"""What a backend needs installed, declared by the backend (Backend.requirements), and the machine. No bpy.

A backend describes its model's environment as data: the Python version, the packages (one `uv pip install` per
Packages, in order: the right PyTorch build first), the weights (Hugging Face repositories) and what its check
imports. The installer and the check read it; nothing else in the add-on knows what a model needs.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

WINDOWS = "windows"
LINUX = "linux"
MACOS = "macos"


@dataclass(frozen=True)
class Gpu:
    name: str
    memory_mb: int
    # (major, minor), e.g. (8, 6) for an RTX 3090; None when unknown
    compute_capability: tuple | None = None
    driver: str = ""


@dataclass(frozen=True)
class Machine:
    system: str          # WINDOWS, LINUX, MACOS
    arch: str            # "x86_64", "arm64"
    gpus: tuple = ()     # NVIDIA GPUs (Gpu)
    # A C++ compiler and git are there: a package's C++ extension can be built from source
    cpp_compiler: bool = False
    git: bool = False

    @property
    def gpu(self):
        """The NVIDIA GPU with the most memory, or None"""
        return max(self.gpus, key=lambda gpu: gpu.memory_mb) if self.gpus else None


@dataclass(frozen=True)
class Packages:
    """One `uv pip install` into the model's environment.

    requirements: pip requirement strings (a direct URL may end with #sha256=<hash>, which is checked).
    index_url: the index replacing PyPI for this step (PyTorch's CUDA builds); extra_index_urls are searched too.
    env: (name, value) pairs set for the install (build options of the packages).
    """
    label: str
    requirements: tuple
    index_url: str | None = None
    extra_index_urls: tuple = ()
    env: tuple = ()
    no_deps: bool = False


@dataclass(frozen=True)
class Weights:
    """A Hugging Face model repository the model loads.

    folder: where it goes, under the backend's own folder; None: the standard Hugging Face cache, shared with the
    user's other tools (weights already there aren't downloaded again).
    required_files: files that must be there (relative to the snapshot); an index (model.safetensors.index.json)
    also requires its shards.
    gated: the repository needs the user's own Hugging Face access (requested on its page, then signed in).
    """
    label: str
    repo_id: str
    size_gb: float
    revision: str | None = None
    allow_patterns: tuple | None = None
    ignore_patterns: tuple | None = None
    folder: str | None = None
    required_files: tuple = ()
    gated: bool = False
    license_url: str = ""

    @property
    def page_url(self):
        return f"https://huggingface.co/{self.repo_id}"


@dataclass(frozen=True)
class Requirements:
    """Everything a backend's model needs, for one machine.

    python: the environment's Python version ("3.11"). imports: modules the check imports (a failure means a broken
    install). optional_imports: (module, what is missing without it) pairs, reported as warnings.
    cuda: the model needs an NVIDIA GPU (it runs on the CPU without one, very slowly). min_vram_gb: video memory
    it needs. disk_gb: about how much the environment takes (the weights are counted apart).
    notes: shown before installing (what is downloaded from where, licences). licences: (label, url) pairs.
    """
    python: str
    packages: tuple
    weights: tuple = ()
    imports: tuple = ()
    optional_imports: tuple = ()
    cuda: bool = True
    min_vram_gb: float = 0.0
    disk_gb: float = 0.0
    notes: tuple = ()
    licences: tuple = field(default=())

    @property
    def download_gb(self):
        """The environment and every weight, in GB (an upper bound: weights already there aren't downloaded)"""
        return self.disk_gb + sum(w.size_gb for w in self.weights)


def step_key(item):
    """A short key changing whenever a step's declaration changes (a new version pinned...): the installer redoes
    a step whose key differs from the one it recorded."""
    return hashlib.sha1(repr(item).encode("utf-8")).hexdigest()[:16]
