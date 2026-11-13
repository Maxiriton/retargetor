"""Generate In-betweens with ARDY (needs ARDY installed by the add-on and a CUDA GPU with 17 GB), on the Phase 1
Rigify rig (rig_keyposes_ik.blend: every limb in IK). One Blender run, the model loaded once per checkpoint:

    blender -b --factory-startup <rig_keyposes_ik.blend> --python tests/blender/test_generate_ardy.py -- <models folder>

<models folder>: where the add-on installed ARDY (RETARGETOR_MODELS_FOLDER); "existing:<python>" for an existing
environment instead.

- base: key poses on frames 1, 61, 120 at 30 fps (SOMA checkpoint, the 8-bit text encoder, the default): loaded
  in under 45 s, streamed (several "frames" messages), key poses untouched, the rig follows the model, feet on the
  floor; then again with the model loaded: fast, same seed same motion.
- segments: three prompt segments of 5 s (15 s in all, any length for ARDY): one request, no jump where they meet.
- segment: the track's second segment regenerated alone with another prompt and seed: the rest unchanged, no jump
  where it meets its neighbours.
- core: the Core checkpoint and the 4-bit text encoder chosen in the preferences: its 27-joint armature replaces
  SOMA's, key poses untouched, the rig follows the model.
"""
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402
import test_generate_kimodo as common  # noqa: E402
from bootstrap import angle_deg, bone_direction  # noqa: E402

PROMPT = "A person walks forward and raises both arms"
SEED = 1
SOMA = "ARDY-SOMA-RP-30FPS-Horizon60"
CORE = "ARDY-Core-RP-20FPS-Horizon40"


def setup(environment, model=SOMA, text_encoder="INT8"):
    bootstrap.register_addon()
    if environment.startswith("existing:"):
        bootstrap.set_backend("ardy", python=environment[len("existing:"):], model=model, text_encoder=text_encoder)
    else:
        os.environ["RETARGETOR_MODELS_FOLDER"] = environment
        bootstrap.set_backend("ardy", python="managed", model=model, text_encoder=text_encoder)
    rig = bpy.data.objects["rig"]
    bpy.context.view_layer.objects.active = rig
    if not rig.data.retargetor_profile.roles:
        bpy.ops.retargetor.profile_load_preset(preset="rigify_human")
    bpy.context.scene.retargetor_target = rig
    rig.retargetor.prompt = PROMPT
    rig.retargetor.seed = SEED
    return rig


def switches(rig):
    return {limb.name: rig.pose.bones[limb.switch_bone] for limb in rig.data.retargetor_profile.to_core().limbs}


def in_fk(rig, function):
    """function() with every limb switched to FK (Rigify's IK chain is a little shorter than the FK one: the rig
    follows the model in FK, as test_generate_kimodo's ik mode checks it)"""
    from test_generate_ik import in_fk as switched
    return switched(rig, switches(rig), function)


def active():
    from retargetor.preferences import active_backend
    return active_backend(bpy.context)


def check_follows_model(checks, rig, frames, label):
    """The rig's limbs follow the model's joints (the active checkpoint's joint map)"""
    joint_map = active().joint_map
    model = rig.retargetor.model_armature
    profile = rig.data.retargetor_profile.to_core()
    limbs = [(b.read_bone, joint_map[b.role]) for b in profile.roles if b.offset_mode == 'ROLL' and b.role in joint_map]
    total = count = 0
    worst = 0.0
    lowest_toe = 1.0
    scene = bpy.context.scene
    for frame in frames:
        scene.frame_set(frame)
        for bone, joint in limbs:
            a = angle_deg(bone_direction(rig, bone), bone_direction(model, joint))
            total, count, worst = total + a, count + 1, max(worst, a)
        lowest_toe = min(lowest_toe, min((rig.matrix_world @ rig.pose.bones[n].tail).z
                                         for n in ("ORG-toe.L", "ORG-toe.R")))
    checks.below(total / count, 0.1, f"{label}: rig follows the model, mean limb direction (deg)")
    checks.below(worst, 2.0, f"{label}: rig follows the model, worst limb direction (deg)")
    checks.check(-0.03 < lowest_toe < 0.1, f"{label}: feet on the floor (lowest toe tip {lowest_toe * 100:.1f} cm)")


