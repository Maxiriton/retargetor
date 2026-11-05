"""Phase 1 spike: compare a rig's animation with key poses saved by make_rig_ik2fk.py.

Run headless with Blender 5.1+:
    blender -b --factory-startup <result.blend> --python compare_keyposes.py -- <reference.json>
"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spike_common as common  # noqa: E402

with open(sys.argv[sys.argv.index("--") + 1]) as fp:
    reference = json.load(fp)
common.compare_to_snapshot(bpy.data.objects["rig"], reference, "Result vs original IK pose,")
