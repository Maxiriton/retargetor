"""Generate In-betweens on the Phase 1 Rigify rig (key poses on frames 1, 61, 120), with the interpolation
backend: the whole chain without GPU.

    blender -b --factory-startup <rig_keyposes.blend> --python tests/blender/test_generate.py

<rig_keyposes.blend>: made by spikes/phase1/make_rig.py (tests/run_tests.py makes it in a scratch folder).
Checks: key poses and user keys untouched, GENERATED keys everywhere else, the rig follows the model,
quaternion signs continuous, regeneration replaces the GENERATED keys and respects a new user key,
IK limbs refused.
"""
import math
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402
from bootstrap import angle_deg, bone_direction  # noqa: E402

KEY_FRAMES = [1, 61, 120]
END_BONES = ["ORG-hand.L", "ORG-hand.R", "ORG-foot.L", "ORG-foot.R", "ORG-spine.006"]


def snapshot(rig, names, frames):
    scene = bpy.context.scene
    result = {}
    for frame in frames:
        scene.frame_set(frame)
        result[frame] = {n: ((rig.matrix_world @ rig.pose.bones[n].head).copy(), bone_direction(rig, n)) for n in names}
    return result


def worst_change(rig, before):
    scene = bpy.context.scene
    worst_angle = worst_dist = 0.0
    for frame, bones in before.items():
        scene.frame_set(frame)
        for n, (head, direction) in bones.items():
            worst_angle = max(worst_angle, angle_deg(direction, bone_direction(rig, n)))
            worst_dist = max(worst_dist, ((rig.matrix_world @ rig.pose.bones[n].head) - head).length * 100)
    return worst_angle, worst_dist


def keys_by_type(rig, generation):
    """{(data_path, index): {frame: (value, type)}} for every F-curve of the rig"""
    result = {}
    for fc in generation.bone_fcurves(rig):
        result[(fc.data_path, fc.array_index)] = {round(p.co.x): (p.co.y, p.type) for p in fc.keyframe_points}
    return result


def user_keys(keys):
    result = {curve: {f: v for f, v in frames.items() if v[1] != 'GENERATED'} for curve, frames in keys.items()}
    return {curve: frames for curve, frames in result.items() if frames}


def run_operator():
    """The operator's result; an error report raises in background mode, it counts as CANCELLED"""
    try:
        return bpy.ops.retargetor.generate_inbetweens('EXEC_DEFAULT')
    except RuntimeError as e:
        print(f"(operator error) {e}")
        return {'CANCELLED'}


def quaternion_flips(rig, generation, bones):
    """Number of consecutive keys whose quaternions are in opposite hemispheres"""
    bag = generation.channelbag(rig)
    flips = 0
    for bone in bones:
        curves = [bag.fcurves.find(f'pose.bones["{bone}"].rotation_quaternion', index=i) for i in range(4)]
        if any(c is None for c in curves):
            continue
        frames = sorted({round(p.co.x) for p in curves[0].keyframe_points})
        previous = None
        for frame in frames:
            q = [c.evaluate(frame) for c in curves]
            if previous is not None and sum(a * b for a, b in zip(q, previous)) < 0.0:
                flips += 1
            previous = q
    return flips


def key_at(rig, generation, path, index, frame):
    fcurve = generation.channelbag(rig).fcurves.find(path, index=index)
    return next((p for p in fcurve.keyframe_points if abs(p.co.x - frame) < 1e-3), None)


def key_type(rig, generation, path, index, frame):
    key = key_at(rig, generation, path, index, frame)
    return key.type if key is not None else None


def edit_key(rig, generation, path, index, frame, value=None, shift=0.0):
    """Change a key's value or move it in time, like the Graph Editor, and let the depsgraph see it"""
    fcurve = generation.channelbag(rig).fcurves.find(path, index=index)
    key = key_at(rig, generation, path, index, frame)
    if value is not None:
        delta = value - key.co.y
        key.co.y = value
        key.handle_left.y += delta
        key.handle_right.y += delta
    key.co.x += shift
    key.handle_left.x += shift
    key.handle_right.x += shift
    fcurve.update()
    bpy.context.view_layer.update()


