# Retargetor

**Retarget an animation from one armature to another, even when their rest poses don't match, and generate the motion between your key poses with an AI motion model.**

Retargetor is a Blender add-on that copies an animation bone by bone from a *source* armature to a *target* armature. It corrects the orientation differences between the two rest poses, scales the root motion to the size of the target, and bakes the result as keyframes on the target.

It can also **generate in-betweens**: pose your own rig at a few key frames, and a motion model (NVIDIA Kimodo for now) generates the movement between them, written back on your rig's controls.

> **Status:** early version (0.0.1). It works, but expect rough edges. Feedback is welcome.

---

## Features

- **Bone-by-bone matching** with an editable list: pick the target bone for every source bone.
- **Automatic first guess** of the matching from bone names (exact match first, then partial match; a target bone is never used twice).
- **Two ways to fix rest pose differences**, selectable per bone:
  - **Roll**: compensates the rotation around the target bone's Y axis.
  - **Offset**: compensates the full rotation difference between the two rest poses.
- **Manual corrections**: pose a bone by hand and record the difference, for the cases where the automatic offsets aren't enough.
- **Translation on demand**: only the bones you flag with **Use Translation** copy the source's movement (typically `Root` and `Hips`).
- **Translation scale**: the root motion is scaled by the size ratio between the two rigs, so a small character doesn't slide like a giant one.
- **Smooth rotations**: quaternion signs are kept continuous from frame to frame, so bones never spin the long way round between two keyframes.
- **Import / export** of the matching as JSON, to reuse a setup on other scenes.
- **Several characters per scene**: each target armature keeps its own setup.
- **Rig profile**: map a rig once to humanoid roles (hips, upper arm, shin...), with a bone to read and a control to write for each, and snap the FK controls of IK-posed limbs. A Rigify preset is included.
- **Generate In-betweens**: the motion between your key poses, from a motion model running in its own process (Blender never freezes, and never loads the model itself). Your keys are never overwritten; the result comes as **Generated** keys. See [ROADMAP.md](ROADMAP.md) for what comes next.

## Requirements

- Blender **5.2** or newer.
- For **Generate In-betweens** with Kimodo: a working install of NVIDIA Kimodo in its own Python environment, with the model weights already downloaded, and an NVIDIA GPU (about 7 GB of video memory). The add-on never downloads anything.

## Installation

1. Zip the add-on folder (the folder containing `__init__.py` and `blender_manifest.toml`).
2. In Blender, open **Edit > Preferences > Get Extensions**, then use **Install from Disk** (the dropdown arrow in the top right) and choose the zip.
3. Enable **Retargetor**.

The panel appears in the 3D Viewport sidebar (press `N`), in the **Retarget Tool** tab.

## Quick start

1. **Choose the armatures.** Set **Target** (the armature that should receive the animation), then **Source** (the one that holds it). The setup is stored on the target object, so each character of the scene keeps its own; switching **Target** switches the setup shown in the panel.
2. **Build the bone list.** Click **Setup Bone list**, or **Import from JSON** if you already have a setup. Retargetor lists every source bone and proposes a target bone by name.
3. **Review the matching.** For every row:
   - set the target bone (leave it empty to ignore a source bone),
   - choose **Roll** or **Offset** for the rest pose correction,
   - switch on the translation button for the bones that carry the root motion.
4. **Check the translation scale.** Click **Auto** next to **Translation Scale** to compute it, or type your own value.
5. **Retarget.** Click **Retarget**. The animation is baked on the target over the scene's frame range (**Start** to **End**).

## The bone list

Each row shows, from left to right:

| Column | Meaning |
|---|---|
| Source bone | A check mark means the offsets were computed for this pair. |
| Target bone | Searchable field. Empty means the source bone is ignored. |
| Translation button | When on, the bone also copies the source's movement. |
| Offset mode | **Roll** or **Offset** (see below). |
| Record button | **Record Correction**, **Update Record** or **Finish Recording**. |

Selecting a bone in Pose Mode (on either armature) selects the matching row in the list.

### Roll vs Offset

- **Roll** fixes the case where the two bones point the same way but are twisted differently around their own axis.
- **Offset** applies the full rotation between the two rest poses. Try it when Roll isn't enough.

Both are computed from the rest poses of the two armatures each time you snap or retarget, so they are always up to date.

### Recording a correction

When an automatic offset is almost right but not quite:

1. Select the row and click **Record Correction**. The target bone is selected in Pose Mode.
2. Rotate the bone by hand until it looks right.
3. Click **Finish Recording**.

The difference is stored and applied on top of the automatic offset. **Update Record** adds a new correction to the existing one, and the **X** button clears it. Changing a row's target bone also clears its correction, since it no longer applies.

## Translation and scale

