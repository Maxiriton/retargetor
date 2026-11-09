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
- **The range** of a generation goes from the first key pose to the last one, or is set on the character (start frame and duration). Key poses outside the range are ignored. Without a key pose on the start frame, the motion starts where the character stands, facing its way; with no key pose at all, the prompt alone drives it.
- **Regenerating a segment** deletes the `GENERATED` keys in that segment and writes new ones (see "Prompt segments": one prompt segment regenerated alone).
- **Editing a generated key retypes it** as a user key, so the edit is kept and becomes a constraint for the next generation. A generated key can also be promoted by hand by changing its type.
- **Density**: for now, the backend's output is used as is (a key on every output frame). Curve simplification may come later.
- **Unmapped channels** (face, props, custom properties) are never touched.
- **Partial poses constrain only what is keyed**: the request lists the joints of the roles keyed on the frame (a role is keyed when its write control, or an IK control of its limb, has a user key there); the backend declares whether it honours them. Kimodo turns them into its end-effector constraints: a keyed arm pins the hand, a keyed leg the foot, the hips alone the hips; the spine, neck or head keyed pin the whole body. Kimodo always pins the hips on a constrained frame.
- **Writing is per control**: on a key frame, the controls the user keyed keep their keys and are not snapped; the other controls of that frame are generated.
- **The keyed limb keeps its FK keys** (local rotations) on a body that is generated there, so the hand or foot lands where those rotations put it on the new body, not where the model put it (20 cm away in the Kimodo test, the torso turned 18°; Kimodo itself hits the end-effector exactly). Decided: the keys are the animator's; to keep the whole pose, key the body too.

## IK and FK

