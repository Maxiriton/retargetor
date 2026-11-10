"""What several backends share: conventions of the models from the same family, not of the add-on. No bpy.

- convert.py: Blender <-> Y-up model conversions, frame rates, canonical frame, constraint lists (Kimodo, ARDY)
- soma.py: the SOMA skeleton's humanoid role -> joint map and end-effectors (Kimodo, ARDY's SOMA checkpoint)

Workers import these modules: keep this file free of imports.
"""
