# CLAUDE.md

## Project

Retargetor is a Blender extension (Blender 5.2+) that retargets animation between armatures with different rest poses. It is the first piece of a larger extension: the user poses their own rig, an AI motion model generates the movement between the key poses, and the result comes back onto the rig. Read [ROADMAP.md](ROADMAP.md) for the goal, the architecture, the phases and the decisions.

## Architecture rules

- **The motion model must be swappable.** Kimodo and ARDY are two backends among others. No model's name, constant or convention (Y-up, axis-angle, SOMA joint names, 30 fps) outside its folder in `backends/`; what several backends share (NVIDIA's Y-up conventions, the SOMA skeleton) lives in `backends/shared/`, never in the add-on.
- **Blender never imports the model or torch.** Each backend runs as a worker process with its own Python, and talks to Blender over JSON.
- **A backend declares what its model needs** (`Backend.requirements()`: Python, packages, weights; `backends/setup/spec.py`); the add-on installs and checks it from that. Never ask for, read, store or send the user's Hugging Face token: huggingface_hub uses their own sign-in.
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
| `preferences.py` | Add-on preferences: active backend, models' folder, developer option, each backend's settings (declared by the backend) and environment (`setup_<id>`: installed by the add-on or existing) |
| `model_setup.py` | The models' setup, Blender side: the environment's Python and paths (`worker_for`), install / check / remove / sign-in operators, a timer following them, the Models section of the preferences, `setup_problem` for the headers |
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
| `backends/setup/` | Installing and checking a model (no `bpy`): `spec.py` (Requirements, Machine), `machine.py` (nvidia-smi), `paths.py` (models' folder, Hugging Face cache), `uv.py` (pinned uv download), `installer.py` (steps, `install.json`, resume, repair, remove), `weights.py` (weights on disk), `checks.py` (CheckItems with their fix), `signin.py`; `env_check.py` and `env_download.py` run with the model environment's Python |
| `backends/interpolate/` | Test backend: slerp between key poses, one joint per role; worker runs with Blender's Python |
| `backends/shared/` | What several backends share (no `bpy`): `convert.py` (Blender <-> Y-up model conversions, timing, canonical frame, constraint lists, `FrameStream` for streamed windows; Kimodo and ARDY), `soma.py` (SOMA's role map and end-effectors) |
| `backends/kimodo/` | Kimodo: constants (`joints.py`, SOMA from `shared/soma.py`), what it installs (`install.py`: Aero-Ex's fork, pinned), `worker.py` (runs in the Kimodo venv) |
| `backends/ardy/` | ARDY: its checkpoints (`models.py`: SOMA 30 fps or Core 20 fps, each with its joint map), what it installs (`install.py`: pinned commit, its C++ post-processing built when a compiler is there), `backend.py` (capabilities per checkpoint: `configured(settings)`), `worker.py` (window by window, streamed) |
| `presets/` | Rig profile presets (JSON): Rigify, Auto-Rig Pro, CloudRig |
| `tests/` | `unit/` (Blender's Python, numpy, no `bpy`), `blender/` (headless), `kimodo/` (Kimodo venv), `fixtures/` (synthetic skeletons named like common rigs in `humanoids.py`, the real rigs' manifest `real_rigs.json`); `python tests/run_tests.py` runs them all |

The core takes its inputs as arguments; only the operators read the panel's character. Rest offsets are computed from the two rigs, not stored.

A backend is a folder in `backends/` with a `Backend` subclass (`backend.py`) and a worker script, listed in `backends/registry.py`; nothing outside `backends/` names a backend. Workers run with `python -I` and import only `backends.protocol`, `backends.shared.*`, their own backend's modules without `bpy`, and `core.*`: keep `backends/__init__.py`, `backends/shared/__init__.py` and `core/__init__.py` free of imports. A backend whose capabilities, joint map or skeleton depend on its settings returns a backend declaring them from `configured(settings)` (`preferences.active_backend` applies it), and names its skeleton with `skeleton_id` (the model's armature is rebuilt when it changes).

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
- `test_model_setup.py` uses the Kimodo venv as an existing environment when `--kimodo-python` is given; `--models-folder` (Kimodo installed by the add-on there) checks it and generates with it. Processes started from the Claude desktop app see `%LOCALAPPDATA%` redirected to the app's package folder: never install there for a test (Blender can't see it), use another folder. The install itself is tested with fake steps (`tests/unit/test_setup.py`); a real install downloads GB: ask the user first, and point `models_folder` and `HF_HOME` to a scratch folder for a throwaway one.

## Git

- `main` always stays a working add-on.
- One short-lived branch per milestone (for example `refactor/retarget-core`, `backends/kimodo`), merged through a PR on `Maxiriton/retargetor`.