def draw_generate_panel():
    """Errors found drawing the Generate panel (see test_panel.CheckingLayout)"""
    from test_panel import CheckingLayout
    from retargetor import ui
    errors = []
    ui.RETARGETOR_PT_GeneratePanel.draw(type("Panel", (), {"layout": CheckingLayout(errors)})(), bpy.context)
    return errors


def main():
    checks = bootstrap.Checks("test_generate")
    bootstrap.register_addon()
    from retargetor import generation
    from retargetor.core.skeleton_io import armature_backend
    from retargetor.properties import get_character

    bootstrap.set_backend("interpolate", developer=True)
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    rig = bpy.data.objects["rig"]
    view_layer.objects.active = rig
    # A Rigify rig needs no setup: choosing it as the character applies the Rigify preset
    from retargetor.profile_operators import detect_preset
    checks.check(len(rig.data.retargetor_profile.roles) == 0, "no rig profile at first")
    detected = detect_preset(rig.data)
    checks.check(detected is not None and detected[0].startswith("Rigify"), "the Rigify preset matches the rig")
    scene.retargetor_target = rig
    checks.check(len(rig.data.retargetor_profile.roles) == 23 and rig.data.retargetor_profile.source == detected[0],
                 f"choosing the character applied the preset ({rig.data.retargetor_profile.source})")
    checks.check(detect_preset(bpy.data.armatures.new("empty")) is None, "no preset for an armature without its bones")
    rig_profile = rig.data.retargetor_profile.to_core()
    controls = [b.write_bone for b in rig_profile.roles if b.write_bone]
    org_bones = [b.read_bone for b in rig_profile.roles if b.read_bone]
    limbs = [b.read_bone for b in rig_profile.roles if b.offset_mode == 'ROLL']

    checks.check(generation.find_key_frames(rig, rig_profile) == KEY_FRAMES, "key poses found on frames 1, 61, 120")
    checks.check(draw_generate_panel() == [], "Generate panel draws")
    before_poses = snapshot(rig, org_bones, KEY_FRAMES)
    before_keys = keys_by_type(rig, generation)

    # 1. First generation
    start = time.perf_counter()
    checks.check(bpy.ops.retargetor.generate_inbetweens('EXEC_DEFAULT') == {'FINISHED'}, "generation finished")
    print(f"FINDING interpolation backend, 120 frames, whole operator: {time.perf_counter() - start:.2f} s "
          f"(including the worker start)")
    model = rig.retargetor.model_armature
    checks.check(model is not None and armature_backend(model) == "interpolate" and model.hide_get(),
                 "model armature built, hidden")
    checks.check(len(model.data.bones) == 23, f"model skeleton: one joint per role ({len(model.data.bones)})")

    angle, dist = worst_change(rig, before_poses)
    checks.below(angle, 1e-4, "key poses untouched, worst bone direction (deg)")
    checks.below(dist, 1e-4, "key poses untouched, worst bone head (cm)")
    after_keys = keys_by_type(rig, generation)
    checks.check(user_keys(after_keys) == user_keys(before_keys), "user keys untouched (values and types)")

    rotation_curve = {c: next((path, 0) for path, _i in after_keys if path.startswith(f'pose.bones["{c}"].rotation'))
                      for c in controls}
    checks.check(len(rotation_curve) == 20, f"{len(rotation_curve)} controls written")
    # Rigify's shoulders are in Euler: they keep their rotation mode
    checks.check(rotation_curve["shoulder.L"][0].endswith("rotation_euler")
                 and rig.pose.bones["shoulder.L"].rotation_mode == 'YXZ', "Euler controls keyed in Euler")
    expected = set(range(1, 121)) - set(KEY_FRAMES)
    generated_frames = {c: {f for f, (_v, t) in after_keys[curve].items() if t == 'GENERATED'}
                        for c, curve in rotation_curve.items()}
    checks.check(all(frames == expected for frames in generated_frames.values()),
                 "GENERATED keys on every frame but the key poses, on every control")
    torso_loc = after_keys.get(('pose.bones["torso"].location', 1), {})
    checks.check(sum(1 for _v, t in torso_loc.values() if t == 'GENERATED') == len(expected), "torso location keyed")
    checks.check(quaternion_flips(rig, generation, controls) == 0, "quaternion signs continuous across user keys")

    # The rig follows the model's motion between the key poses
    from retargetor.backends.interpolate.backend import InterpolateBackend
    joint_of = {b.read_bone: InterpolateBackend.joint_map[b.role] for b in rig_profile.roles}
    total = count = 0
    worst = 0.0
    for frame in range(1, 121):
        scene.frame_set(frame)
        for bone in limbs:
            a = angle_deg(bone_direction(rig, bone), bone_direction(model, joint_of[bone]))
            total, count, worst = total + a, count + 1, max(worst, a)
    checks.below(total / count, 0.1, "rig follows the model, mean limb direction (deg)")
    checks.below(worst, 2.0, "rig follows the model, worst limb direction (deg)")
    # The root moves in a straight line between key poses (lerp), so the hips do too
    heads = {}
    for frame in (1, 31, 61):
        scene.frame_set(frame)
        heads[frame] = rig.matrix_world @ rig.pose.bones["ORG-spine"].head
    checks.below(((heads[1] + heads[61]) / 2 - heads[31]).length * 100, 0.1, "hips halfway at frame 31 (cm)")

    # 1b. Step by step, as the modal operator runs it: the keys are written over many small steps, the progress
    # goes up to 100%, writing can't be cancelled, and the result is the same
    first_keys = keys_by_type(rig, generation)
    task = generation.GenerationTask()
    task.start(bpy.context, rig)
    fractions, writing_steps, refused = [], 0, False
    while not task.update(bpy.context, budget=0.02):
        fractions.append(task.fraction)
        if task.stage == generation.WRITING:
            writing_steps += 1
            if not refused:
                refused = not task.cancellable
                task.cancel()
                checks.check(task.message.startswith("Writing keys"), f"progress message while writing ({task.message})")
        time.sleep(0.005)
    checks.check(not task.cancelled and task.result is not None, "step by step generation finished, cancel refused "
                                                                  "while writing")
    checks.check(refused, "writing is not cancellable")
    checks.check(writing_steps >= 5, f"keys written over several steps ({writing_steps})")
    checks.check(all(b >= a - 1e-9 for a, b in zip(fractions, fractions[1:])), "progress never goes back")
    checks.check(max(fractions) > 0.8 and task.fraction == 1.0, f"progress goes up to 100% ({max(fractions):.2f})")
    stepped_keys = keys_by_type(rig, generation)
    diffs = [(curve, f, v, stepped_keys.get(curve, {}).get(f)) for curve, frames in first_keys.items()
             for f, v in frames.items() if stepped_keys.get(curve, {}).get(f) is None
             or abs(stepped_keys[curve][f][0] - v[0]) > 1e-5 or stepped_keys[curve][f][1] != v[1]]
    checks.check(not diffs and set(first_keys) == set(stepped_keys), "same keys as the generation in one go")

    # 2. A new user key on frame 90, then regenerate: GENERATED keys replaced, frame 90 not written
    scene.frame_set(90)
    head = rig.pose.bones["head"]
    head.rotation_quaternion = (0.9, 0.3, 0.0, 0.0)
    head.keyframe_insert("rotation_quaternion", frame=90)
    # Keying over a GENERATED key keeps its type (Blender's behaviour, even with keytype='KEYFRAME'); the add-on's
    # handler retypes it as soon as the depsgraph sees the action changed
    checks.check(key_type(rig, generation, 'pose.bones["head"].rotation_quaternion', 0, 90) == 'GENERATED',
                 "FINDING keying over a GENERATED key keeps it GENERATED")
    view_layer.update()
    checks.check(all(key_type(rig, generation, 'pose.bones["head"].rotation_quaternion', i, 90) == 'KEYFRAME'
                     for i in range(4)), "the edited key is a Keyframe right away, on its 4 channels")
    checks.check(key_type(rig, generation, 'pose.bones["neck"].rotation_quaternion', 0, 90) == 'GENERATED',
                 "the other generated keys of the frame stay Generated")
    keys_before = keys_by_type(rig, generation)
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig), "second generation")
    print("FINDING interpolation backend, second generation: " +
          ", ".join(f"{name} {seconds:.2f} s" for name, seconds in task.timings.items()))
    checks.check(task.key_frames == [1, 61, 90, 120], f"frame 90 is a key pose ({task.key_frames})")
    after_keys = keys_by_type(rig, generation)
    checks.check(user_keys(after_keys) == user_keys(keys_before), "user keys untouched by the regeneration")
    frames = after_keys[('pose.bones["upper_arm_fk.L"].rotation_quaternion', 0)]
    generated = {f for f, (_v, t) in frames.items() if t == 'GENERATED'}
    # Frame 90 keys the head alone: the other controls are written there, the head isn't
    checks.check(generated == expected, "GENERATED keys replaced, the other controls written on frame 90")
    checks.check(key_type(rig, generation, 'pose.bones["head"].rotation_quaternion', 0, 90) == 'KEYFRAME',
                 "the head keeps its user key on frame 90")
    checks.check(len(frames) == 120, f"no duplicate keys ({len(frames)} keys on upper_arm_fk.L)")
    checks.check(task.request.key_poses[90].constrained_joints is None, "the interpolation backend gets whole poses")
    # 117 generated frames on 18 quaternion controls, 2 Euler shoulders and the torso location, minus the
    # 4 keys retyped on frame 90
    checks.check(task.result[1] == 117 * (18 * 4 + 2 * 3 + 3) - 4, f"{task.result[1]} old GENERATED keys removed")
    scene.frame_set(90)
    checks.close(head.rotation_quaternion.w, 0.9, 1e-6, "the new user key keeps its value")

    # A backend taking partial poses gets the joints keyed on frame 90 only (the head); whole key poses elsewhere
    import dataclasses
    from retargetor.backends.registry import get
    backend = get("interpolate")
    capabilities = backend.capabilities
    backend.capabilities = dataclasses.replace(capabilities, partial_poses=True)
    try:
        task = generation.GenerationTask()
        checks.check(task.run(bpy.context, rig), "generation with partial poses")
        poses = task.request.key_poses
        checks.check(poses[90].constrained_joints == ["head"] and len(poses[90].rotations) == 23,
                     f"frame 90 constrains the head, and lists every joint ({poses[90].constrained_joints})")
        checks.check(all(poses[f].constrained_joints is None for f in (1, 61, 120)), "the other key poses are whole")
    finally:
        backend.capabilities = capabilities

    # 2a. Edits like the Graph Editor's: a value changed, then put back (a cancelled drag); a key moved in time.
    # fcurve.update() may move the keys in memory: they are looked up again after each one
    path = 'pose.bones["forearm_fk.R"].rotation_quaternion'
    original = key_at(rig, generation, path, 1, 40).co.y
    edit_key(rig, generation, path, 1, 40, value=original + 0.2)
    checks.check(all(key_type(rig, generation, path, i, 40) == 'KEYFRAME' for i in range(4)), "value edited: Keyframe")
    edit_key(rig, generation, path, 1, 40, value=original)
    checks.check(all(key_type(rig, generation, path, i, 40) == 'GENERATED' for i in range(4)),
                 "value put back (cancelled drag): Generated again")
    torso = 'pose.bones["torso"].location'
    edit_key(rig, generation, torso, 2, 70, shift=0.4)
    checks.check(key_type(rig, generation, torso, 2, 70.4) == 'KEYFRAME', "key moved in time: Keyframe")
    edit_key(rig, generation, torso, 2, 70.4, shift=-0.4)
    checks.check(key_type(rig, generation, torso, 2, 70) == 'GENERATED', "key moved back: Generated again")
    # An edit the handler didn't see (handler off): retyped when generating; the frame becomes a key pose
    from retargetor import generated_keys
    bpy.app.handlers.depsgraph_update_post.remove(generated_keys.retype_edited_handler)
    edited_value = key_at(rig, generation, torso, 2, 70).co.y + 0.05
    edit_key(rig, generation, torso, 2, 70, value=edited_value)
    bpy.app.handlers.depsgraph_update_post.append(generated_keys.retype_edited_handler)
    checks.check(key_type(rig, generation, torso, 2, 70) == 'GENERATED', "edit unseen: still Generated")
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig), "generation after an unseen edit")
    # The 3 channels of the location on that frame: x, y and z
    checks.check(any("3 edited Generated keys" in note for note in task.notes) and 70 in task.key_frames,
                 f"retyped before generating, frame 70 is a key pose ({task.notes}, {task.key_frames})")
    key = key_at(rig, generation, torso, 2, 70)
    checks.check(key.type == 'KEYFRAME' and abs(key.co.y - edited_value) < 1e-6, "the edited value is kept")
    # The generation's own keys don't trigger the handler: only the user keys are Keyframes
    after = keys_by_type(rig, generation)
    stray = [(c, f) for c, frames in after.items() for f, (_v, t) in frames.items()
             if t == 'KEYFRAME' and f not in (1, 61, 70, 90, 120)]
    checks.check(not stray, f"no generated key retyped by the generation itself ({stray[:3]})")
    # Back to the key poses of the next sections: frame 70 is no key pose any more
    for curve in generation.bone_fcurves(rig):
        for p in list(curve.keyframe_points):
            if round(p.co.x) == 70 and p.type != 'GENERATED':
                curve.keyframe_points.remove(p)
    view_layer.update()

    # 2b. Custom range past the last key pose: extends the animation (the interpolation holds the last pose)
    state = rig.retargetor
    scene.frame_set(1)
    state.range_mode = 'CUSTOM'
    checks.check(state.range_start == 1, "a custom range starts on the current frame")
    state.range_duration = 150
    keys_before = keys_by_type(rig, generation)
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig), "generation on a custom range, past the last key pose")
    checks.check((task.start_frame, task.end_frame, task.key_frames) == (1, 150, [1, 61, 90, 120]),
                 f"range 1-150 with its key poses ({task.start_frame}-{task.end_frame}, {task.key_frames})")
    after_keys = keys_by_type(rig, generation)
    checks.check(user_keys(after_keys) == user_keys(keys_before), "user keys untouched by the custom range")
    frames = after_keys[('pose.bones["upper_arm_fk.L"].rotation_quaternion', 0)]
    generated = {f for f, (_v, t) in frames.items() if t == 'GENERATED'}
    checks.check(generated == set(range(1, 151)) - {1, 61, 120}, "GENERATED keys up to frame 150")
    held = snapshot(rig, END_BONES, [120])[120]
    angle, dist = worst_change(rig, {150: held})
    checks.below(angle, 1e-3, "frame 150 holds the last key pose (deg)")

    # A range holding one key pose: the interpolation backend needs two, the panel says so
    state.range_start, state.range_duration = 100, 51
    checks.check(generation.generation_range(rig, rig_profile) == (100, 150, [120]), "key poses outside the range "
                                                                                       "are ignored")
    checks.check(run_operator() == {'CANCELLED'}, "one key pose refused by the interpolation backend")
    from retargetor.backends.registry import get
    problem = get("interpolate").range_problem(100, 150, 30.0, 1)
    checks.check("at least 2 key poses" in problem, f"the message says why ({problem})")
    checks.check(draw_generate_panel() == [], "Generate panel draws a custom range")
    checks.check(get("kimodo").range_problem(100, 150, 30.0, 0) == "", "Kimodo takes a range without key pose")
    checks.check("at most 10 s" in get("kimodo").range_problem(1, 301, 30.0, 0), "Kimodo: 10 s at most")
    state.range_mode = 'KEY_POSES'

    # 2c. Prompt segments with a backend generating one request per segment (the interpolation backend): each one
    # starts from the previous one's last frame, without transition
    from retargetor import segment_track
    from retargetor.core.segments import PromptSegment
    segment_track.write_track(state, [PromptSegment(1, 61, "walks", 1), PromptSegment(62, 120, "runs", 2)])
    keys_before = keys_by_type(rig, generation)
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig), "generation of two prompt segments, one after the other")
    checks.check([(c.request_start, c.write_start, c.write_end) for c in task.chunks] == [(1, 1, 61), (61, 62, 120)],
                 "one request per segment, the second from the first one's last frame")
    checks.check(task.request.start_frame == 61 and not task.request.segments, "the last request: segment 2 alone")
    after_keys = keys_by_type(rig, generation)
    checks.check(user_keys(after_keys) == user_keys(keys_before), "user keys untouched by the segments")
    frames = after_keys[('pose.bones["upper_arm_fk.L"].rotation_quaternion', 0)]
    generated = {f for f, (_v, t) in frames.items() if t == 'GENERATED' and f <= 120}  # 121-150: section 2b
    checks.check(generated == set(range(1, 121)) - {1, 61, 120}, "GENERATED keys on both segments")
    checks.check(task.result[0] == 117, f"117 frames written ({task.result})")
    checks.check(all(segment_track.segment_state(item) == 'GENERATED' for item in state.segments),
                 "the segments are marked generated")
    checks.check(draw_generate_panel() == [], "Generate panel draws the segments")
    kimodo_chunks = generation.generation_chunks(state, get("kimodo"), 1, 120)
    checks.check(len(kimodo_chunks) == 1 and len(kimodo_chunks[0].segments) == 2,
                 "a backend generating segments in one pass gets them in one request")

    # 2d. One segment regenerated alone: the motion around it is sent (the interpolation backend continues it), only
    # its frames are written, the rest of the track stays as it is
    # Two key poses in each segment, counting the frame before it (the interpolation backend generates them one by
    # one, each from the previous one's last frame)
    segment_track.write_track(state, [PromptSegment(1, 61, "walks", 1), PromptSegment(62, 90, "runs", 2),
                                      PromptSegment(91, 120, "stops", 3)])
    checks.check(generation.GenerationTask().run(bpy.context, rig), "the whole track of 3 segments")
    # A key pose added in segment 2 (the head turned): regenerating segment 2 must go through it
    head = 'pose.bones["head"].rotation_quaternion'
    scene.frame_set(75)
    rig.pose.bones["head"].rotation_quaternion = (0.94, 0.0, 0.0, 0.34)
    rig.keyframe_insert(head, frame=75, keytype='KEYFRAME')
    state.segments[0].prompt = "walks slowly"  # segment 1 edited: it stays "modified"
    keys_before = keys_by_type(rig, generation)
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig, segment=1), "segment 2 regenerated alone")
    request = task.request
    checks.check((request.start_frame, request.end_frame, sorted(request.key_poses)) == (62, 90, [75, 90]),
                 f"the request: segment 2 and its key poses ({request.start_frame}-{request.end_frame}, "
                 f"{sorted(request.key_poses)})")
    checks.check((request.context_before.start_frame, request.context_before.end_frame,
                  request.context_after.start_frame, request.context_after.end_frame) == (61, 61, 91, 91),
                 "the motion around it: one frame on each side for the interpolation backend")
    after_keys = keys_by_type(rig, generation)
    outside = {c: {f: v for f, v in frames.items() if not 62 <= f <= 90} for c, frames in after_keys.items()}
    outside_before = {c: {f: v for f, v in frames.items() if not 62 <= f <= 90} for c, frames in keys_before.items()}
    checks.check(outside == outside_before, "the rest of the track is unchanged (values and types)")
    changed = [(c, f, v, user_keys(after_keys).get(c, {}).get(f)) for c, frames in user_keys(keys_before).items()
               for f, v in frames.items() if user_keys(after_keys).get(c, {}).get(f) != v]
    checks.check(not changed, f"user keys untouched ({changed[:4]})")
    # Keying the head over its Generated keys kept them Generated (Blender keeps a replaced key's type): the
    # generation retyped them as Keyframes, the only new user keys
    added = {(c[0], f) for c, frames in user_keys(after_keys).items() for f in frames
             if f not in user_keys(keys_before).get(c, {})}
    checks.check(added == {(head, 75)}, f"the head's key pose retyped as Keyframes, nothing else ({added})")
    curve = ('pose.bones["upper_arm_fk.L"].rotation_quaternion', 0)
    user = {f for f, (_v, t) in keys_before[curve].items() if t != 'GENERATED'}
    generated = {f for f, (_v, t) in after_keys[curve].items() if t == 'GENERATED' and 62 <= f <= 90}
    checks.check(generated == set(range(62, 91)) - user, "GENERATED keys on segment 2")
    checks.check(task.result[0] > 0 and task.result[1] > 0,
                 f"its frames written, its old Generated keys replaced ({task.result})")
    # Through the new key pose, joining the motion before it: the head halfway between frame 61 and 75
    expected = {}
    for frame in (61, 68, 75):
        scene.frame_set(frame)
        expected[frame] = rig.pose.bones["ORG-spine.006"].matrix.to_quaternion()
    middle = expected[61].slerp(expected[75], 0.5)
    checks.below(math.degrees(middle.rotation_difference(expected[68]).angle), 0.5,
                 "the head halfway from the motion before (frame 61) to the new key pose (deg)")
    states = [segment_track.segment_state(item) for item in state.segments]
    checks.check(states == ['MODIFIED', 'GENERATED', 'GENERATED'], f"only segment 2 marked generated ({states})")
    # A neighbour never generated isn't continued
    state.segments[2].generated = ""
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig, segment=1), "segment 2 next to a segment never generated")
    checks.check(task.request.context_before is not None and task.request.context_after is None,
                 "the segment never generated is not continued")
    checks.check(any("segment 3 (after)" in note for note in task.notes), f"the report says so ({task.notes})")
    # The operator, on the active segment
    state.segments_active_index = 0
    checks.check(bpy.ops.retargetor.regenerate_segment('EXEC_DEFAULT') == {'FINISHED'},
                 "Regenerate Segment, on the active segment")
    states = [segment_track.segment_state(item) for item in state.segments]
    checks.check(states == ['GENERATED', 'GENERATED', 'NEW'], f"segment 1 generated, segment 3 still new ({states})")
    checks.check(draw_generate_panel() == [], "Generate panel draws the Regenerate button")
    # Kimodo gets about 5 model frames on each side; a backend that doesn't continue the motion gets the segment
    # from the frame before it, without context
    state.segments[2].generated = segment_track.generated_signature(state.segments[2])
    chunk, _notes = generation.segment_chunk(state, get("kimodo"), 1, 30.0)
    checks.check((chunk.context_before, chunk.context_after, chunk.request_start) == ((57, 61), (91, 95), 62),
                 f"Kimodo: 5 frames on each side ({chunk.context_before}, {chunk.context_after})")
    from retargetor.backends.base import Backend, Capabilities
    plain = type("Plain", (Backend,), {"label": "Plain", "capabilities": Capabilities(min_key_poses=2)})()
    chunk, notes = generation.segment_chunk(state, plain, 1, 30.0)
    checks.check((chunk.context_before, chunk.context_after, chunk.request_start) == (None, None, 61)
                 and "without transition" in notes[0], "without motion_context: from the frame before, no transition")
    for curve in generation.bone_fcurves(rig, ["head"]):
        for p in list(curve.keyframe_points):
            if round(p.co.x) == 75 and p.type != 'GENERATED':
                curve.keyframe_points.remove(p)
    state.segments.clear()

    # 3. An arm in IK (its IK controls at rest): its FK controls are snapped to the IK pose on the key poses,
    # it is in FK while generating, then its IK controls are snapped to the motion and it is back in IK (the switch
    # isn't animated: set once). tests/blender/test_generate_ik.py checks the IK snap on a real IK pose.
    switch = rig.pose.bones["upper_arm_parent.L"]
    switch["IK_FK"] = 0.0
    rig.update_tag()
    arm = ["ORG-upper_arm.L", "ORG-forearm.L", "ORG-hand.L"]
    key_frames = [1, 61, 90, 120]
    ik_pose = snapshot(rig, arm, key_frames)

    def in_fk(function):
        switch["IK_FK"] = 1.0
        rig.update_tag()
        try:
            return function()
        finally:
            switch["IK_FK"] = 0.0
            rig.update_tag()

    checks.check(run_operator() == {'FINISHED'}, "generated with an arm in IK")
    checks.check(switch["IK_FK"] == 0.0, "the arm is back in IK")
    # Frame 90 keys the head alone: the body is generated there (the interpolation goes through the pose read
    # there, within 0.02 degrees after the round trip through the spine's read-only roles)
    angle, _dist = in_fk(lambda: worst_change(rig, {f: bones for f, bones in ik_pose.items() if f != 90}))
    checks.below(angle, 0.01, "the FK arm takes the IK pose on the whole key poses, worst direction (deg)")
    angle, _dist = in_fk(lambda: worst_change(rig, {90: ik_pose[90]}))
    checks.below(angle, 0.05, "the FK arm takes the IK pose on frame 90, where the body is generated (deg)")
    # The IK hand stays at rest while the character walks away: Rigify's IK stretches the arm (by a metre), which
    # the FK chain doesn't. Only the shoulder joint keeps its place.
    _angle, dist = in_fk(lambda: worst_change(
        rig, {f: {"ORG-upper_arm.L": bones["ORG-upper_arm.L"]} for f, bones in ik_pose.items()}))
    checks.below(dist, 0.01, "the shoulder joint stays in place on the key poses (cm)")
    # In IK the key poses keep the IK controls as they were (keyed there as user keys), and the hand follows the
    # FK motion between them
    angle, dist = worst_change(rig, ik_pose)
    checks.below(angle + dist, 1e-3, "in IK, the key poses are as they were")
    after_keys = keys_by_type(rig, generation)
    hand_keys = after_keys[('pose.bones["hand_ik.L"].location', 0)]
    checks.check({f for f, (_v, t) in hand_keys.items() if t == 'KEYFRAME'} == set(key_frames)
                 and {f for f, (_v, t) in hand_keys.items() if t == 'GENERATED'} == set(range(1, 121)) - set(key_frames),
                 "the IK hand keyed as it was on the key poses, generated between them")
    snapped = after_keys[('pose.bones["forearm_fk.L"].rotation_quaternion', 0)]
    checks.check(all(snapped[f][1] == 'KEYFRAME' for f in key_frames), "the snapped FK keys are user keys")
    checks.check(quaternion_flips(rig, generation, controls) == 0, "quaternion signs still continuous")

    # The switch animated, in IK on a key pose: snapped there, its keys put back as they were
    switch["IK_FK"] = 1.0
    switch.keyframe_insert('["IK_FK"]', frame=1)
    switch["IK_FK"] = 0.0
    switch.keyframe_insert('["IK_FK"]', frame=61)
    switch["IK_FK"] = 1.0
    switch.keyframe_insert('["IK_FK"]', frame=120)
    rig.update_tag()
    fcurve = generation.channelbag(rig).fcurves.find('pose.bones["upper_arm_parent.L"]["IK_FK"]')
    switch_keys = [(tuple(p.co), p.type) for p in fcurve.keyframe_points]
    checks.check(run_operator() == {'FINISHED'}, "generated with the switch going to IK on a key pose")
    fcurve = generation.channelbag(rig).fcurves.find('pose.bones["upper_arm_parent.L"]["IK_FK"]')
    checks.check([(tuple(p.co), p.type) for p in fcurve.keyframe_points] == switch_keys and not fcurve.mute,
                 "the switch's keys are put back as they were")

    # The switch going to IK between two key poses, on a limb without IK snap: refused, the rig untouched (with an
    # IK snap, the limb plays the motion in IK and FK alike: see test_generate_ik.py)
    rig.data.retargetor_profile.limbs[0].ik_snap.clear()
    rig_profile = rig.data.retargetor_profile.to_core()
    switch["IK_FK"] = 0.0
    switch.keyframe_insert('["IK_FK"]', frame=100)
    keys_before = keys_by_type(rig, generation)
    checks.check(run_operator() == {'CANCELLED'}, "refused when the switch goes to IK between key poses")
    try:
        generation.limbs_in_ik(rig, rig_profile, 1, 120, key_frames)
        message = ""
    except ValueError as e:
        message = str(e)
    checks.check("arm.L" in message and "100" in message, f"the message names the limb and the frame ({message})")
    checks.check(keys_by_type(rig, generation) == keys_before, "nothing changed on the rig")

    # 4. A deleted character: the scene's pointer keeps the object alive, out of every scene
    for collection in list(rig.users_collection):
        collection.objects.unlink(rig)
    checks.check(scene.retargetor_target == rig, "the deleted rig is still the scene's target")
    checks.check(get_character(bpy.context) == (None, None), "a target out of the scene isn't the character")
    checks.check(not bpy.ops.retargetor.generate_inbetweens.poll(), "no generation on a target out of the scene")
    checks.finish()


if __name__ == "__main__":
    main()
