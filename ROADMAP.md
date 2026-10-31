# Roadmap

## Goal

A Blender extension to animate a character rig with an AI motion model:

1. The user poses **their own rig with its own controllers** at a few key frames.
2. The extension snaps the model's skeleton to those key poses.
3. The model generates the movement between them.
4. The generated motion is retargeted back onto the user's rig.

The current Retargetor (bone mapping, rest pose offsets, corrections, root motion scale) is the retargeting piece of this pipeline. It will be used in both directions: user rig → model skeleton, and model skeleton → user rig.

**Kimodo** (NVIDIA) is the first model, but it is **not a hard constraint**: the extension must be able to switch to another model when a better one arrives. See [Architecture](#architecture).

Features and data model (keyframe types, where results and settings are stored) are in [DESIGN.md](DESIGN.md).

## Architecture

### Principles

- **Kimodo is one backend among others.** No Kimodo name or constant outside `backends/kimodo/`.
- **The model runs in its own process**, with its own Python environment. Blender never imports torch or the model; it talks to a worker script over a JSON protocol.
- **Blender-side data uses Blender conventions**: Z-up, meters, quaternions, Blender frame numbers and scene fps. The backend adapter converts to and from the model's conventions (up axis, rotation format, canonical origin and heading, fps).
- **The user maps their rig once, whatever the model.** Rig bones are mapped to **humanoid roles** (hips, spine, chest, neck, head, upper arm, forearm, hand, thigh, shin, foot…). Each backend maps the roles to its own joints. Composing both gives direct bone pairs, so there is still a single retargeting step.
- **A second backend from the start**: a pure Python interpolation backend (slerp between key poses, no GPU). It keeps the interface honest and makes fast tests possible.
- **Don't over-design**: the interface starts minimal and grows when a real new model needs it.

### Backend interface (draft)

- `skeleton()`: joint names, parents, rest pose, and an asset (BVH or .blend) to build its armature in Blender.
- `capabilities()`: text prompt, full-body keyframes, end-effectors, root path, max length, native fps.
- `generate(request) -> Motion`, plus `start()`, `stop()`, `status()`, `cancel()`.

The UI only shows what the active backend supports.

### Target layout

```
core/retarget/       retargeting, independent of the scene properties
core/roles.py        humanoid roles
core/motion.py       neutral Pose / Motion / GenerationRequest types (no bpy)
backends/base.py     backend interface and capabilities
backends/process.py  worker lifecycle and JSON protocol
backends/interpolate/
backends/kimodo/     skeleton, role mapping, worker.py (runs in the Kimodo venv)
ui/
```

## Working method

- **Risks first, then a rough end-to-end version, then polish.**
- **Each milestone has a "done" test** and lands on `main` through a short-lived branch and a PR. `main` always stays a working add-on.
- **One session per milestone**, in its own worktree. Shared context lives in `CLAUDE.md` and in this file, not in conversations.
- **Parallel work only on separate files.**
- **A test scene per phase**, with scripts runnable headless (`blender -b --python`).

## Phases

### Phase 0: check the model works

- [x] Generate a motion with a full-body keyframe constraint from the Kimodo venv (`kimodo_gen`), get the NPZ and the BVH.
- [x] Import the SOMA skeleton in Blender (BVH, standard T-pose) and save it as the reference armature.
- [x] Round-trip test: Kimodo motion → constraints built from the Blender armature → compare with the NPZ rotations.

**Done when** a pose made on the SOMA armature in Blender comes out unchanged in the generated motion.

**Done (2026-10-31).** Every conversion matches exactly; generation takes about 23 s and 6.8 GB of video memory. Results, confirmed conventions and one trap (hand end joints) are in [spikes/phase0/README.md](spikes/phase0/README.md). Generating from a pose made by hand in Blender is left to Phase 1.

### Phase 1: rough end-to-end prototype

- [ ] Pose the user rig at 2–3 key frames.
- [ ] Retarget those poses onto the SOMA armature with the current Retargetor.
- [ ] Export the constraints, generate by hand, import the result.
- [ ] Retarget the result back onto the user rig.

Hard-coded values and manual steps are fine. **Done when** a short clip goes through the whole chain and we have a list of what goes wrong.

### Phase 2: retargeting core refactor

- [ ] Make the retargeting functions independent of `scene.retarget_*` (source, target and mapping passed as arguments).
- [ ] Move the rig profile to the Armature data and the per-character state to the Object, so a scene can hold several characters (see DESIGN.md).
- [ ] Migrate setups saved in `scene.retarget_*`, or document the JSON export / import route.
- [ ] Check how the rig profile behaves on a rig linked from a library, with library overrides.
- [ ] Snap and bake on a given list of frames, not only the scene range.
- [ ] Humanoid roles: rig bone → role mapping, saved and reloaded.
- [ ] Neutral types in `core/motion.py`.
- [ ] Remove or isolate the dead code in `utils.py`.

**Done when** the Phase 1 chain runs through the new API, and the existing panel still works.

### Phase 3: backends

- [ ] Backend interface and JSON worker protocol.
- [ ] Interpolation backend (pure Python).
- [ ] Kimodo backend: skeleton, role mapping, conversions, worker running in the Kimodo venv (path set in the add-on preferences).
- [ ] "Generate in-betweens" operator: reads the key poses from the user keys (any type but `GENERATED`), sends them, writes the result as `GENERATED` keys in the rig's action, without freezing Blender (timer or modal operator). One undo step.
- [ ] Frame rate handling (model fps vs scene fps).

**Done when** switching between the interpolation and Kimodo backends needs no code change outside `backends/`.

### Phase 4: controller rigs

- [ ] IK/FK limbs, Rigify.
- [ ] Never overwrite the user's key poses: only fill the frames between them.
- [ ] Partial poses: constrain only the keyed controls (end-effectors).
- [ ] Regenerate a single segment between two keys.
- [ ] Retype edited `GENERATED` keys as user keys before regenerating.
- [ ] Test the jumps around key poses; blend if needed.

### Phase 5: user experience and release

- [ ] Prompt segments, visible in the timeline.
- [ ] Root path drawing (when the backend supports it).
- [ ] Ghost preview of the model's skeleton (nice-to-have).
- [ ] Clear error messages, progress and cancel.
- [ ] Documentation and packaging; choose the final name (it should not contain "Kimodo").

## Decisions

| Date | Decision |
|---|---|
| 2026-10-31 | The motion model must be swappable; Kimodo is the first backend. |
| 2026-10-31 | First Kimodo model: SOMA (BVH export, best supported). |
| 2026-10-31 | Kimodo runs natively on Windows in its own venv; no WSL or Docker needed. |
| 2026-10-31 | The third-party "Kimodo Blender Bridge" add-on is a reference only, not a dependency. |
| 2026-10-31 | Key poses are read from keyframe types: user keys are any type but `GENERATED`; generated keys are `GENERATED`, in the rig's own action. |
| 2026-10-31 | Several characters per scene: rig profile on the Armature data, character state on the Object, backend settings in the preferences. |

## Open questions

- Which rigs to support first (Rigify, Mixamo, custom)? Do the limbs use IK?
- Kimodo's code and weights licence, and what it means for distributing the extension.
- Use GitHub issues for the tasks, or this file only?
