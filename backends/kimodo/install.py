"""What Kimodo needs installed (backends.setup.spec.Requirements), for one machine. No bpy.

Kimodo comes from Aero-Ex's fork (the user's choice, 2026-11-10): it runs on Windows without a compiler (its
post-processing module is prebuilt) and its text encoder is a 4-bit copy of LLM2Vec / Llama 3 8B (about 5 GB of video
memory instead of about 17, and no gated Hugging Face repository). Everything is pinned: the fork's commit, the
wheels' SHA-256, the text encoder's revision. If that source goes away, the official NVIDIA Kimodo with the gated
Llama 3 weights (quantized by us) replaces it here, nothing else changes.
"""
from ..setup.spec import MACOS, Packages, Requirements, Weights
from . import joints

PYTHON = "3.11"
FORK = "https://github.com/Aero-Ex/kimodo"
FORK_COMMIT = "3b45cc6d420136bfa6128e8be5e81e45521f2b7a"
FORK_ARCHIVE = f"{FORK}/archive/{FORK_COMMIT}.zip"

# Aero-Ex's prebuilt post-processing module (release v1.0.0), for Python 3.11
_WHEELS = f"{FORK}/releases/download/v1.0.0/"
MOTION_CORRECTION_WHEELS = {
    "windows": (_WHEELS + "motion_correction-1.0.0-cp311-cp311-win_amd64.whl",
                "c195a75fcadf222925c38c7782c33a36c17c4fbb60ac6e62e57e7d8910f3d257"),
    "linux": (_WHEELS + "motion_correction-1.0.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
              "2c5f73869083ce5334863cc0f830a2222ce6b62ff29e0536611dc59cc167a9e6"),
}

# The text encoder, in a folder of its own: the worker points the fork's encoder to it
TEXT_ENCODER_FOLDER = "llm2vec-model"
TEXT_ENCODER = Weights(
    "Text encoder (LLM2Vec / Llama 3 8B, 4-bit)", "Aero-Ex/KIMODO-Meta3_llm2vec_NF4", 4.67,
    revision="207f0c64a7325f6045d15c68c5ea9e961c18fafd", folder=TEXT_ENCODER_FOLDER,
    required_files=("config.json", "llm2vec_config.json", "model.safetensors", "tokenizer.json"),
    license_url="https://www.llama.com/llama3/license/")

# Kimodo models (Hugging Face nvidia/<name>) and their size in GB
MODEL_SIZES = {"Kimodo-SOMA-RP-v1.1": 1.13, "Kimodo-SOMA-RP-v1": 1.13}

NVIDIA_MODEL_LICENSE = "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/"


def model_weights(model):
    return Weights(f"{model} weights", f"nvidia/{model}", MODEL_SIZES.get(model, 1.2),
                   required_files=("config.yaml", "model.safetensors"), license_url=NVIDIA_MODEL_LICENSE)


def torch_packages(machine):
    """PyTorch for this machine: CUDA 12.1 builds up to the RTX 40 series, CUDA 12.8 for the RTX 50 series
    (Blackwell, sm_120, PyTorch 2.7+), the default PyPI build on macOS"""
    if machine.system == MACOS:
        return Packages("PyTorch", ("torch==2.5.1",))
    gpu = machine.gpu
    if gpu is not None and gpu.compute_capability is not None and gpu.compute_capability >= (12, 0):
        return Packages("PyTorch (CUDA 12.8)", ("torch==2.7.1",), index_url="https://download.pytorch.org/whl/cu128")
    return Packages("PyTorch (CUDA 12.1)", ("torch==2.5.1",), index_url="https://download.pytorch.org/whl/cu121")


def requirements(machine, model=joints.DEFAULT_MODEL):
    model = model or joints.DEFAULT_MODEL
    packages = [torch_packages(machine)]
    wheel = MOTION_CORRECTION_WHEELS.get(machine.system) if machine.arch == "x86_64" else None
    if wheel is not None:
        url, digest = wheel
        packages.append(Packages("Kimodo's post-processing", (f"motion_correction @ {url}#sha256={digest}",),
                                 no_deps=True))
    packages.append(Packages(
        "Kimodo",
        (f"kimodo @ {FORK_ARCHIVE}",
         # Imported by Kimodo without being declared by it (as the fork's own installer does)
         "bitsandbytes>=0.46.1", "safetensors", "psutil"),
        # Its post-processing module comes from the wheel above, not built from source (that needs a compiler)
        env=(("SKIP_MOTION_CORRECTION_IN_SETUP", "1"),)))
    return Requirements(
        python=PYTHON,
        packages=tuple(packages),
        weights=(model_weights(model), TEXT_ENCODER),
        imports=("torch", "kimodo", "transformers", "bitsandbytes"),
        optional_imports=(("motion_correction", "Kimodo's post-processing is off: key poses are not hit exactly."),),
        cuda=True,
        # Measured: 6.8 GB on an RTX 3090 (4-bit text encoder, 10 s of motion)
        min_vram_gb=8.0,
        disk_gb=6.0,
        notes=(f"Kimodo from Aero-Ex's fork ({FORK}, commit {FORK_COMMIT[:7]}), with its prebuilt post-processing "
               f"module and its 4-bit copy of the Llama 3 text encoder; the model's weights from NVIDIA.",),
        licences=(("Kimodo code: Apache-2.0", f"{FORK}/blob/{FORK_COMMIT}/LICENSE"),
                  ("Kimodo weights: NVIDIA Open Model License", NVIDIA_MODEL_LICENSE),
                  ("Text encoder: Meta Llama 3 Community License", TEXT_ENCODER.license_url)),
    )
