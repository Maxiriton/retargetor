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
| `properties.py` | Stored data: rig profile on `Armature.retargetor_profile`, character state on `Object.retargetor`, `Scene.retargetor_target` (which character the panel edits) |
| `migration.py` | `load_post` handler moving the old `scene.retarget_*` setups onto the target object |
| `setup_operators.py` | Bone list setup, translation scale, JSON import/export, corrections |
| `retarget_operators.py` | Snapping and baking operators |
| `profile_operators.py` | Rig profile: presets, roles, JSON, Snap FK to IK |
| `ui.py` | Sidebar panels and lists |
| `core/retarget/` | `pairs.py` (`BonePair`, no `bpy`), `snap.py` (`Retargeter`: snap and bake on given frames, offsets computed from the rigs), `fk_snap.py` |
| `core/roles.py`, `core/profile.py` | Humanoid roles and the rig profile in neutral form, `compose()` (no `bpy`) |
| `core/motion.py`, `core/pose_io.py` | `Pose` / `Motion` / `GenerationRequest` (no `bpy`), read and written on an armature |
| `presets/` | Rig profile presets (JSON) |
| `tests/` | `unit/` (plain Python), `blender/` (headless), `fixtures/`; `python tests/run_tests.py` runs them all |

The core takes its inputs as arguments; only the operators read the panel's character. Rest offsets are computed from the two rigs, not stored.

## Conventions

- Operators: `bl_idname = "retargetor.<name>"`, classes prefixed `RTGTR_`.
- Helpers raise `KeyError` / `ValueError` with an explicit message; operators catch them and `self.report()` them.
- All UI text and messages in English.
- Target bones use quaternion rotation; keep quaternion signs continuous between keyframes.
- Keep the README up to date when a user-facing feature changes.

## Testing

- All tests: `python tests/run_tests.py --spikes <folder with phase0/out and phase1/out>` (the chain tests need the spike outputs, which are not committed).
- Headless: `"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup <file.blend> --python <script.py>`. The `blender` on PATH is 5.0, which is too old for this extension.
- Setting a custom property from Python doesn't tag the object: call `obj.update_tag()` before reading anything driven by it (Rigify's IK/FK switch).
- Live inspection goes through the Blender MCP connector; it needs Blender running with the MCP add-on server started.
- Machine-specific paths (Kimodo venv, test files) are in `CLAUDE.local.md`, which is not committed.

## Git

- `main` always stays a working add-on.
- One short-lived branch per milestone (for example `refactor/retarget-core`, `backends/kimodo`), merged through a PR on `Maxiriton/retargetor`.
