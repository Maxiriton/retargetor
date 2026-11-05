"""Dump the world matrices of an armature's pose bones on some frames, to compare two runs.

    blender -b --factory-startup <file.blend> --python tests/blender/dump_pose.py -- <object> <out.json> <first> <last>
"""
import json

import bpy

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402


def dump(obj, frames):
    scene = bpy.context.scene
    data = {}
    for frame in frames:
        scene.frame_set(frame)
        data[str(frame)] = {pb.name: [list(row) for row in obj.matrix_world @ pb.matrix] for pb in obj.pose.bones}
    return data


if __name__ == "__main__":
    name, out, first, last = bootstrap.script_args()
    with open(out, "w") as f:
        json.dump(dump(bpy.data.objects[name], range(int(first), int(last) + 1)), f)
    print(f"dumped {name} to {out}")
