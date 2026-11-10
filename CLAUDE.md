# CLAUDE.md

## Project

Retargetor is a Blender extension (Blender 5.2+) that retargets animation between armatures with different rest poses. It is the first piece of a larger extension: the user poses their own rig, an AI motion model generates the movement between the key poses, and the result comes back onto the rig. Read [ROADMAP.md](ROADMAP.md) for the goal, the architecture, the phases and the decisions.

## Architecture rules

- **The motion model must be swappable.** Kimodo is only the first backend. No Kimodo name, constant or convention (Y-up, axis-angle, SOMA joint names, 30 fps) outside `backends/kimodo/`.
- **Blender never imports the model or torch.** Each backend runs as a worker process with its own Python, and talks to Blender over JSON.
- **Blender-side data uses Blender conventions**: Z-up, meters, quaternions, Blender frame numbers and scene fps. The backend adapter converts.
- **Pure logic stays free of `bpy`** when it can (conversions, neutral types), so it can be tested with plain Python and numpy.

## Current layout

| File | Role |
|---|---|
| `__init__.py` | Entry point, bone selection handler |
| `properties.py` | Stored data: rig profile on `Armature.retargetor_profile`, character state on `Object.retargetor` (prompt, seed, custom range, prompt segments), `Scene.retargetor_target` (which character the panel edits) |
| `migration.py` | `load_post` handler moving the old `scene.retarget_*` setups onto the target object |
| `setup_operators.py` | Bone list setup, translation scale, JSON import/export, corrections |
| `retarget_operators.py` | Snapping and baking operators |
| `profile_operators.py` | Rig profile: presets (fitted: optional roles whose bones are missing left out), skeleton detection (`detect_profile`: preset, else `core.rig_detect`; cached per armature), Detect / Assign / Select / Clear a role, Check Rig (`checked`: one check per profile, run by Generate), JSON, Snap FK to IK |
| `rig_check.py` | The rig check: `profile_problems` (static) and `control_problems` (each write control turned, each IK limb snapped and switched both ways; pose put back) |
| `ui.py` | Sidebar panels and lists (Retarget, Rig Setup with its IK/FK Limbs and Advanced sub-panels, Generate); the animation editors' header (model state, Generate or progress, bands toggle, Retargetor menu) |
| `preferences.py` | Add-on preferences: active backend, developer option, each backend's settings (declared by the backend) |
| `generation.py` | Generate In-betweens step by step (`GenerationTask`): key poses, model armature, request, result baked as `GENERATED` keys (`MotionWriter`), IK controls snapped back (`IkSnapWriter`); the whole track or one segment alone (`segment_chunk`: the motion around it as context) |
| `generated_keys.py` | Edited `GENERATED` keys become Keyframes as soon as they are edited: values recorded after each generation, compared by a depsgraph handler. Also records the user keys the add-on makes itself (FK snap...), and `clear()` removes both |
| `segment_track.py` | A character's prompt segments (`Object.retargetor.segments`) read and written as a `core.segments` track, kept contiguous when a start or end is edited; generated state |
| `segment_operators.py` | Add, remove, split, select prompt segments, previous / next |
| `segment_draw.py` | Prompt segments drawn as bands in the Dope Sheet and Graph Editor (layout and hit test as plain functions), View menu toggle |
| `segment_mouse.py` | The bands handled with the mouse (keymap items passing the event through off the bands): hover, click, drag, popup, menu |
| `generate_operators.py` | Generate and Regenerate Segment (modal, Esc cancels; `execute` blocks, for scripts and tests), cancel, Clear Generated Keys, start / stop the model |
| `core/retarget/` | `pairs.py` (`BonePair`, no `bpy`), `snap.py` (`Retargeter`: snap and bake on given frames, offsets computed from the rigs, each bone keyed in its own rotation mode), `fk_snap.py` (FK controls snapped to the IK pose before generating, IK controls snapped to the generated FK pose after) |
| `core/roles.py`, `core/profile.py` | Humanoid roles (required ones marked) and the rig profile in neutral form, `compose()` (no `bpy`) |
| `core/rig_detect.py` | Roles found on a skeleton from its names and hierarchy, the rig's body frame, swapped sides (no `bpy`) |
| `core/segments.py` | `PromptSegment` and the contiguous track: move a boundary or a segment, split, append, remove (no `bpy`) |
| `core/motion.py`, `core/pose_io.py` | `Pose` / `Motion` / `GenerationRequest` (no `bpy`), read and written on an armature; `write_motion_fcurves` writes a whole motion in bulk |
| `core/skeleton.py`, `core/skeleton_io.py` | A backend's skeleton in neutral form (no `bpy`), and the armature built from it |
| `core/quat.py` | Quaternion helpers on numpy arrays (no `bpy`) |
| `backends/` | `base.py` (what a backend declares), `protocol.py` (JSON lines protocol, shared with the workers), `process.py` (worker process), `registry.py` (backends list, running workers) |
| `backends/interpolate/` | Test backend: slerp between key poses, one joint per role; worker runs with Blender's Python |
| `backends/kimodo/` | Kimodo: role map and constants (`joints.py`), conversions (`convert.py`), `worker.py` (runs in the Kimodo venv) |
| `presets/` | Rig profile presets (JSON): Rigify, Auto-Rig Pro, CloudRig |
| `tests/` | `unit/` (Blender's Python, numpy, no `bpy`), `blender/` (headless), `kimodo/` (Kimodo venv), `fixtures/` (synthetic skeletons named like common rigs in `humanoids.py`, the real rigs' manifest `real_rigs.json`); `python tests/run_tests.py` runs them all |

