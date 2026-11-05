"""Phase 0 spike: dump the SOMA joint lists so Blender-side scripts don't need Kimodo.

Run with the Kimodo venv's Python:
    python -I dump_skeleton.py <output.json>
"""
import json
import sys

from kimodo.skeleton import SOMASkeleton30

skel30 = SOMASkeleton30()
skel77 = skel30.somaskel77

with open(sys.argv[1], "w") as f:
    json.dump(
        {
            "joints77": skel77.bone_order_names,
            "parents77": [skel77.bone_parents[name] for name in skel77.bone_order_names],
            "joints30": skel30.bone_order_names,
            "parents30": [skel30.bone_parents[name] for name in skel30.bone_order_names],
            "subset30_in_77": [int(i) for i in skel30.get_skel_slice(skel77)],
        },
        f,
        indent=1,
    )
