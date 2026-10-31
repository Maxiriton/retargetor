# Phase 1 spike: rough end-to-end prototype on a Rigify rig

The whole chain, scripted and headless: key poses on a Rigify rig → SOMA → Kimodo → SOMA → back onto the Rigify controls. Uses the current Retargetor unchanged. Outputs go to `out/` (not committed); `out/result.blend` holds the rig with the baked motion and the generated SOMA armature next to it.

## Results (2026-10-31)

Test: a generated Rigify human rig in FK, three full-body key poses on its controls (frame 1 standing, frame 61 mid-stride 0.7 m ahead, frame 120 arms raised 1.5 m ahead), 30 fps, prompt "A person walks forward and raises both arms".

| Step | Result |
|---|---|
| Rig → SOMA, limbs in **REST_OFFSET** mode | **Wrong**: limbs off by up to 34° (arms), the same at every frame. |
| Rig → SOMA, limbs in **ROLL** mode, spine in REST_OFFSET | **Exact**: 0.0° on every limb bone. |
| Kimodo generation (4 s, 3 key poses) | 19 s. Key poses hit exactly (0.00 cm). |
| SOMA → rig, at the key frames | The rig gets its own key poses back **exactly** (0.0°, 0.0 cm on hands, feet, head). |
| SOMA → rig, over the whole clip | 120 keys baked. The rig follows the generated motion within 0.05° on average (max 1.8°, on a hand). |
| Floor contact | Lowest toe tip between -0.4 cm and 7.8 cm over the clip (1.7 cm at rest): feet stay on the floor. |
| The motion itself | Plausible walk into the stride pose, then the arms rise into the last pose (see `out/generated_strip.png`). |

**Phase 1 done**: the full chain works on a real controller rig, with no change to the Retargetor's code.

## IK test (2026-10-31)

Same key poses, animated with **IK controls only** (`hand_ik`, `foot_ik`, `toe_ik`, pole targets, pole vectors on), FK limb keys removed. Outputs in `out/ik/`.

| Step | Result |
|---|---|
| Building the IK key poses from the FK ones | Close, not identical: 0.3–0.6° mean, up to 2.7° on the arms (see the stretch point below). |
| **Read side**: rig → SOMA, unchanged script | **Exact**: 0.0° on every limb. Reading from the `ORG-` bones doesn't care whether the limb is in FK or IK. |
| Kimodo generation | Key poses hit exactly. |
| **Write side**: bake onto the FK chain, then transfer FK → IK on every frame (IK control on the hand/foot, pole in the plane of the chain) | Works. Key poses back within 0.2–0.3° mean (max 1.6°), hands and feet within 0.5 cm. |
| Over the whole clip | Hands and feet **exact** (0.02 cm). Limb directions 0.7° mean, max 5.6°. Elbows up to 1.8 cm off, knees up to 4.4 cm. Feet on the floor (lowest toe -0.9 cm). |

**Why elbows and knees are a little off:** Rigify's IK bones have `ik_stretch = 0.1`, so Blender's IK solver shrinks the bones slightly (about 1.4%) instead of bending the joint fully: the knee bends less while the foot stays in place. Confirmed by setting `ik_stretch` to 0 in memory: elbows and right knee become exact (0.0 cm), left knee 1.7 cm. The `IK_Stretch` slider of the rig does not control this. It is the rig's own behaviour (an animator posing in IK gets the same), so we can accept it, compensate for it, or let the user turn it off. To decide in Phase 4.

