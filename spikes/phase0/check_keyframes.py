"""Phase 0 spike: does a Kimodo generation hit its full-body keyframes?

Run with the Kimodo venv's Python:
    python -I check_keyframes.py <constraints.json> <motion.npz>

Rebuilds the constrained poses with Kimodo's own forward kinematics and compares
the joint positions with the generated motion at the constrained frames.
"""
import json
import sys

import numpy as np
import torch

from kimodo.geometry import axis_angle_to_matrix
from kimodo.skeleton import SOMASkeleton30


def main(constraints_path, npz_path):
    motion = np.load(npz_path)
    skel30 = SOMASkeleton30()
    skel77 = skel30.somaskel77
    subset = skel30.get_skel_slice(skel77)

    for item in json.load(open(constraints_path)):
        if item["type"] != "fullbody":
            continue
        frames = item["frame_indices"]
        local_rots = axis_angle_to_matrix(torch.tensor(item["local_joints_rot"], dtype=torch.float32))
        root_positions = torch.tensor(item["root_positions"], dtype=torch.float32)

        _global_rots, posed, _ = skel77.fk(skel30.to_SOMASkeleton77(local_rots), root_positions)
        target = posed.numpy()[:, subset]
        generated = motion["posed_joints"][frames][:, subset]

        error_cm = np.linalg.norm(target - generated, axis=-1) * 100.0
        for i, frame in enumerate(frames):
            worst = int(error_cm[i].argmax())
            print(
                f"frame {frame}: mean {error_cm[i].mean():.2f} cm, "
                f"max {error_cm[i].max():.2f} cm ({skel30.bone_order_names[worst]})"
            )


if __name__ == "__main__":
    main(*sys.argv[1:3])
