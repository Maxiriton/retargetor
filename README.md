# Retargetor

**Retarget an animation from one armature to another, even when their rest poses don't match, and generate the motion between your key poses with an AI motion model.**

Retargetor is a Blender add-on that copies an animation bone by bone from a *source* armature to a *target* armature. It corrects the orientation differences between the two rest poses, scales the root motion to the size of the target, and bakes the result as keyframes on the target.

It can also **generate in-betweens**: pose your own rig at a few key frames, and a motion model (NVIDIA Kimodo or ARDY for now) generates the movement between them, written back on your rig's controls.

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
- **Several characters per scene**: each target armature keeps its own setup.
- **Rig setup**: a rig is mapped once to humanoid roles (hips, upper arm, shin...), with a bone to read and a control to write for each. Rigify, Auto-Rig Pro and CloudRig rigs and skeletons (Mixamo, Unreal, SMPL...) set themselves up; others are set up by picking their bones, and **Check Rig** tests what the controls do.
- **Generate**: the motion between your key poses, from a motion model running in its own process (Blender never freezes, and never loads the model itself). Your keys are never overwritten; the result comes as **Generated** keys. See [ROADMAP.md](ROADMAP.md) for what comes next.
- **Prompt segments**: a track of prompts per character, one after the other, shown as bands in the Dope Sheet, the Timeline and the Graph Editor, and edited with the mouse like NLA strips; the whole track is generated at once, with the model's own transitions between the segments, or one segment is regenerated alone, joining the motion around it.

## Requirements

