# Retargetor

**Retarget an animation from one armature to another, even when their rest poses don't match.**

Retargetor is a Blender add-on that copies an animation bone by bone from a *source* armature to a *target* armature. It corrects the orientation differences between the two rest poses, scales the root motion to the size of the target, and bakes the result as keyframes on the target.

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

## Requirements

- Blender **5.1** or newer.

## Installation

1. Zip the add-on folder (the folder containing `__init__.py` and `blender_manifest.toml`).
2. In Blender, open **Edit > Preferences > Get Extensions**, then use **Install from Disk** (the dropdown arrow in the top right) and choose the zip.
3. Enable **Retargetor**.

The panel appears in the 3D Viewport sidebar (press `N`), in the **Retarget Tool** tab.

## Quick start

1. **Choose the armatures.** Set **Source** (the armature that holds the animation) and **Target** (the one that should receive it).
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

Both are computed automatically from the rest poses when a target bone is set.

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

**Export to JSON** saves the whole list: bone names, offsets, offset modes, translation flags and recorded corrections. **Import from JSON** loads it back. If both armatures are set, the rest pose offsets are recomputed from the current scene on import, and the translation scale is recomputed as well.

Files exported by older versions can still be imported. Missing fields fall back to safe defaults (no translation, no correction).

## Good to know

- Only **matched** bones receive keyframes: rotation for all of them, location only for those flagged with translation.
- Two source bones can't point to the same target bone. Retargetor stops with an explicit message if that happens.
- The target bones are switched to quaternion rotation.
- With **Rigify** targets, match the **FK** controls and set the limbs to FK, otherwise the snapped bones will have no visible effect.
- Retargeting scales the root motion, but it can't remove foot sliding when the legs of the two rigs have very different proportions.
- Retargeting runs over the scene's frame range and can take a while on long animations.

## Project layout

| File | Role |
|---|---|
| `__init__.py` | Add-on entry point, properties, selection handler |
| `setup_operators.py` | Bone list setup, offsets, translation scale, JSON import/export, corrections |
| `retarget_operators.py` | Snapping and baking |
| `ui.py` | Sidebar panel and bone list |
| `blender_manifest.toml` | Extension manifest |

## License

GPL-3.0-or-later, as declared in the manifest.

## Author

Henri Hebeisen
