"""Phase 1 spike: draw a generated motion as stick figures (side view), to eyeball it.

Run with the Kimodo venv's Python (needs numpy and Pillow):
    python -I draw_strip.py <motion.npz> <soma_skeleton.json> <out.png> <key_frame> [<key_frame> ...]

Key frames (Kimodo frame indices) are drawn in orange, the in-betweens in blue.
"""
import json
import sys

import numpy as np
from PIL import Image, ImageDraw

STEP = 10  # draw every 10th frame
SCALE = 220  # pixels per meter
SPREAD = 0.55  # extra horizontal spacing per drawn frame, in meters


def main(npz_path, skeleton_path, out_path, key_frames):
    joints = np.load(npz_path)["posed_joints"]  # [T, 77, 3], Y-up, Z forward
    skeleton = json.load(open(skeleton_path))
    names = skeleton["joints77"]
    parents = skeleton["parents77"]
    keep = set(skeleton["joints30"])
    bones = [(names.index(p), i) for i, (n, p) in enumerate(zip(names, parents))
             if p is not None and n in keep and p in keep]

    frames = sorted(set(range(0, len(joints), STEP)) | set(key_frames))
    width = int((joints[:, :, 2].max() - joints[:, :, 2].min() + SPREAD * len(frames) + 1.0) * SCALE)
    height = int(2.1 * SCALE)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    z0 = joints[:, :, 2].min() - 0.4
    draw.line([(0, height - 0.1 * SCALE), (width, height - 0.1 * SCALE)], fill=(180, 180, 180), width=2)

    for k, f in enumerate(frames):
        color = (230, 120, 20) if f in key_frames else (60, 110, 200)

        def px(p):
            return ((p[2] - z0 + SPREAD * k) * SCALE, height - (p[1] + 0.1) * SCALE)

        for a, b in bones:
            draw.line([px(joints[f, a]), px(joints[f, b])], fill=color, width=3)
        draw.text(px(joints[f, names.index("Head")] + np.array([0, 0.25, 0])), str(f), fill=color)

    image.save(out_path)
    print(f"Saved {out_path} ({len(frames)} poses)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], [int(f) for f in sys.argv[4:]])
