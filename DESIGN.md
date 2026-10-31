# Design

Features and data model of the extension. The goal, architecture and phases are in [ROADMAP.md](ROADMAP.md). This file is filled in as decisions are made; open points are listed at the end.

## Key poses and generated keys

The animation itself is the source of truth: key poses are not stored in a separate list, they are read from the rig's action through the **keyframe types**.

- **User keys**: every key whose type is **not** `GENERATED` (Keyframe, Breakdown, Extreme, Moving Hold, Jitter). Animators keep their own conventions.
- **Generated keys**: keys written by the extension, with the type **`GENERATED`** (Blender's built-in type for "a key generated automatically by a tool").

### Rules

- **A frame is a key pose** as soon as **any** mapped control has a user key on it.
- **Partial poses**: key types are per F-curve, so a frame where only some controls are keyed gives a partial constraint (for example hand only), when the backend supports it.
- **User keys are never overwritten.** Generation only writes between them.
- **Regenerating a segment** deletes the `GENERATED` keys in that segment and writes new ones.
- **Editing a generated key retypes it** as a user key, so the edit is kept and becomes a constraint for the next generation. A generated key can also be promoted by hand by changing its type.
- **Density**: for now, the backend's output is used as is (a key on every output frame). Curve simplification may come later.
- **Unmapped channels** (face, props, custom properties) are never touched.
- **Partial poses constrain only what is keyed**: if the hand is keyed but not the elbow, only the hand is constrained. To revisit after testing.

## IK and FK

- **Generated motion is always written to FK controls.** Writing to IK controls is inexact (Rigify's IK bones stretch slightly, so elbows and knees end up a few cm off; see `spikes/phase1/README.md`).
- **Limbs posed in IK**: before reading the key poses, the FK controls are snapped to the IK pose on the key frames, and the limbs are switched to FK. The user's IK keys are kept.
- The rig profile describes, per limb, which FK control follows which bone and which property switches IK/FK.
- **After generation, the limbs simply play in FK.** No switch keyed per segment, no snap back to IK for now; to revisit with usage.

## Where the result goes

- **Generated keys go into the rig's own action**, next to the user keys, told apart only by their type.
- **No separate NLA strip or action for the result**: the Dope Sheet and Timeline only show the keys of the active action, so the user would see either their keys or the generated ones, never both.
- A generation is a single undo step.
- Takes or variations (comparing several results) are not planned for now. If they come later, they must keep the single-action rule, for example by keeping alternate results aside and swapping them into a segment.

## Text prompts (later)

- The user defines **segments with a prompt**, and they must be **visible in the timeline**.
- Not designed yet. To keep in mind for the data model: a segment has a start, an end, a prompt (and probably a seed), and is stored with the character.

## Root motion

- Root motion follows the existing per-bone **Use Translation** flag: only the flagged bones (typically root and hips) carry translation.
- The root position is fixed at the key poses (taken from the user's rig); the model decides the path between them.
- Drawing a root path (when the backend supports it) may come later.

## The model's skeleton

- **A ghost preview is a nice-to-have.** The cheapest version: the model's armature is already in the scene for the retargeting, so it can be shown with the generated motion (in front, wireframe) or hidden.

### Implementation notes

- `keyframe_insert(..., keytype='GENERATED')` writes the generated keys.
- Blender has no "key edited" event. A likely approach: remember the values written at generation time; before regenerating, any `GENERATED` key whose value changed is retyped as a user key. To be checked in Phase 4.

## To test later

- Small jumps right before or after a key pose, since the model does not hit the poses exactly. Blending over a few frames around each pose is an option, to decide after testing.

## Characters

- **Several characters per scene** must be possible. Today the setup is stored on the scene (`scene.retarget_*`), which allows only one, so per-character data moves to the character (see below).

## Where data is stored

| Where | What | Why |
|---|---|---|
| **Armature data** (`bpy.types.Armature`) | The **rig profile**: per role, the bone that is read and the control that is written (they differ on controller rigs, e.g. Rigify `ORG-upper_arm.L` / `upper_arm_fk.L`), offset mode, Use Translation flags, corrections per backend | It all depends on the bones, which belong to the Armature data. Objects sharing an armature share its profile. |
| **Object** (the character in the shot) | Chosen backend, prompt segments, link to its model armature, generation state | Varies per character, so several characters can live in one scene. |
| **Add-on preferences** | Backend settings: Python path, model, device | Depends on the machine, not on the file. |
| **JSON** | Export / import of a rig profile | Reuse a mapping on another similar rig. |
| **Computed, not stored** | Translation scale | Depends on both skeletons together. |

- **Linked rigs** (checked in Phase 2, `tests/blender/test_library_override.py`): the profile comes with a rig linked from a library, so it is set up once in the rig's file.
  - Linked without override: profile and character state are read-only (Python can change them in memory, nothing is saved).
  - Library override of the character, default or fully editable: the **Object** is overridden, so the character state can be edited and is saved (bone list rows can be added). The **Armature data stays linked**, so the profile is read-only in the shot; the Rig Profile panel says so.
  - To change the profile in one shot only, override the armature data too (Outliner, or `armature.override_create()`). Edits, added roles included, are then saved; changed values win over the library, the others keep following it.
  - A JSON import needs editable armature data, so it only works on that last kind of override.
- **Existing files**: setups saved in `scene.retarget_*` are moved onto the target object when the file is loaded (`migration.py`). When that can't be done (no target, linked target, target already set up), the setup stays on the scene; the JSON export / import route is documented in the README.
- **Offsets are computed, not stored**: the rest offsets of a pair depend on both skeletons, like the translation scale.

## Open points

None for now. Later topics are marked "later" or "to test" above.
- ~~Rig profile: stored on the rig (travels with linked rigs) or as a separate preset?~~ Both: stored on the Armature data, and presets as JSON files in `presets/` (same format as the export), loaded onto a rig.