- Blender **5.2** or newer.
- To generate with Kimodo: an NVIDIA GPU (about 7 GB of video memory) and about 12 GB of disk. With ARDY: an NVIDIA GPU with 17 GB of video memory (an RTX 3090 or 4090), about 23 GB of disk (Llama 3 8B included), access to Meta's Llama 3 on Hugging Face, and Visual Studio's C++ build tools on Windows (a C++ compiler elsewhere) for its post-processing. The add-on installs both itself (see [Models](#models)); Blender's **Allow Online Access** (Preferences > System > Network) must be on for the install.

## Installation

1. Zip the add-on folder (the folder containing `__init__.py` and `blender_manifest.toml`).
2. In Blender, open **Edit > Preferences > Get Extensions**, then use **Install from Disk** (the dropdown arrow in the top right) and choose the zip.
3. Enable **Retargetor**.

The panel appears in the 3D Viewport sidebar (press `N`), in the **Retarget Tool** tab.

## Quick start

1. **Choose the armatures.** Set **Target** (the armature that should receive the animation), then **Source** (the one that holds it). The setup is stored on the target object, so each character of the scene keeps its own; switching **Target** switches the setup shown in the panel.
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

Both are computed from the rest poses of the two armatures each time you snap or retarget, so they are always up to date.

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

**Export to JSON** saves the whole list: bone names, offset modes, translation flags and recorded corrections. **Import from JSON** loads it back onto the current target, and recomputes the translation scale if the source is set.

Files exported by older versions can still be imported. Missing fields fall back to safe defaults (no translation, no correction); the rest offsets they contain are ignored, since they are computed from the rigs.

## Files made with older versions

Older versions stored the setup on the scene (one per scene). When such a file is opened, the setup is moved onto its target armature object automatically, and the scene's **Target** is set to it. The setup is left on the scene, and a message is printed in the console, when it can't be moved: no target armature, a linked target, or a target that already has a bone list. In that case, open the file with the old version, **Export to JSON**, then open it with this version and **Import from JSON** on the target.

## Rig setup

The **Rig Setup** panel (same tab) describes how the **active armature** maps to humanoid roles: its rig profile. It is stored on the armature data, so every object using that armature shares it, and it travels with a rig linked from a library. Most rigs set themselves up: choosing the character as the **Target** is enough.

- **Rigs recognized**: **Rigify**, **Auto-Rig Pro** and **CloudRig** rigs get their preset (with their FK controls, IK/FK switches and IK snap). A **skeleton** animated directly, without controls (Mixamo, Unreal's mannequin, SMPL, VRM, Daz, Character Creator, a mocap or BVH import...), is recognized from its bone names and hierarchy: each role's bone is read and written. Both are applied as soon as the character is chosen (or when it generates), when every required role is found.
- **Detect Bones** does it on request, and keeps what it found on an incomplete skeleton. The roles are listed by body part; each one shows whether it is found (check), missing and required (error) or optional and missing. Pick a role's bone in the viewport (Pose Mode) and click the **eyedropper** of the role; the select button selects the role's bones to see them, the cross takes the role out. Required roles: hips, at least one spine bone, head, upper arms, forearms, hands, thighs, shins and feet.
- **Separate Controls**: on a controller rig, each role has a bone to **read** (on Rigify, the `ORG-` bone, the result of FK and IK) and a control to **write** (on Rigify, the FK control; empty means the role isn't written). Off, for a skeleton: one bone per role, read and written.
- **Check Rig** checks the profile: the bones of each role, then what the controls really do, from the rig's rest pose. Each control written is turned, and its read bone must turn with it; each IK/FK limb is posed in FK, its IK controls snapped and the limb switched to IK, then back: it must stay where it was. The pose is put back and nothing is keyed. The problems are listed in the panel; an error stops **Generate**, which runs the check itself the first time a profile is used. Only problems are reported: a rig whose IK chain is a little shorter than its FK one (Rigify) is fine.
- **IK/FK Limbs** (sub-panel): for each limb, the FK controls and the bone each one follows, and the IK/FK switch property. **Snap FK to IK** rotates the FK controls onto the current pose on the frames you list (for example `1, 61, 120`, or empty for the current frame), keys them, and switches the limbs to FK. IK keys are kept. **IK snap** (in order): how each IK control follows the generated motion, so the limb plays in IK after generating. **Follow** takes the transform of a bone (with the offset of their rest poses), **Pole** places a pole target in the plane of the limb, **Rest** resets the control. The presets fill it; a limb without it stays in FK after generating.
- **Advanced** (sub-panel): per role, Use Translation and the offset mode. Arms and legs default to **Roll** (the direction of the bone is copied), the spine, neck, head and feet to **Offset** (the rotation from rest: a foot bone slopes differently from rig to rig, but every rig stands with its feet flat at rest).
- The menu next to **Check Rig**: **Load Preset**, **Import Profile** / **Export Profile** (JSON, to reuse a profile on a similar rig), **Add Roles** (every role, empty).
- A rig standing with its bones Y-up (an FBX import) or facing +Y (SMPL) is fine: the model's skeleton stands like the rig.
- Not supported yet: **limbs posed in IK only**, whose bones only an IK constraint can pose, with no FK control to write and no IK/FK switch (some older hand-made rigs, such as the 2006 Proog of Elephants Dream: its legs, its feet hanging from the root). **Check Rig** says so. A chain whose IK constraints are turned off by their influence can be used in FK, but the add-on doesn't switch such constraints itself.

### Linked rigs and library overrides

Set the profile up in the rig's own file. In a shot file that links the rig, the profile is read-only. A library override of the character overrides the object (so the per-character setup in the Retarget panel can be edited and is saved) but **not the armature data**, even with a fully editable override: the profile stays the library's, and edits made there would not be saved. To change the profile in a shot only, override the armature data too (from Python: `rig.data = rig.data.override_create(remap_local_usages=True)`; the Outliner's **Library Override > Make** on the armature data should do the same). Values you change then win over the library, and the others still follow it.

## Generate in-betweens

1. **Choose the character** as **Target** in the Retarget panel. A **Rigify**, **Auto-Rig Pro** or **CloudRig** rig, or a skeleton such as a Mixamo character, needs nothing else: its rig profile is set up as soon as you choose it (the Generate panel says how). For another rig, set it up in the Rig Setup panel.
2. **Key your poses** on the controls of the profile (on Rigify, the FK or IK controls and the torso). Any keyframe type works except **Generated**: Keyframe, Breakdown, Extreme... A frame is a key pose as soon as one of those controls has a key on it.
3. **Limbs in IK** are handled for you, and stay in IK: the generated motion is written to the FK controls, so before generating, the FK controls of a limb in IK are snapped to its IK pose on each key pose (keyed as normal keys), and the limb is in FK while generating. Then its IK controls (hand, foot, pole, toe...) are snapped to the generated motion on every frame, as Generated keys, and the IK/FK switch goes back to what you left (animated or not). The limb plays the motion in IK: pose it in IK anywhere, and the edited frame is a key pose for the next generation. Your IK keys are kept, and on the key poses the IK controls are keyed as they are. On Rigify the IK arm and leg are a little shorter than the FK ones, so the elbows and knees can sit up to 1 or 2 cm from the FK motion, and an IK knee doesn't fully straighten (where the generated leg straightens, it stays bent a few cm and can pop forward); hands and feet follow the motion. A limb whose rig profile has no IK snap stays in FK after generating; for such a limb, a switch key in IK between two key poses stops the generation (key the switch in FK there, or key a pose on that frame).
4. In the **Generate** panel, write a **prompt** (what the character does) and choose a **seed**, then click **Generate** (it becomes prompt segment 1, shown in the timeline; from then on the segment's **Regenerate Segment** button, or **Generate** in the timeline's header for the whole track). The panel and the status bar show the progress: the model's own steps, then the keys being written onto the rig. **Esc** (or the cancel button) stops the generation until the keys are being written; writing takes a few seconds and can't be stopped (Blender stays responsive meanwhile, you can look around but not edit).

The model generates the motion from your first key pose to your last one. The result is written on the rig's controls as **Generated** keys, on every frame between the key poses.

**Range**: **Key Poses** (the default) goes from the first key pose to the last one. **Custom** sets a start frame (the current frame when you switch to Custom, or the clock button) and a duration: the panel shows the frames, the seconds and the key poses inside. Key poses outside the range are ignored (and never touched). With a custom range you can:

- generate from the **prompt alone**, with no key pose: the motion starts where the character stands on the start frame, facing where it faces (on Rigify, move or turn the **root** control: it isn't a control of the profile, so it doesn't make a key pose);
- start from **one key pose**, or end on one: the motion starts where the character stands on the start frame, so to walk up to a key pose, place the root where the walk starts;
- **extend** an animation past its last key pose.

**Partial poses**: a frame where you keyed only some controls (an arm, a foot...) is a partial key pose. With Kimodo and ARDY it pins only what you keyed: a hand or a foot where your pose puts it (and the hips, which they always pin on a constrained frame); keying the spine, the neck or the head pins the whole body. The rest of that frame is generated, and your keys stay as they are. Since your keys are FK rotations, the keyed limb follows the generated body on that frame: if the body moves a lot there, the hand or foot lands away from where you posed it. Key the body as well to keep the whole pose.

Kimodo needs no key pose and generates up to 10 s (per segment with [prompt segments](#prompt-segments)); the panel says when the range is too long, or has fewer key poses than the backend needs (the interpolation test backend needs two). Frames carrying one of your keys are never written. Generating again replaces the Generated keys of the range and keeps yours. The whole generation is one undo step.

- **Clear Generated Keys** (under Generate) removes what the add-on put on the character: its Generated keys, and the keys it made on the key poses (FK controls snapped to your IK pose, IK controls, an IK/FK switch keyed in FK), even on bones hidden in protected bone collections. A key it made that you changed since is yours, and stays. Your own keys stay, and a control left without any key goes back to its rest pose. One undo step.
- The first generation starts the model and its text encoder (about 20 s with Kimodo, a minute with ARDY; the header says **Starting**, then **Loading**); the model then stays loaded, and the next ones take about 3 s with Kimodo, under a second with ARDY, plus the time to write the keys (on Rigify about 1 s for 120 frames, and as much again to snap the IK controls of limbs in IK; more on a character whose meshes are heavy to deform). **Start** / **Stop** in the panel load the model ahead of time, or free its memory.
- The model's skeleton is added to the scene as a hidden armature, in a **Retargetor Models** collection, next to your character.
- Kimodo works at 30 fps and up to 10 s per prompt; other scene rates are handled (the key poses land exactly on the model's frames, the result is resampled to the scene's rate). A character facing any direction works.
- **Editing a Generated key makes it yours**: as soon as you change a generated key (move it in the Graph Editor or the Dope Sheet, or key over it after posing the rig), it becomes a **Keyframe**, with the other channels of the same property on that frame, so the next generation keeps it and uses it as a key pose. Cancel the move (right click) and it goes back to Generated. You can also promote a generated key without changing it: **Key > Keyframe Type**.

### Prompt segments

A character can follow several prompts, one after the other: "walks forward" for 3 s, then "turns left and waves" for 2 s... Each **segment** has a start, an end, a prompt and a seed. The segments of a character follow each other with no gap, like a track: each one starts on the frame after the previous one ends, so the motion is always defined. Your key poses stay constraints inside them.

- **The first generation makes the first segment**: generated from the character's prompt, seed and range, it becomes prompt segment 1, shown in the timeline (then the segment is the range: drag its ends to change it, or remove it to use the prompt and range again). **Add Prompt Segment** (Generate panel) makes it too before generating; the next ones are added at the end of the track (2 s, no prompt yet). With segments, the panel shows the **active** segment (its prompt, seed, start and end), the arrows go to the previous or next one, and **+**, **−** and the split button add one at the end, remove the active one (the one before takes its frames) or cut the segment under the current frame in two. Without segments, the prompt, seed and range are used again.
- The segments are drawn as **bands** at the bottom of the **Dope Sheet**, the **Timeline** and the **Graph Editor**: the panel's character, then the other selected characters with segments, each with its name on the left. A band shows each prompt, its frames and seed, your key poses (small diamonds), and the transitions (a blend of colours just before each boundary). A hatched segment hasn't been generated, or was edited since the last generation. **View > Show Prompt Segments** hides them (they cover the bottom of the editor).
- With the mouse, like NLA strips: **click** a segment to make it the active one (a click on a name makes that character the panel's), **drag** a boundary to move it (the neighbour adapts, the others don't move) or drag a segment to move both its boundaries; **Esc** or a right click cancels. **Double click** opens the segment's prompt, seed and frames; **right click** (the other button, with right-click select) opens its menu: Edit, Split at Current Frame, Add, Remove, Regenerate Segment, Generate Whole Track. **+** after the track adds a segment. Each change is one undo step.
- **From the animation editors**: the headers of the Dope Sheet, the Timeline and the Graph Editor show the model's state (with a start button when it isn't loaded) and **Generate**, or the progress bar and its cancel button while generating; the eye shows or hides the bands, and the Retargetor menu next to it holds the rest: generate, regenerate the active segment, edit, add, split or remove a segment, Clear Generated Keys, start or stop the model, its errors, the preferences. The Generate panel in the 3D Viewport stays.
- **Generate** in the timeline's header (or **Generate Whole Track** in the Retargetor menu and the segment's menu) then generates the whole track; the Generate panel's button generates the active segment. Kimodo generates the segments one after the other in one pass, each one starting from the end of the previous one (its first 5 model frames, 0.17 s, follow it): the transitions are the model's. Each segment lasts 0.5 s at least and 10 s at most, but the track can be longer than 10 s. ARDY changes prompt at each boundary while it generates, continuing the motion so far, with no length limit. A model that can't chain prompts generates the segments one after the other, each one starting where the previous one ended, without transition.
- **Regenerate Segment** (the segment's menu, its popup, the Retargetor menu, the Generate panel) generates one segment again, with its own prompt and seed, and leaves the rest of the track as it is: only the segment's frames get new Generated keys, your keys stay, one undo step. The motion around it is the model's to join: Kimodo is given the 5 model frames (0.17 s) on each side (ARDY 8) and generates the segment from the end of the one before to the start of the one after, like its own transitions, so there is no jump at its boundaries. A neighbour that was never generated (hatched, "not generated yet") isn't joined: the segment starts where the character stands on its first frame, or ends freely; generate that neighbour afterwards, or the whole track. A model that can't continue a motion generates the segment from the last frame of the one before, without transition (the report says so).

### Models

**Edit > Preferences > Add-ons > Retargetor** lists the motion models, each with what it supports (text prompt, key poses, prompt segments, longest motion...):

- **Backend** (or **Use** on a model): the model generating the motion. One model is loaded on the GPU at a time: choosing another one stops the previous one.
- **Install** sets the model up by itself, after showing what it downloads, from where, and the licences: its own Python and environment (with [uv](https://github.com/astral-sh/uv), downloaded once), its packages (the right PyTorch build for your GPU) and its weights. It runs in the background with its progress; **Cancel** stops it, and **Resume Install** goes on where it stopped (a failure too). **Repair** makes the environment again and completes the weights. The folder and log buttons open the model's folder and its install log; the bin removes the model (its environment and the weights installed with it; its weights in the Hugging Face cache too if you tick it, unless another model needs them).
- **Models Folder**: where the environments go. Empty: `%LOCALAPPDATA%\Retargetor` on Windows, `~/.local/share/retargetor` on Linux, `~/Library/Application Support/Retargetor` on macOS. Weights from Hugging Face go to its usual cache (`~/.cache/huggingface`), shared with your other tools: weights already there aren't downloaded again.
- **Existing Environment**: use a Python environment where the model is installed already (its Python executable, for example `kimodo-venv\Scripts\python.exe`), instead of installing it.
- **Check Setup** says what is ready and what isn't, each problem with its fix: the environment, the packages, the GPU (PyTorch can use it, enough video memory), the weights. Loading the model itself is the **Start** / **Load** button. The animation editors' headers and the Generate panel say when the active model isn't set up.
- **Gated weights**: some models need weights you must ask access to on Hugging Face (Meta's Llama 3, for example). The check says which, **Request Access** opens its page, and **Sign In** opens a terminal running Hugging Face's own sign-in (from the browser, or with a token you paste there). The add-on never asks for, reads, stores or sends your token: Hugging Face's library uses your sign-in by itself. Kimodo needs none.
- **ARDY** (NVIDIA, github.com/nv-tlabs/ardy) generates window by window (2 s at a time), each window continuing the previous ones and seeing the key poses ahead: any length, the motion sent to Blender as it comes, about a second for 5 s once loaded. **Model**: **SOMA, 30 fps** (the same skeleton as Kimodo) or **Core, 20 fps** (ARDY's own 27-joint skeleton). Its text encoder is LLM2Vec on Meta's Llama 3 8B Instruct, in full precision: about 16 GB of video memory, a minute to load, and Hugging Face access to Llama 3 (requested on its page; weights already in your Hugging Face cache are used as they are). Without a C++ compiler it installs without its post-processing (key poses followed less exactly); install Visual Studio's C++ build tools, then **Repair**.
- **Kimodo** is installed from Aero-Ex's fork (github.com/Aero-Ex/kimodo), which runs on Windows without a compiler and comes with a 4-bit text encoder (about 5 GB of video memory instead of about 17, no gated weights); the model's weights come from NVIDIA. **Model**: **SOMA, v1.1** (the default) or **SOMA, v1**.
- **Developer**: also lists the test backends (an interpolation without any model, for tests).

## Good to know

- Only **matched** bones receive keyframes: rotation for all of them, location only for those flagged with translation.
- Two source bones can't point to the same target bone. Retargetor stops with an explicit message if that happens.
- The target bones keep their rotation mode (quaternion, Euler or axis-angle); quaternion keys keep continuous signs.
- With **Rigify** targets, match the **FK** controls and set the limbs to FK, otherwise the snapped bones will have no visible effect.
- Retargeting scales the root motion, but it can't remove foot sliding when the legs of the two rigs have very different proportions.
- **Retarget** runs over the scene's frame range and can take a while on long animations.

## Project layout

| File | Role |
|---|---|
| `__init__.py` | Add-on entry point, selection handler |
| `properties.py` | Where the data is stored: rig profile (Armature), character setup (Object) |
| `migration.py` | Moves setups saved by older versions off the scene |
| `setup_operators.py` | Bone list setup, translation scale, JSON import/export, corrections |
| `retarget_operators.py` | Snapping and baking |
| `profile_operators.py` | Rig profile: presets, detection, roles picked in the viewport, Check Rig, JSON, Snap FK to IK |
| `rig_check.py` | The rig check: profile problems, then what the controls do |
| `ui.py` | Sidebar panels and lists |
| `preferences.py` | Add-on preferences: backend, models' folder, each model's environment and settings, developer option |
| `model_setup.py` | The models' setup: install, check, remove, sign in, the Models section of the preferences |
| `generation.py`, `generate_operators.py` | Generate In-betweens: key poses, request, result as Generated keys; operators |
| `segment_track.py`, `segment_operators.py` | Prompt segments on the character, kept contiguous; add, remove, split, select |
| `segment_draw.py`, `segment_mouse.py` | Prompt segments drawn in the animation editors, and handled with the mouse |
| `core/` | Retargeting core, humanoid roles, role detection on a skeleton, neutral motion and skeleton types (see below) |
| `backends/` | Motion model backends, each in its own folder (`kimodo/`, `ardy/`, `interpolate/`), what several share (`shared/`), the protocol with their worker processes, and `setup/`: installing and checking a model's environment |
| `presets/` | Rig profile presets (Rigify, Auto-Rig Pro, CloudRig) |
| `tests/` | Unit tests, headless Blender tests, Kimodo and ARDY tests, real rigs (`python tests/run_tests.py`, see the file) |
| `blender_manifest.toml` | Extension manifest |

The core can be used from scripts, without the scene properties: `core.retarget.snap.Retargeter(source, target, pairs, translation_scale)` snaps (`snap_pose`) or bakes (`bake(scene, view_layer, frames)`) a list of `BonePair`s, and `core.profile.compose(profile, joint_map, direction)` builds those pairs from a rig profile and a skeleton's role → joint map.

## License

GPL-3.0-or-later, as declared in the manifest.

## Author

Henri Hebeisen