By default, every bone only receives a **rotation**. For the root motion to come through, switch on the translation button of the bones that should move through space, usually `Root` and `Hips`.

For these bones, the target position is:

```
target = target rest position + scale × (source position − source rest position)
```

The target keeps its own standing height, and only the *movement* is scaled.

**Auto** computes the scale as the ratio of the heights of the two rigs, measured on the bones that are matched (Z extent of the bone heads in rest pose, in world space). Check the heights it reports: if they look wrong, enter the scale by hand. The scale is **not** saved in the JSON, because it depends on the two rigs of the current scene.

## Snapping tools

Useful to tune the setup before baking:

- **Snap active bone** aligns the active target bone to its source at the current frame.
- **Snap full pose** aligns every matched bone at the current frame.

Both work in Pose Mode on the target armature.

## JSON setups

**Export to JSON** saves the whole list: bone names, offset modes, translation flags and recorded corrections. **Import from JSON** loads it back onto the current target, and recomputes the translation scale if the source is set.

Files exported by older versions can still be imported. Missing fields fall back to safe defaults (no translation, no correction); the rest offsets they contain are ignored, since they are computed from the rigs.

## Files made with older versions

Older versions stored the setup on the scene (one per scene). When such a file is opened, the setup is moved onto its target armature object automatically, and the scene's **Target** is set to it. The setup is left on the scene, and a message is printed in the console, when it can't be moved: no target armature, a linked target, or a target that already has a bone list. In that case, open the file with the old version, **Export to JSON**, then open it with this version and **Import from JSON** on the target.

## Rig profile

The **Rig Profile** panel (same tab) describes how the **active armature** maps to humanoid roles. It is stored on the armature data, so every object using that armature shares it, and it travels with a rig linked from a library.