def run_base(checks, rig):
    keys = [1, 61, 120]
    before = common.motion_snapshot(rig, keys)
    task = common.generate(checks, "base, first generation (starts ARDY, loads the model)")
    checks.below(task.timings["generation"], 45.0, "first generation, ARDY started and loaded with its 8-bit text "
                                                   "encoder (s)")
    model = rig.retargetor.model_armature
    checks.check(len(model.data.bones) == 77, f"SOMA armature built from ARDY's install ({len(model.data.bones)} bones)")
    # 120 frames at 30 fps: two windows of 60 frames, each one sent when done
    checks.check(task.frame_messages >= 2, f"the motion streamed window by window ({task.frame_messages} messages)")
    common.key_poses_kept(checks, rig, before, "base")
    in_fk(rig, lambda: check_follows_model(checks, rig, range(1, 121), "base, in FK"))
    first = common.motion_snapshot(rig, range(1, 121))

    task = common.generate(checks, "base, second generation (model loaded)")
    checks.below(task.timings["generation"], 4.0, "second generation, model already loaded (s)")
    again = common.motion_snapshot(rig, range(1, 121))
    _ma, _wa, _md, worst_d = common.compare(first, again, [(f, f) for f in range(1, 121)])
    print(f"FINDING same seed twice: worst head {worst_d:.3f} cm")
    checks.below(worst_d, 1.0, "same seed twice, worst head (cm)")


def write_track(rig):
    from retargetor import segment_track
    from retargetor.core.segments import PromptSegment
    segment_track.write_track(rig.retargetor, [PromptSegment(*segment) for segment in common.SEGMENTS])


def run_segments(checks, rig):
    from retargetor import segment_track
    write_track(rig)
    key_frames = [1, 61, 120]
    before = common.motion_snapshot(rig, key_frames)
    task = common.generate(checks, "three prompt segments, 15 s")
    checks.check(len(task.chunks) == 1 and len(task.request.segments) == 3 and (task.start_frame, task.end_frame)
                 == (1, 450), "one request for the three segments, frames 1-450")
    checks.check(task.frame_messages >= 7, f"15 s streamed window by window ({task.frame_messages} messages)")
    common.key_poses_kept(checks, rig, before, "segments")
    checks.check(common.generated_frames(rig) >= set(range(1, 451)) - set(key_frames),
                 "GENERATED keys on the whole track")
    checks.check(all(segment_track.segment_state(item) == 'GENERATED' for item in rig.retargetor.segments),
                 "the segments are marked generated")
    common.boundary_jumps(checks, rig, [151, 301], "segments")