The core takes its inputs as arguments; only the operators read the panel's character. Rest offsets are computed from the two rigs, not stored.

A backend is a folder in `backends/` with a `Backend` subclass (`backend.py`) and a worker script, listed in `backends/registry.py`; nothing outside `backends/` names a backend. Workers run with `python -I` and import only `backends.protocol` and `core.*` (no `bpy`): keep `backends/__init__.py` and `core/__init__.py` free of imports.

## Conventions

- Operators: `bl_idname = "retargetor.<name>"`, classes prefixed `RTGTR_`.
- Helpers raise `KeyError` / `ValueError` with an explicit message; operators catch them and `self.report()` them.
- All UI text and messages in English.
- Target bones use quaternion rotation; keep quaternion signs continuous between keyframes.
- Keep the README up to date when a user-facing feature changes.

## Testing

- All tests: `python tests/run_tests.py --spikes <folder with phase0/out and phase1/out> [--kimodo-python <venv python.exe>] [--rigs <rigs.json>]` (the chain tests need the spike outputs, which are not committed; the Kimodo tests need the venv and a CUDA GPU, and take a few minutes; `--rigs` maps the files of `tests/fixtures/real_rigs.json` to the real rigs on this machine, which are not committed either).
- `--gui` also runs the tests needing Blender's interface (`test_segment_mouse.py`: the segment bands with simulated mouse events). A window opens on the user's screen for about a minute: say so first. Never start a Blender with its interface without `BLENDER_USER_RESOURCES` pointed at a scratch folder (`run_tests.py` does it): a preference save in that session (the "scripts disabled" popup with "Permanently allow" does one) would overwrite the user's real preferences. The first simulated events after start don't reach the editor: the test warms up with a cancelled drag.
- Unit tests run with Blender's own Python (numpy included), found next to `blender.exe`.
- Headless: `"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup <file.blend> --python <script.py>`. The `blender` on PATH is 5.0, which is too old for this extension.
- `fcurve.update()` may move the keys in memory: look keyframe points up again after it (a kept reference reads and writes garbage).
- Setting a custom property from Python doesn't tag the object: call `obj.update_tag()` before reading anything driven by it (Rigify's IK/FK switch).
- Live inspection goes through the Blender MCP connector; it needs Blender running with the MCP add-on server started.
- Setting `pose_bone.matrix` ignores the bone's own constraints (Auto-Rig Pro's IK controls have Child Of constraints, CloudRig's FK toe an Armature one): `fk_snap` places such controls again through them.
- Machine-specific paths (Kimodo venv, test files, real rigs) are in `CLAUDE.local.md`, which is not committed.

## Git

- `main` always stays a working add-on.
- One short-lived branch per milestone (for example `refactor/retarget-core`, `backends/kimodo`), merged through a PR on `Maxiriton/retargetor`.
