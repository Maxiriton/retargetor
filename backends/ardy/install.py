"""What ARDY needs installed (backends.setup.spec.Requirements), for one machine. No bpy.

ARDY (NVIDIA, github.com/nv-tlabs/ardy, Apache-2.0) at a pinned commit, its checkpoints from Hugging Face (NVIDIA
Open Model License), and its text encoder: LLM2Vec (McGill NLP, MIT) on Meta's Llama 3 8B Instruct, a gated
repository the user requests access to (Meta Llama 3 Community License). ARDY pins transformers 5.8.1 and numpy < 2:
it can't share Kimodo's environment.

Its post-processing (foot skating, constraints hit exactly) is a C++ extension built from source when the package is
installed: it needs a C++ compiler (and git, which fetches pybind11). Without them ARDY is installed without it, and
the check says so.
"""
from ..setup.spec import MACOS, Packages, Requirements, Weights
from . import models

PYTHON = "3.11"
REPOSITORY = "https://github.com/nv-tlabs/ardy"
COMMIT = "e706e27acc88070918308a10922b8f7174d0825e"
ARCHIVE = f"{REPOSITORY}/archive/{COMMIT}.zip"

NVIDIA_MODEL_LICENSE = "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-agreement/"
LLAMA_LICENSE = "https://www.llama.com/llama3/license/"

# The text encoder (ardy.model.load_model's "llm2vec" preset): LLM2Vec's two adapters on Llama 3 8B Instruct
TEXT_ENCODER = (
    Weights("Text encoder adapter (LLM2Vec, MNTP)", "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp", 0.17,
            required_files=("adapter_config.json", "adapter_model.safetensors", "config.json"),
            license_url="https://huggingface.co/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp"),
    Weights("Text encoder adapter (LLM2Vec, supervised)",
            "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised", 0.16,
            required_files=("adapter_config.json", "adapter_model.safetensors"),
            license_url="https://huggingface.co/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised"),
    Weights("Text encoder (Meta Llama 3 8B Instruct)", "meta-llama/Meta-Llama-3-8B-Instruct", 16.1,
            # The safetensors weights only, not the original PyTorch checkpoint (another 16 GB). The tokenizer
            # comes from the MNTP adapter's repository.
            allow_patterns=("*.json", "*.safetensors"),
            required_files=("config.json", "model.safetensors.index.json"),
            gated=True, license_url=LLAMA_LICENSE),
)


def checkpoint_weights(model):
    checkpoint = models.CHECKPOINTS[model]
    return Weights(f"{model} weights", f"nvidia/{model}", checkpoint.size_gb,
                   required_files=("config.yaml", "denoiser.safetensors"), license_url=NVIDIA_MODEL_LICENSE)


def torch_packages(machine):
    """PyTorch 2.7.1: CUDA 12.6 builds up to the RTX 40 series, CUDA 12.8 for the RTX 50 series (Blackwell), the
    default PyPI build on macOS"""
    if machine.system == MACOS:
        return Packages("PyTorch", ("torch==2.7.1",))
    gpu = machine.gpu
    if gpu is not None and gpu.compute_capability is not None and gpu.compute_capability >= (12, 0):
        return Packages("PyTorch (CUDA 12.8)", ("torch==2.7.1",), index_url="https://download.pytorch.org/whl/cu128")
    return Packages("PyTorch (CUDA 12.6)", ("torch==2.7.1",), index_url="https://download.pytorch.org/whl/cu126")


def requirements(machine, model=models.DEFAULT_MODEL):
    model = model if model in models.CHECKPOINTS else models.DEFAULT_MODEL
    torch = torch_packages(machine)
    build = machine.cpp_compiler and machine.git
    env = () if build else (("ARDY_SKIP_MOTION_CORRECTION", "1"),)
    ardy = Packages("ARDY" + ("" if build else " (without its post-processing)"),
                    # The PyTorch build installed above stays: its version (2.7.1+cu126) matches the pin
                    (f"ardy @ {ARCHIVE}",) + torch.requirements, env=env)
    notes = [f"ARDY from NVIDIA ({REPOSITORY}, commit {COMMIT[:7]}), its {models.CHECKPOINTS[model].label} "
             f"model, and its text encoder: LLM2Vec on Meta's Llama 3 8B Instruct, which needs your Hugging Face "
             f"access (requested on its page)."]
    if not build:
        notes.append("No C++ compiler (or git) found: ARDY is installed without its post-processing, so key poses "
                     "are followed less exactly. Install Visual Studio's C++ build tools (Windows) or a compiler, then "
                     "Repair.")
    return Requirements(
        python=PYTHON,
        packages=(torch, ardy),
        weights=(checkpoint_weights(model),) + TEXT_ENCODER,
        imports=("torch", "ardy", "ardy.model", "transformers", "peft"),
        optional_imports=(("motion_correction._motion_correction",
                           "ARDY's post-processing is off: key poses are followed less exactly."),),
        cuda=True,
        # The text encoder in bfloat16 takes about 15 GB, the model about 1
        min_vram_gb=17.0,
        disk_gb=6.0,
        notes=tuple(notes),
        licences=(("ARDY code: Apache-2.0", f"{REPOSITORY}/blob/{COMMIT}/LICENSE"),
                  ("ARDY weights: NVIDIA Open Model License", NVIDIA_MODEL_LICENSE),
                  ("Text encoder: Meta Llama 3 Community License, LLM2Vec: MIT", LLAMA_LICENSE)),
    )