- **Load Preset** fills it from a preset (Rigify human, with its FK controls), **Add Roles** adds the missing roles with their defaults.
- Per role: **Read** is the bone whose pose is read (on Rigify, the `ORG-` bone, the result of FK and IK), **Write** is the control that receives motion (on Rigify, the FK control; empty means the role isn't written), Use Translation, and the offset mode. Limbs default to **Roll**, the spine, neck and head to **Offset**.
- **IK limbs**: for each limb, the FK controls and the bone each one follows, and the IK/FK switch property. **Snap FK to IK** rotates the FK controls onto the current pose on the frames you list (for example `1, 61, 120`, or empty for the current frame), keys them, and switches the limbs to FK. IK keys are kept.
- **Import Profile** / **Export Profile** save it as JSON, to reuse it on a similar rig.

### Linked rigs and library overrides

Set the profile up in the rig's own file. In a shot file that links the rig, the profile is read-only. A library override of the character overrides the object (so the per-character setup in the Retarget panel can be edited and is saved) but **not the armature data**, even with a fully editable override: the profile stays the library's, and edits made there would not be saved. To change the profile in a shot only, override the armature data too (from Python: `rig.data = rig.data.override_create(remap_local_usages=True)`; the Outliner's **Library Override > Make** on the armature data should do the same). Values you change then win over the library, and the others still follow it.

## Generate in-betweens

1. **Choose the character** as **Target** in the Retarget panel. A **Rigify** rig needs nothing else: its rig profile is filled from the Rigify preset as soon as you choose it (any rig whose bones match a preset of the add-on gets it; the Generate panel says which). For another rig, set up its profile in the Rig Profile panel.
2. **Key your poses** on the controls of the profile (on Rigify, the FK or IK controls and the torso). Any keyframe type works except **Generated**: Keyframe, Breakdown, Extreme... A frame is a key pose as soon as one of those controls has a key on it.
3. **Limbs in IK** are handled for you: the generated motion is written to the FK controls, so before generating, the FK controls of a limb in IK are snapped to its IK pose on each key pose (keyed as normal keys) and the limb is switched to FK. Your IK keys are kept. If the IK/FK switch is animated, it is keyed in FK on the key poses and the ends of the range; a switch key in IK between two key poses stops the generation (key the switch in FK there, or key a pose on that frame). After generation the limbs play in FK.
4. In the **Generate** panel, write a **prompt** (what the character does) and choose a **seed**, then click **Generate In-betweens**. The panel and the status bar show the progress: the model's own steps, then the keys being written onto the rig. **Esc** (or the cancel button) stops the generation until the keys are being written; writing takes a few seconds and can't be stopped (Blender stays responsive meanwhile, you can look around but not edit).

The model generates the motion from your first key pose to your last one. The result is written on the rig's controls as **Generated** keys, on every frame between the key poses.

**Range**: **Key Poses** (the default) goes from the first key pose to the last one. **Custom** sets a start frame (the current frame when you switch to Custom, or the clock button) and a duration: the panel shows the frames, the seconds and the key poses inside. Key poses outside the range are ignored (and never touched). With a custom range you can:

- generate from the **prompt alone**, with no key pose: the motion starts where the character stands on the start frame, facing where it faces (on Rigify, move or turn the **root** control: it isn't a control of the profile, so it doesn't make a key pose);
- start from **one key pose**, or end on one: the motion starts where the character stands on the start frame, so to walk up to a key pose, place the root where the walk starts;
- **extend** an animation past its last key pose.

**Partial poses**: a frame where you keyed only some controls (an arm, a foot...) is a partial key pose. With Kimodo it pins only what you keyed: a hand or a foot where your pose puts it (and the hips, which Kimodo always pins on a constrained frame); keying the spine, the neck or the head pins the whole body. The rest of that frame is generated, and your keys stay as they are. Since your keys are FK rotations, the keyed limb follows the generated body on that frame: if the body moves a lot there, the hand or foot lands away from where you posed it. Key the body as well to keep the whole pose.

Kimodo needs no key pose and generates up to 10 s; the panel says when the range is too long, or has fewer key poses than the backend needs (the interpolation test backend needs two). Frames carrying one of your keys are never written. Generating again replaces the Generated keys of the range and keeps yours. The whole generation is one undo step.

- The first generation starts the model (about 20 s with Kimodo); the model then stays loaded, and the next ones take about 3 s plus the time to write the keys (about 3 s for 120 frames). **Start** / **Stop** in the panel load the model ahead of time, or free its memory.
- The model's skeleton is added to the scene as a hidden armature, in a **Retargetor Models** collection, next to your character.
- Kimodo works at 30 fps and up to 10 s; other scene rates are handled (the key poses land exactly on the model's frames, the result is resampled to the scene's rate). A character facing any direction works.
- **Editing a Generated key makes it yours**: as soon as you change a generated key (move it in the Graph Editor or the Dope Sheet, or key over it after posing the rig), it becomes a **Keyframe**, with the other channels of the same property on that frame, so the next generation keeps it and uses it as a key pose. Cancel the move (right click) and it goes back to Generated. You can also promote a generated key without changing it: **Key > Keyframe Type**.

### Preferences

**Edit > Preferences > Add-ons > Retargetor**:

- **Backend**: the motion model. **Kimodo** for now.
- **Kimodo Python**: the Python executable of the environment where Kimodo is installed (for example `kimodo-venv\Scripts\python.exe`). **Model**: the Kimodo model to load (`Kimodo-SOMA-RP-v1.1` by default).
- **Developer**: also lists the test backends (an interpolation without any model, for tests).

## Good to know

- Only **matched** bones receive keyframes: rotation for all of them, location only for those flagged with translation.
- Two source bones can't point to the same target bone. Retargetor stops with an explicit message if that happens.
- The target bones keep their rotation mode (quaternion, Euler or axis-angle); quaternion keys keep continuous signs.
- With **Rigify** targets, match the **FK** controls and set the limbs to FK, otherwise the snapped bones will have no visible effect.
- Retargeting scales the root motion, but it can't remove foot sliding when the legs of the two rigs have very different proportions.
- **Retarget** runs over the scene's frame range and can take a while on long animations.

## Project layout

| File | Role |
|---|---|
| `__init__.py` | Add-on entry point, selection handler |
| `properties.py` | Where the data is stored: rig profile (Armature), character setup (Object) |
| `migration.py` | Moves setups saved by older versions off the scene |
| `setup_operators.py` | Bone list setup, translation scale, JSON import/export, corrections |
| `retarget_operators.py` | Snapping and baking |
| `profile_operators.py` | Rig profile: presets, roles, JSON, Snap FK to IK |
| `ui.py` | Sidebar panels and lists |
| `preferences.py` | Add-on preferences: backend, its settings, developer option |
| `generation.py`, `generate_operators.py` | Generate In-betweens: key poses, request, result as Generated keys; operators |
| `core/` | Retargeting core, humanoid roles, neutral motion and skeleton types (see below) |
| `backends/` | Motion model backends, each in its own folder (`kimodo/`, `interpolate/`), and the protocol with their worker processes |
| `presets/` | Rig profile presets |
| `tests/` | Unit tests, headless Blender tests, Kimodo tests (`python tests/run_tests.py`, see the file) |
| `blender_manifest.toml` | Extension manifest |

The core can be used from scripts, without the scene properties: `core.retarget.snap.Retargeter(source, target, pairs, translation_scale)` snaps (`snap_pose`) or bakes (`bake(scene, view_layer, frames)`) a list of `BonePair`s, and `core.profile.compose(profile, joint_map, direction)` builds those pairs from a rig profile and a skeleton's role → joint map.

## License

GPL-3.0-or-later, as declared in the manifest.

## Author

Henri Hebeisen
