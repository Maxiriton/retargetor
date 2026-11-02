"""Kimodo backend (NVIDIA), SOMA skeleton. Everything specific to Kimodo stays in this folder.

- joints.py: Kimodo's constants and the SOMA role -> joint map (no bpy)
- convert.py: Blender <-> Kimodo conversions (numpy, no bpy, no torch)
- worker.py: the worker, run with the Kimodo venv's Python; keeps the model loaded between generations
- backend.py: what the add-on knows about it (preferences: the venv's Python, the model)
"""