Things tried that did **not** help: rotating the pole around the limb axis to minimize the elbow/knee error (no gain, the pole wasn't the cause), and turning off the rig's `IK_Stretch` slider.

## What goes wrong, or needs work

1. **REST_OFFSET copies the rotation from rest, not the direction.** When the two rest poses differ (Rigify's arms slope down, SOMA is in a T-pose), the limbs are off by the rest difference. ROLL mode copies the direction and only corrects the twist, which is right for limbs. The spine works in REST_OFFSET (both rigs stand upright at rest, and their spine bones are laid out differently). → Each humanoid role needs a **default offset mode** (limbs ROLL, spine and hips REST_OFFSET).
2. **Reading and writing use different bones.** The pose is read from Rigify's `ORG-` bones (the result of FK/IK), but written to the FK controls (`upper_arm_fk.L`, `torso`, …). → The rig profile needs, per role, **a bone to read and a control to write**.
3. **IK needs an extra step on the write side.** Reading works in FK and IK alike. Writing goes through the FK chain, then an FK → IK transfer per frame (see the IK test above). This transfer is rig-specific (Rigify's controls, poles, switch properties): the rig profile will need to describe it.
4. **Spine partly written.** Only `torso` (Hips, with translation), `chest`, `neck` and `head` are written; Spine1 and Spine2 are left to Rigify's chest interpolation. Exact at the key poses, not measured in between.
5. **Heading not handled.** The rig faces -Y, which happens to be Kimodo's default heading. A character facing another way needs its heading canonicalized (rotation around the vertical axis, or Kimodo's `first_heading_angle`), like the root position already is.
6. **Frame rate.** The scene was set to 30 fps, Kimodo's rate. Other rates need resampling.
7. **Duration.** Chosen by hand to span the key frames (4 s = 120 frames).
8. **The bake overwrites everything**, with ordinary `KEYFRAME` keys on every frame, user keys included. Expected at this stage; the `GENERATED` keys are Phase 3.
9. **Blender 5 layered actions**: `Action.fcurves` no longer exists; F-curves are reached through the slot's channelbag (`bpy_extras.anim_utils.action_get_channelbag_for_slot`). Any new code reading keys must do the same.
10. **Your Blender loads this working tree.** `extensions/vscode_development/retargetor` in Blender 5.1 is a link to the repository: switching branches changes the add-on in Blender, and `spikes/` must be excluded from the extension build. Headless runs use `--factory-startup` so the add-on isn't registered twice.

## Scripts

| Script | Runs with | Does |
|---|---|---|
| `make_rig.py` | Blender 5.1 | Generates the Rigify rig in FK and keys the three poses → `out/rig_keyposes.blend` |
| `make_rig_ik.py` | Blender 5.1 | Turns those poses into IK-only key poses → `out/rig_keyposes_ik.blend` |
| `rig_to_soma.py` | Blender 5.1 | Snaps SOMA to the key poses with the Retargetor, measures it, writes `out/constraints.json` and `out/canonical.json` |
| `soma_to_rig.py` | Blender 5.1 | Imports the generated BVH, retargets it onto the FK controls (then onto the IK controls with `ik`), compares the key poses → `result.blend` |
| `check_result.py` | Blender 5.1 | Checks the bake over the whole clip (keys, fidelity, floor contact) |
| `draw_strip.py` | Kimodo venv | Draws the generated motion as stick figures → PNG |
| `spike_common.py` | (imported) | Bone mappings, SOMA import, Kimodo conversions, Retargetor setup |

Requires the Phase 0 outputs (`../phase0/out/soma_reference.blend`, `../phase0/out/soma_skeleton.json`).

## Reproduce

From this folder, in Git Bash, with `K` set to the Kimodo venv and `B` to Blender 5.1:

```bash
"$B" -b --factory-startup --python make_rig.py -- out
"$B" -b --factory-startup out/rig_keyposes.blend --python rig_to_soma.py -- out roll 1 61 120
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 $K/Scripts/kimodo_gen.exe "A person walks forward and raises both arms" --model Kimodo-SOMA-RP-v1.1 --duration 4.0 --constraints out/constraints.json --output out/generated --bvh --bvh_standard_tpose --seed 1
"$B" -b --factory-startup out/rig_keyposes.blend --python soma_to_rig.py -- out out/generated.bvh fk 1 61 120
"$B" -b --factory-startup out/result.blend --python check_result.py
$K/Scripts/python.exe -I draw_strip.py out/generated.npz ../phase0/out/soma_skeleton.json out/generated_strip.png 0 60 119
```

IK test, after the FK steps above:

```bash
mkdir -p out/ik
"$B" -b --factory-startup out/rig_keyposes.blend --python make_rig_ik.py -- out 1 61 120
"$B" -b --factory-startup out/rig_keyposes_ik.blend --python rig_to_soma.py -- out/ik roll 1 61 120
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 $K/Scripts/kimodo_gen.exe "A person walks forward and raises both arms" --model Kimodo-SOMA-RP-v1.1 --duration 4.0 --constraints out/ik/constraints.json --output out/ik/generated --bvh --bvh_standard_tpose --seed 1
"$B" -b --factory-startup out/rig_keyposes_ik.blend --python soma_to_rig.py -- out/ik out/ik/generated.bvh ik 1 61 120
"$B" -b --factory-startup out/ik/result.blend --python check_result.py
```
