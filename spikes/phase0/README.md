# Phase 0 spike: checking Kimodo works the way we need

Throwaway scripts that check the Kimodo model and the Blender ↔ Kimodo conversions. Outputs go to `out/` (not committed). The Kimodo venv path is in `CLAUDE.local.md`.

## Results (2026-10-31)

| Check | Result |
|---|---|
| Generation from the Kimodo venv on Windows (`Kimodo-SOMA-RP-v1.1`, 150 frames, 2 full-body keyframes, 100 diffusion steps) | Works. **23 s** in total, including model loading. **6.8 GB** of video memory at peak, with the 4-bit LLM2Vec text encoder. |
| Generated motion vs its keyframes | **Exact** (0.00 cm on every joint), thanks to Kimodo's post-processing. |
| BVH import in Blender 5.1 (bone heads vs `posed_joints`) | **0.001 cm** max error over 77 joints. |
| Blender pose → global rotations vs NPZ `global_rot_mats` | **0.000°** |
| Blender pose → constraints JSON → Kimodo FK vs generated motion | **0.00 cm** |
| Blender-built constraints vs the original example constraints | Root positions: 0.0005 cm. Local rotations: 0.1° max (float precision). |

## Conventions confirmed

- **Kimodo frame rate: 30 fps.** Kimodo frame `f` is Blender frame `f + 1` after the BVH import.
- **Axes:** Blender `(x, y, z)` → Kimodo `(x, z, -y)`. BVH import with `global_scale=0.01`, `axis_forward='-Z'`, `axis_up='Y'`.
- **Rest pose:** with `--bvh_standard_tpose`, the imported armature's rest pose is Kimodo's identity. A joint's Kimodo global rotation is simply its pose-vs-rest rotation in world space, converted to Y-up.
- **Skeletons:** the model works on `somaskel30`; NPZ and BVH outputs use `somaskel77` (77 joints, plus a `Root` bone in the BVH). Joint names are the same in Kimodo and in the BVH.
- **Trap:** the 30-joint `local_joints_rot` is a slice of the 77-joint local rotations. Each rotation is relative to the joint's **77-joint parent**, not its 30-joint parent. It only matters for the 4 hand end joints (`*HandThumbEnd`, `*HandMiddleEnd`), whose 77-joint parent is the last finger bone. Getting it wrong gives up to 60° errors on those joints, but no position error.
- **Root:** `root_positions` is the `Hips` head position, Y-up, meters, in Kimodo's canonical frame (root at XZ = (0, 0) on frame 0).

## Scripts

| Script | Runs with | Does |
|---|---|---|
| `dump_skeleton.py` | Kimodo venv | Writes the SOMA joint lists and parents to JSON, so Blender-side scripts don't need Kimodo. |
| `check_keyframes.py` | Kimodo venv | Rebuilds full-body constraints with Kimodo's FK and compares them with a motion. |
| `blender_roundtrip.py` | Blender 5.1 | Imports a BVH, checks positions and rotations, writes constraints rebuilt from the Blender pose, saves `out/soma_reference.blend`. |

## Reproduce

From this folder, in Git Bash, with `K` set to the Kimodo venv:

```bash
E=$K/Lib/site-packages/kimodo/assets/demo/examples/kimodo-soma-rp/03_full_body_keyframes
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 $K/Scripts/kimodo_gen.exe --model Kimodo-SOMA-RP-v1.1 --input_folder "$(cygpath -w $E)" --output "$(cygpath -w out)/fullbody_test" --bvh --bvh_standard_tpose --seed 43
$K/Scripts/python.exe -I dump_skeleton.py out/soma_skeleton.json
"/c/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b --factory-startup --python blender_roundtrip.py -- out/fullbody_test.bvh out/fullbody_test.npz out/soma_skeleton.json out 79 134
$K/Scripts/python.exe -I check_keyframes.py out/roundtrip_constraints.json out/fullbody_test.npz
```

## Not covered yet

- Generating from constraints built on a pose made **in Blender** (the round trip used poses taken from a Kimodo motion). That comes with Phase 1, on a real rig.
- Partial constraints (hands, feet) and root paths.
- Keeping the model loaded between generations (`kimodo_textencoder` server, or a persistent worker as in Phase 3).
