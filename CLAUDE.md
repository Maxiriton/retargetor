# CLAUDE.md

## Project

Retargetor is a Blender extension (Blender 5.1+) that retargets animation between armatures with different rest poses. It is the first piece of a larger extension: the user poses their own rig, an AI motion model generates the movement between the key poses, and the result comes back onto the rig. Read [ROADMAP.md](ROADMAP.md) for the goal, the architecture, the phases and the decisions.

## Architecture rules

- **The motion model must be swappable.** Kimodo is only the first backend. No Kimodo name, constant or convention (Y-up, axis-angle, SOMA joint names, 30 fps) outside `backends/kimodo/`.
- **Blender never imports the model or torch.** Each backend runs as a worker process with its own Python, and talks to Blender over JSON.
- **Blender-side data uses Blender conventions**: Z-up, meters, quaternions, Blender frame numbers and scene fps. The backend adapter converts.
- **Pure logic stays free of `bpy`** when it can (conversions, neutral types), so it can be tested with plain Python and numpy.

## Current layout

| File | Role |
|---|---|
| `__init__.py` | Entry point, scene properties, bone selection handler |
| `setup_operators.py` | Bone list setup, offsets, translation scale, JSON import/export, corrections |
| `retarget_operators.py` | Snapping and baking |
| `ui.py` | Sidebar panel and bone list |
| `utils.py` | Old code, not imported, does not run as is (to remove or isolate in Phase 2) |

The retargeting functions currently read their inputs from `scene.retarget_*`. Phase 2 makes them take the source, target and mapping as arguments.

## Conventions

- Operators: `bl_idname = "retargetor.<name>"`, classes prefixed `RTGTR_`.
- Helpers raise `KeyError` / `ValueError` with an explicit message; operators catch them and `self.report()` them.
- All UI text and messages in English.
- Target bones use quaternion rotation; keep quaternion signs continuous between keyframes.
- Keep the README up to date when a user-facing feature changes.

## Testing

- Headless: `"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" -b <file.blend> --python <script.py>`. The `blender` on PATH is 5.0, which is too old for this extension.
- Live inspection goes through the Blender MCP connector; it needs Blender running with the MCP add-on server started.
- Machine-specific paths (Kimodo venv, test files) are in `CLAUDE.local.md`, which is not committed.

## Git

- `main` always stays a working add-on.
- One short-lived branch per milestone (for example `refactor/retarget-core`, `backends/kimodo`), merged through a PR on `Maxiriton/retargetor`.