- **Generated motion is always written to FK controls.** Writing to IK controls is inexact (Rigify's IK bones stretch slightly, so elbows and knees end up a few cm off; see `spikes/phase1/README.md`).
- **Limbs posed in IK**: before reading the key poses, the FK controls are snapped to the IK pose on the key frames, and the limbs are switched to FK. The user's IK keys are kept. The snapped FK keys are user keys (type Keyframe): they are key poses from then on.
- The rig profile describes, per limb, which FK control follows which bone, which property switches IK/FK, and the limb's IK controls: a key on an IK control makes a key pose, like a key on a write control.
- An animated switch is keyed in FK on the key poses and the ends of the range. A switch key in IK between two key poses can't be covered that way: the generation stops and says so.
- **After generation, a limb posed in IK plays in IK again**, so the animator keeps working in IK. It is in FK only while generating (its switch set to FK, the switch's animation muted); then its IK controls are snapped to the generated FK pose on every frame of the range (`Generated` keys), and the switch is put back exactly as the user left it (value, keys). A generation cancelled or failed puts the switches back too.
- **The rig profile says how each IK control is snapped** (`ik_snap`, per limb, in order): **Follow** takes the followed bone's transform with the offset their rest poses have (Rigify: `hand_ik` follows `ORG-hand`, `foot_ik` `ORG-foot`, `toe_ik` `ORG-toe`, `upper_arm_ik` / `thigh_ik` their `ORG-` bone, which gives the twist when the pole is off); **Pole** places a pole target in the plane of the followed bone and its parent, on the side the joint bends, at its rest distance from the joint (only its position is keyed: Rigify's `upper_arm_ik_target` follows `ORG-forearm`). On a nearly straight limb (the joint less than 5% of the limb's length off its line) the bend side isn't reliable: the pole goes back to its rest side, carried by the parent, gradually if the joint bends that way and at once if it bends the other way (a knee a little overextended would flip the pole, and the IK knee with it); **Rest** resets the control (Rigify's `foot_heel_ik`, `foot_spin_ik`, reset before the foot is placed). Locked channels are kept. A limb without `ik_snap` (a custom rig) stays in FK after generating, as before, and the report says so.
- **On the key poses, the IK controls are keyed as they are** (type Keyframe, where they have no user key) next to the snapped FK keys: the IK pose there stays the user's, and repeated generations don't drift. The IK controls of a limb are not written on a frame where one of them has a user key.
- **Rigify's IK chain is shorter than the FK one**: its IK bones have `ik_stretch` 0.1, and Blender's IK solver shrinks them by 1 to 4% even when the target is within reach (the bend plane is exact). With the hand or foot placed exactly, the elbows and knees come in by up to 1 or 2 cm, and on a key pose the user's IK hand is a few mm from the snapped FK hand. To avoid a jump there, the offset of each Follow control on the key poses (its pose relative to its target) is blended from one key pose to the next: the hands and feet follow the FK motion up to that gap, fading out between key poses. Near full extension the IK knee doesn't straighten (the solver, with `ik_stretch`, stays bent by a few cm): where a generated leg straightens, the IK knee pops forward by up to 3 cm. Not compensated for now.
- **A switch keyed in IK between key poses is only refused for a limb without IK snap**: with an IK snap the limb plays the generated motion in IK and FK alike.
- **Editing in IK after a generation**: an edited `Generated` IK key becomes a Keyframe (the live retype), so its frame is a key pose; the next generation snaps the FK controls to it, and writes the IK controls again around it.

## Where the result goes

- **Generated keys go into the rig's own action**, next to the user keys, told apart only by their type.
- **No separate NLA strip or action for the result**: the Dope Sheet and Timeline only show the keys of the active action, so the user would see either their keys or the generated ones, never both.
- A generation is a single undo step.
- **Clearing**: one operator removes everything the add-on put on a character: the `Generated` keys, and the user keys it made itself on the key poses (snapped FK keys, IK controls keyed as they are, switch keys). Those are recorded on the character when they are made (frames and values), and removed only while they still have the recorded value: one the animator changed is theirs. A key the add-on changes again later (a new snap, a quaternion sign flipped) follows in the record, unless the animator changed it first. F-curves left empty are removed and their channels put back to rest. Needed because the controls the add-on keys are often on hidden, protected bone collections (Rigify's FK controls when the animator works in IK).
- Takes or variations (comparing several results) are not planned for now. If they come later, they must keep the single-action rule, for example by keeping alternate results aside and swapping them into a segment.

## Prompt segments

- A character has a **track of prompt segments**: each segment has a start, an end, a prompt and a seed, stored on the character (`object.retargetor.segments`). The segments are **contiguous**, like Kimodo's prompt timeline: each one starts on the frame after the previous one ends, so the motion is never undefined. The user's key poses stay constraints inside them.
- **No segment: one prompt**, as before (the character's prompt, seed and range, Key Poses or Custom). The first segment is made from them; with segments, the track is the generation's range.
- **Editing keeps the track contiguous** (`core/segments.py`, no `bpy`): moving a boundary changes the two segments around it only (the key poses stay where they are in time); moving a segment moves both its boundaries; removing one gives its frames to the one before (the one after, for the first); splitting keeps the prompt and seed on both parts. A segment lasts 0.5 s at least (room for a backend's transition) and the backend's longest motion at most (Kimodo 10 s): the track itself has no limit. A move is clamped to these limits; a segment already outside them may stay as it is, not get further out.
- **Shown in the animation editors**, not as scene markers: a band per character at the bottom of the Dope Sheet (Timeline included) and Graph Editor main regions, drawn by the add-on (`segment_draw.py`): the panel's character, then the other selected characters with segments. Each segment shows its prompt, frames and seed; the key poses are small diamonds; a gradient before each boundary shows the backend's transition; a hatched segment was never generated or was edited since (frames, prompt or seed compared with what the last generation recorded). The look was chosen on mockups drawn in the user's Blender (variant D). **View > Show Prompt Segments** hides them (`scene.retargetor_show_segments`): a band always covers the bottom channels.
- **The bands are the UI's entry point, handled like NLA strips** (`segment_mouse.py`): add-on keymap items in the Dope Sheet and Graph Editor keymaps run an operator on every click and mouse move of the main region, which hit-tests the bands (the same layout function as the drawing) and lets the event through off them. Click selects (on a name: that character becomes the panel's), drag moves a boundary or a whole segment (Esc cancels), double click opens a popup (prompt, seed, frames; no text editing in the band itself), the other mouse button opens the segment's menu, "+" after the track adds one. One selected segment at a time. The Generate panel shows the active segment, with previous / next arrows.
- **Everything is reachable from the animation editors** (the user's request after the first test): their headers show the model's state and Generate, or the progress bar while generating, an eye toggling the bands (they were hidden once without the user noticing why) and a Retargetor menu (generate, segments, Clear Generated Keys, the model's start / stop and errors). The Generate panel stays.
- **Regenerating one segment alone** (Regenerate Segment: the segment's menu and popup, the Retargetor menu, the Generate panel): its prompt and seed, its key poses, and the motion around it as the model's constraint (see "Continuity around key poses"). Only its frames are written (`GENERATED` keys replaced, user keys kept), only it is marked generated: a neighbour edited since its own generation stays hatched. One undo step.
- **Colours** follow the position in the track (blue, orange, green, purple). A colour per segment may come later.

## Root motion

- Root motion follows the existing per-bone **Use Translation** flag: only the flagged bones (typically root and hips) carry translation.
- The root position is fixed at the key poses (taken from the user's rig); the model decides the path between them.
- Drawing a root path (when the backend supports it) may come later.

## The model's skeleton

- **A ghost preview is a nice-to-have.** The cheapest version: the model's armature is already in the scene for the retargeting, so it can be shown with the generated motion (in front, wireframe) or hidden.

### Implementation notes

- `keyframe_insert(..., keytype='GENERATED')` writes the generated keys.
- Keying over an existing `GENERATED` key keeps it `GENERATED` (Blender keeps the type of a replaced key, even with `keytype='KEYFRAME'`): checked in Phase 3, so the add-on retypes edited keys itself.
- Blender has no "key edited" event. The add-on remembers the `GENERATED` keys it wrote (frames and values, on the character) and a depsgraph handler compares them whenever a character's action changes (`generated_keys.py`): an edited or moved `GENERATED` key becomes a Keyframe at once, with the other channels of the same property on that frame. Keys retyped that way go back to `GENERATED` when their values come back (a cancelled transform). The same check runs before each generation, for what the handler couldn't see. Checked with Blender's interface: the Graph Editor's translate retypes the key before its undo step is pushed, so undo and redo bring the type back with the value.

## Continuity around key poses

- Left to the backend: Kimodo's post-processing hits the key poses exactly (checked in Phase 3). The add-on does not measure or blend the motion around them.
- **Transitions between prompt segments are the model's, never the add-on's** (the user's decision: blending motions is not the add-on's job). A backend declaring `Capabilities.prompt_segments` gets the whole track in one request (`GenerationRequest.segments`) and makes its own transitions; Kimodo uses its multi-prompt generation: the segments one after the other, each one's first 5 model frames constrained by the end of the previous one, the key poses cropped to each segment, post-processed per segment. `Capabilities.transition_duration` only tells the timeline where to draw them. A backend without it gets one request per segment, each starting on the previous segment's last frame (its origin: where and which way the character stands there), with no transition: the pose may jump at the boundary.
- **A single segment regenerated joins the motion around it, and the backend does it** (the user's decision, 2026-11-06): the request carries the motion just before and after the range (`GenerationRequest.context_before` / `context_after`, read from the rig as it plays, in the model's skeleton), never written back. A backend declares `Capabilities.motion_context` and how much it needs (`context_duration`; the add-on sends one frame more). Kimodo generates the context with the segment and constrains its model frames (whole body, and the hands and feet by name) like the start of a segment in its multi-prompt generation: 5 model frames on each side; its post-processing hits them, so the segment starts and ends in the motion around it, speed included. The interpolation backend interpolates from the frames next to the segment.
- **A neighbour never generated is not joined**: its frames hold nothing the model made (at most the user's keys, interpolated); the segment starts where the character stands on its first frame, or ends freely. A neighbour edited since its generation still has its motion: it is joined.
- **A backend without `motion_context`** regenerates the segment from the previous segment's last frame (its origin), as a track generated one segment at a time, without transition at either end; the report says so.
- **IK limbs**: the motion around the segment is read with the limbs in FK (they are while generating), so on IK limbs the segment joins the generated FK motion; played in IK, the IK snap blends the key poses' offsets over the whole track as the whole generation did, so the IK controls don't jump either. Measured with Kimodo on the Phase 1 rig in IK: the step onto the segment's first frame is 0.20 cm and 1.9° (0.21 cm and 1.8° the frame before), onto the next segment 0.10 cm and 2.8°.

## Characters

- **Several characters per scene** must be possible. Today the setup is stored on the scene (`scene.retarget_*`), which allows only one, so per-character data moves to the character (see below).

## Where data is stored

| Where | What | Why |
|---|---|---|
| **Armature data** (`bpy.types.Armature`) | The **rig profile**: per role, the bone that is read and the control that is written (they differ on controller rigs, e.g. Rigify `ORG-upper_arm.L` / `upper_arm_fk.L`), offset mode, Use Translation flags, corrections per backend | It all depends on the bones, which belong to the Armature data. Objects sharing an armature share its profile. |
| **Object** (the character in the shot) | Prompt, seed and range, or its prompt segments (start, end, prompt, seed, what was last generated), link to its model armature | Varies per character, so several characters can live in one scene. |
| **Add-on preferences** | Active backend and each backend's settings (Kimodo: Python path, model), developer option | Depends on the machine, not on the file. |
| **JSON** | Export / import of a rig profile | Reuse a mapping on another similar rig. |
| **Computed, not stored** | Translation scale | Depends on both skeletons together. |

- **Presets are detected**: an empty rig profile gets the first preset whose bones all exist in the armature, when the character is chosen as the panel's target, or when generating (on a linked armature, the preset is used without being saved). The profile remembers the preset it came from.
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
