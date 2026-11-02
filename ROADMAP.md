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

### Backend interface

- A backend declares (`backends/base.py`): its capabilities (text prompt, seed, max duration, native fps, streaming), its role → joint map, its settings (shown in the add-on preferences) and the command starting its worker.
- Its worker answers over JSON lines (`backends/protocol.py`): `skeleton` (joint names, parents, rest heads and tails in Blender conventions; the add-on builds the armature), `load`, `generate` (a `GenerationRequest`), `cancel`, `shutdown`. It sends `progress`, `frames` (the motion, possibly in several chunks, as base64 float32 arrays in the skeleton's joint order), `done` or `error`.
- The UI only shows what the active backend supports.

### Target layout

```
core/retarget/       retargeting, independent of the scene properties
core/roles.py        humanoid roles
core/motion.py       neutral Pose / Motion / GenerationRequest types (no bpy)
backends/base.py     backend interface and capabilities
backends/process.py  worker lifecycle and JSON protocol
backends/registry.py the backends, their running workers
backends/interpolate/
backends/kimodo/     role mapping, conversions, worker.py (runs in the Kimodo venv)
generation.py        Generate In-betweens, step by step
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

- [x] Canonicalize the heading as well as the root position (moved from Phase 2).
- [x] Move the SOMA role → joint map from `tests/fixtures/soma_roles.json` into `backends/kimodo/`.
- [x] Backend interface and JSON worker protocol.
- [x] Interpolation backend (pure Python).
- [x] Kimodo backend: skeleton, role mapping, conversions, worker running in the Kimodo venv (path set in the add-on preferences).
- [x] "Generate in-betweens" operator: reads the key poses from the user keys (any type but `GENERATED`), sends them, writes the result as `GENERATED` keys in the rig's action, without freezing Blender (timer or modal operator). One undo step.
- [x] Frame rate handling (model fps vs scene fps).
- [x] Never overwrite the user's key poses (moved from Phase 4).

**Done when** switching between the interpolation and Kimodo backends needs no code change outside `backends/`.

**Done (2026-11-02)** on branch `claude/backends-core-a49724`. The backend is a preference; nothing outside `backends/` names one. Results on the Phase 1 Rigify rig (key poses 1, 61, 120, same prompt and seed as the spike), `tests/blender/test_generate_kimodo.py`:

| Check | Result |
|---|---|
| Key poses and user keys | Untouched (0.0000°, 0.0000 cm); `GENERATED` keys on every other frame |
| Rig vs the generated motion | 0.0000° on every limb, hips 0.000 cm |
| Same as the spike's result | 0.04° mean (the spike's hands were 1.9° off, see below) |
| First generation (starts the worker, loads the model) | about 17 s: 10.5 s generation, 2.6 s writing the keys |
| Next generations (model kept loaded) | about 5.7 s: 3.0 s generation, 2.6 s writing |
| Same seed twice | Identical (0.002 cm) |
| Character turned 90° (Rigify root) | The base motion turned, 0.00° / 0.00 cm |
| 24 fps scene, key poses at the same times | The 30 fps motion at the same times, 0.00 cm |
| Interpolation backend, whole operator | 3 s for 120 frames, no GPU (`tests/blender/test_generate.py`) |

Findings:
- **Snapping order.** A bone reads its parents' evaluated matrices, which only a scene update refreshes. The five fixed passes of Phase 2 weren't enough: Rigify's hands are 6 levels deep through ORG and MCH constraints (the Phase 1 result was up to 1.9° off on the hands: its "max 1.8° on a hand"), and SOMA's head and arms 7 (a turned character came out wrong). The `Retargeter` now measures the dependencies once (turning each target bone in turn) and snaps level by level: exact in one sweep.
- **Translation pivot.** The model's hips match the rig's read bone (ORG-spine), not the written control (torso): the 1.9 cm between them must turn with the hips. Fixed with a pivot on the bone pairs.
- **Euler controls.** Rigify's shoulders are Euler: the retargeter used to switch every target to quaternions, so the user's Euler keys stopped driving them. Bones now keep their rotation mode.
- **Keying over a `GENERATED` key keeps it `GENERATED`** (Blender keeps the type when a key is replaced, even with `keytype='KEYFRAME'`): an animator's edit is lost at the next generation unless retyped by hand. Phase 4 item below.
- **Writing the keys is the bottleneck of a fast model**: about 22 ms per frame on Rigify, all of it in the rig's evaluation (5 scene updates per frame, one per dependency level); keying itself costs nothing. Writing a motion on the model's own armature takes 0.2 ms per frame (F-curves written in bulk). The protocol costs 1 ms per round trip and 0.5 MB for 10 s of SOMA motion.
- **Windows pipes.** A thread waiting on the stdin pipe blocked scipy's DLLs (imported by Kimodo) from loading; workers read from a private copy of stdin.

### Phase 4: controller rigs and workflow

Order set after the first test on the user's own Rigify character (2026-11-02): everything worked, but setting up the rig profile is intimidating, and the progress bar stops around 93% (Kimodo's post-processing and the key writing send no progress; the writing blocks Blender in one go).

- [x] Progress over the whole generation: a "Post-processing" step from the worker after denoising, and the keys written in chunks over several timer ticks with their own progress, so Blender stays responsive. Still one undo step. Esc is refused while writing (decided below).
- [ ] Generate with fewer than two key poses: an optional custom range on the character (start frame, current frame by default, and a duration) next to the default range from the key poses. 0 key poses: motion from the prompt only, starting from the character's position and heading on the start frame. 1 key pose: the motion starts from it (or ends on it). The range may also go past the last key pose to extend an animation. Key poses outside the range are ignored; user keys stay protected. Each backend declares the minimum number of key poses it needs (Kimodo 0, interpolation 2); the panel only offers what the active backend allows and warns past its maximum duration (Kimodo 10 s).
- [ ] IK/FK limbs, Rigify: when a limb is posed in IK, snap its FK controls to the IK pose on the key frames automatically, then work in FK only (tested in Phase 1: exact), instead of refusing as in Phase 3. The snap is already described in the rig profile. After generation the limbs play in FK; revisit with usage.
- [ ] Detect a Rigify rig and apply the Rigify preset automatically, so a Rigify character needs no profile setup.
- [ ] Retype edited `GENERATED` keys as user keys before regenerating (Blender keeps the `GENERATED` type when a key is replaced: see the Phase 3 findings).
- [ ] Partial poses: constrain only the keyed controls (end-effectors).

### Phase 5: user experience and release

- [ ] Prompt segments, visible in the timeline.
- [ ] Regenerate a single segment (between two key poses, or one prompt segment) without touching the rest.
- [ ] Transitions between segments (where two generations meet).
- [ ] Root path drawing (when the backend supports it).
- [ ] Ghost preview of the model's skeleton (nice-to-have).
- [ ] Clear error messages, progress and cancel (a first version is in Phase 3).
- [ ] Faster writing for fast or real-time models: compute the controls' values without scene updates (today about 22 ms per frame on Rigify), or preview on the model's armature while generating.
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
| 2026-10-31 | Minimum Blender version raised to 5.2 (LTS). Phase 0 and 1 spikes were run on 5.1. |

| 2026-10-31 | First rig to support: Rigify (FK first, IK in Phase 4). |
| 2026-10-31 | Generated motion is always written to FK controls. Limbs posed in IK get their FK controls snapped to the IK pose first; no writing to IK controls (Rigify's IK stretch makes it inexact). After generation the limbs simply play in FK, for now. |
| 2026-10-31 | Rest offsets are computed from the two rigs when snapping or baking, not stored (like the translation scale). JSON files keep their format; old offset fields are ignored. |
| 2026-10-31 | The manual bone list (any source → any target) stays next to the rig profile: both produce `BonePair`s for the same core. The scene only keeps which character the panel edits. |
| 2026-10-31 | Rig profile presets ship as JSON in `presets/` (same format as the profile export). The SOMA role map lives in the test fixtures until Phase 3. |
| 2026-11-02 | Each backend describes its skeleton as neutral JSON (joint names, parents, rest heads and tails in Blender conventions); the add-on builds the armature. No BVH import. Kimodo's 77 SOMA joints are read from the user's Kimodo install, so no SOMA data ships with the add-on. Motions come back as JSON too and are written in bulk into F-curves. |
| 2026-11-02 | User keys are never overwritten (from Phase 3): no write on a frame carrying a user key; the `GENERATED` keys of the range are replaced. |
| 2026-11-02 | Interpolation backend: slerp / lerp between key poses on its own skeleton (one joint per role), run as a worker with Blender's Python through the same protocol. Only listed with the Developer preference. |
| 2026-11-02 | One prompt and one seed per character (on the Object) for now; prompt segments are Phase 5. |
| 2026-11-02 | Phase 3 refuses to generate when a limb of the profile is in IK on the range, and points to Snap FK to IK. Automatic snap is Phase 4. |
| 2026-11-02 | numpy is used where it helps (backends, bulk writing): it ships with Blender and with the model venvs. Unit tests run with Blender's own Python. |
| 2026-11-02 | Protocol: JSON lines on the worker's stdin / stdout; bulk data as base64 float32 arrays in the skeleton's joint order; a motion may come in several chunks (streaming models such as NVIDIA ARDY). Kept small on purpose: with a fast model, the bottleneck is writing the keys, not the protocol. |
| 2026-11-02 | The model's armature follows the rig object's placement (not its scale); its poses are read and written in its own armature space, so the motion is generated in the character's space. |
| 2026-11-02 | A generation may use 0 or 1 key pose with a custom range (start, duration), when the backend allows it; without a key pose the motion starts from the character's current position and heading. The custom range prepares the prompt segments of Phase 5. |
| 2026-11-02 | Phase 4 order, after the first test on the user's own Rigify character: progress and chunked writing, fewer than two key poses, automatic IK → FK snap, automatic Rigify preset, retyping edited generated keys, then the rest. |
| 2026-11-02 | Progress: the backend's generation takes 80% of the bar, writing the keys the rest. The keys are written about 0.1 s of work per timer tick (the number of frames per tick adapts to the rig). Esc and the cancel button are refused while writing (a few seconds; undoing a half-written range would need the old keys saved); meanwhile only navigation events reach Blender, so nothing edits the rig or undoes. A generation cancelled after the rig was changed (automatic FK snap...) still finishes as one undo step, with a warning. |
| 2026-11-02 | The continuity of the motion around key poses is left to the backend (Kimodo's post-processing hits them exactly); it is not measured or blended. Regenerating a single segment and the transitions between segments move to Phase 5, with the prompt segments. |
| 2026-11-02 | Kimodo: key poses are moved to Kimodo's canonical frame (origin and heading of the first one, as Kimodo computes it) and the result moved back; `first_heading_angle` is not used. Key frames go to the nearest model frame, the time between key poses is stretched so each lands exactly, and the result is resampled to the scene's rate. |

## Open questions
- Kimodo's code and weights licence, and what it means for distributing the extension.
- Use GitHub issues for the tasks, or this file only?
