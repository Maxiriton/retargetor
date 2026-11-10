"""Installing and checking a backend's model: its Python environment, its packages and its weights. No bpy.

- spec.py: what a backend needs (Requirements), and the machine it runs on (Machine)
- machine.py: the machine's system and NVIDIA GPUs
- paths.py: where environments, tools and weights go
- uv.py: the uv tool, downloaded once (it installs Python and the packages)
- installer.py: the install, step by step, resumable
- checks.py: what is ready and what is not, with the fix for each problem
- env_check.py, env_download.py: run with the model environment's own Python (stdlib and huggingface_hub only)

Nothing here imports bpy: the add-on side (model_setup.py) runs it from operators and timers.
"""