def run_segment(checks, rig):
    from retargetor import segment_track
    state = rig.retargetor
    outside = [f for f in range(1, 451) if not 151 <= f <= 300]
    motion_before = common.motion_snapshot(rig, range(1, 451))
    fk_before = in_fk(rig, lambda: common.motion_snapshot(rig, outside))
    keys_before = common.all_keys(rig)
    state.segments[1].prompt = "A person turns right and crouches"
    state.segments[1].seed = 7
    task = common.generate(checks, "segment 2 regenerated alone", segment=1)
    request = task.request
    checks.check((request.start_frame, request.end_frame, request.seed) == (151, 300, 7),
                 "the request: segment 2 and its seed")
    count = active().context_frame_count(30.0)
    checks.check((request.context_before.start_frame, request.context_after.end_frame) == (151 - count, 300 + count),
                 f"the motion around it: {count} frames on each side")
    states = [segment_track.segment_state(item) for item in state.segments]
    checks.check(states == ['GENERATED', 'GENERATED', 'GENERATED'], f"the segments are generated ({states})")
    keys_after = common.all_keys(rig)
    changed = [(c, f) for c in set(keys_before) | set(keys_after)
               for f in set(keys_before.get(c, {})) | set(keys_after.get(c, {}))
               if not 151 <= f <= 300 and keys_before.get(c, {}).get(f) != keys_after.get(c, {}).get(f)]
    checks.check(not changed, f"the keys outside segment 2 are unchanged ({len(changed)}: {changed[:3]})")
    motion_after = common.motion_snapshot(rig, range(1, 451))
    fk_after = in_fk(rig, lambda: common.motion_snapshot(rig, outside))
    _ma, worst_angle, _md, worst_dist = common.compare(fk_before, fk_after, [(f, f) for f in outside])
    checks.below(worst_dist, 1e-3, "the motion outside segment 2 is unchanged in FK, worst head (cm)")
    _ma, worst_angle, _md, worst_dist = common.compare(motion_before, motion_after, [(f, f) for f in outside])
    print(f"FINDING outside segment 2, played in IK: worst head {worst_dist * 10:.4f} mm from before")
    checks.below(worst_dist, 0.01, "the motion outside segment 2 is unchanged in IK, worst head (cm, Rigify's IK "
                                   "solver starts from the frame evaluated before)")
    mean_angle, _wa, mean_dist, _wd = common.compare(motion_before, motion_after, [(f, f) for f in range(151, 301)])
    print(f"FINDING segment 2 regenerated: {mean_dist:.1f} cm, {mean_angle:.1f} deg from the previous motion on average")
    checks.check(mean_dist > 5.0, f"segment 2 is a new motion ({mean_dist:.1f} cm from the previous one)")
    common.boundary_jumps(checks, rig, [151, 301], "segment 2 regenerated")
    for boundary in (151, 301):
        steps = common.frame_steps(rig, list(range(boundary - 4, boundary + 5)))
        print(f"FINDING segment 2 regenerated, steps around frame {boundary} (cm, deg): " +
              ", ".join(f"{f}: {h:.2f} {t:.1f}" for f, (h, t) in steps.items()))
        around = [steps[f] for f in steps if f != boundary]
        checks.below(steps[boundary][0], 2.0 * max(h for h, _t in around) + 0.1,
                     f"segment 2 regenerated: hips step onto frame {boundary} like the frames around it (cm)")


def run_core(checks, rig, environment):
    # Back to one prompt, then the Core checkpoint: the worker restarts with it, the armature is rebuilt
    rig.retargetor.segments.clear()
    setup(environment, CORE, "NF4")
    backend = active()
    checks.check(backend.capabilities.native_fps == 20.0 and backend.joint_map["thigh.L"] == "LeftUpLeg",
                 "the Core checkpoint's capabilities and joint map")
    keys = [1, 61, 120]
    before = common.motion_snapshot(rig, keys)
    start = time.perf_counter()
    common.generate(checks, "Core checkpoint, 4-bit text encoder (restarts ARDY with them)")
    print(f"FINDING Core: {time.perf_counter() - start:.1f} s with the model's load")
    model = rig.retargetor.model_armature
    checks.check(len(model.data.bones) == 27, f"Core armature replaces SOMA's ({len(model.data.bones)} bones)")
    common.key_poses_kept(checks, rig, before, "Core")
    in_fk(rig, lambda: check_follows_model(checks, rig, range(1, 121), "Core, in FK"))


def main():
    args = bootstrap.script_args()
    environment = args[0]
    checks = bootstrap.Checks("test_generate_ardy")
    try:
        rig = setup(environment)
        run_base(checks, rig)
        run_segments(checks, rig)
        run_segment(checks, rig)
        run_core(checks, rig, environment)
    finally:
        from retargetor.backends import registry
        registry.stop_all()
    checks.finish()


if __name__ == "__main__":
    main()
