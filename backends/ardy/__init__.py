"""ARDY backend (NVIDIA): autoregressive diffusion, its motion streamed window by window. Everything specific to ARDY
stays in this folder.

- models.py: its checkpoints (skeleton, frame rate, horizon, joint map; no bpy)
- install.py: what it needs installed (no bpy)
- backend.py: what the add-on knows (capabilities per checkpoint, preferences)
- worker.py: runs in ARDY's environment
"""
