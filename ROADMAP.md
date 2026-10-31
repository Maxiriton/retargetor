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

- [x] Pose the user rig at 2–3 key frames.
- [x] Retarget those poses onto the SOMA armature with the current Retargetor.
- [x] Export the constraints, generate by hand, import the result.
- [x] Retarget the result back onto the user rig.

Hard-coded values and manual steps are fine. **Done when** a short clip goes through the whole chain and we have a list of what goes wrong.

**Done (2026-10-31)** on a Rigify rig in FK. The rig gets its key poses back exactly and follows the generated motion in between. The list of what goes wrong is in [spikes/phase1/README.md](spikes/phase1/README.md); its consequences are in Phase 2 below.

### Phase 2: retargeting core refactor

- [x] Make the retargeting functions independent of `scene.retarget_*` (source, target and mapping passed as arguments).
- [x] Move the rig profile to the Armature data and the per-character state to the Object, so a scene can hold several characters (see DESIGN.md).
- [x] Migrate setups saved in `scene.retarget_*` (automatic on file load), and document the JSON export / import route.
- [x] Check how the rig profile behaves on a rig linked from a library, with library overrides (see DESIGN.md).
- [x] Snap and bake on a given list of frames, not only the scene range.
- [x] Humanoid roles: rig bone → role mapping, saved and reloaded. Per role: a bone to **read** (e.g. Rigify `ORG-`) and a control to **write** (e.g. Rigify FK control).
- [x] Default offset mode per role: limbs ROLL (copies the direction), spine and hips REST_OFFSET (Phase 1 finding).
- [ ] Canonicalize the heading as well as the root position. → moved to Phase 3 (it depends on the backend).
- [x] Exclude `spikes/` from the extension build.
- [x] Neutral types in `core/motion.py`.
- [x] Remove or isolate the dead code in `utils.py` (removed).

**Done when** the Phase 1 chain runs through the new API, and the existing panel still works.

**Done (2026-10-31)** on branch `refactor/retarget-core`. `tests/blender/test_chain.py` runs the Phase 1 chain through the rig profile and `Retargeter`, in FK and on the IK-posed rig snapped to FK: the SOMA key poses and the baked rig are identical to the spike's results (0.0000°, 0.0000 cm). A setup made and baked by the previous version is migrated and baked again with identical keys. `tests/blender/test_panel.py` covers the panel workflow. `python tests/run_tests.py` runs everything.

A correction to Phase 1: the spike's "FK snap vs IK pose: 0.00 cm" was measured before Rigify's IK/FK switch drivers had updated (a custom property set from Python doesn't tag the object). Measured correctly, the FK snap keeps the limb directions exact (0.00°) and puts hands and feet up to 0.5 cm from the IK pose: the IK stretch already described. The final results are unaffected.

### Phase 3: backends

- [ ] Canonicalize the heading as well as the root position (moved from Phase 2).
- [ ] Move the SOMA role → joint map from `tests/fixtures/soma_roles.json` into `backends/kimodo/`.
- [ ] Backend interface and JSON worker protocol.
- [ ] Interpolation backend (pure Python).
- [ ] Kimodo backend: skeleton, role mapping, conversions, worker running in the Kimodo venv (path set in the add-on preferences).
- [ ] "Generate in-betweens" operator: reads the key poses from the user keys (any type but `GENERATED`), sends them, writes the result as `GENERATED` keys in the rig's action, without freezing Blender (timer or modal operator). One undo step.
- [ ] Frame rate handling (model fps vs scene fps).

**Done when** switching between the interpolation and Kimodo backends needs no code change outside `backends/`.

### Phase 4: controller rigs

- [ ] IK/FK limbs, Rigify: when a limb is posed in IK, snap its FK controls to the IK pose on the key frames, then work in FK only (tested in Phase 1: exact). Describe the snap in the rig profile (FK control ↔ followed bone, IK/FK switch property). After generation the limbs play in FK; revisit with usage.
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

| 2026-10-31 | First rig to support: Rigify (FK first, IK in Phase 4). |
| 2026-10-31 | Generated motion is always written to FK controls. Limbs posed in IK get their FK controls snapped to the IK pose first; no writing to IK controls (Rigify's IK stretch makes it inexact). After generation the limbs simply play in FK, for now. |
| 2026-10-31 | Rest offsets are computed from the two rigs when snapping or baking, not stored (like the translation scale). JSON files keep their format; old offset fields are ignored. |
| 2026-10-31 | The manual bone list (any source → any target) stays next to the rig profile: both produce `BonePair`s for the same core. The scene only keeps which character the panel edits. |
| 2026-10-31 | Rig profile presets ship as JSON in `presets/` (same format as the profile export). The SOMA role map lives in the test fixtures until Phase 3. |

## Open questions
- Kimodo's code and weights licence, and what it means for distributing the extension.
- Use GitHub issues for the tasks, or this file only?
