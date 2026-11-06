"""Prompt segments on a character: adding, editing, splitting, removing, selecting, and the Generate panel.

    blender -b --factory-startup --python tests/blender/test_segments.py
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402
from test_panel import draw_panels  # noqa: E402


def bounds(state):
    return [(s.frame_start, s.frame_end) for s in state.segments]


def main():
    checks = bootstrap.Checks("test_segments")
    _source, rig = bootstrap.make_test_scene()
    bootstrap.register_addon()
    from retargetor import generation, segment_track, ui
    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = 24, 1.0
    bootstrap.set_backend("kimodo")  # at most 10 s per segment: 240 frames
    scene.retargetor_target = rig
    state = rig.retargetor

    errors = draw_panels([ui.RETARGETOR_PT_GeneratePanel])
    checks.check(not errors, f"Generate panel without segments draws: {errors}")

    # The first segment takes the prompt, seed and custom range
    state.prompt, state.seed = "walks forward", 3
    state.range_mode = 'CUSTOM'
    state.range_start, state.range_duration = 10, 100
    bpy.ops.retargetor.segment_add()
    checks.check(bounds(state) == [(10, 109)], f"first segment from the custom range: {bounds(state)}")
    checks.check((state.segments[0].prompt, state.segments[0].seed) == ("walks forward", 3),
                 "first segment from the prompt and seed")
    bpy.ops.retargetor.segment_add()
    checks.check(bounds(state) == [(10, 109), (110, 157)], f"a 2 s segment added at the end: {bounds(state)}")
    checks.check(state.segments_active_index == 1 and state.segments[1].seed == 3 and state.segments[1].prompt == "",
                 "the new segment is active, with the previous seed and no prompt")

    # Editing an end moves the boundary; the limits hold
    state.segments[0].frame_end = 79
    checks.check(bounds(state) == [(10, 79), (80, 157)], f"end edited, next segment follows: {bounds(state)}")
    state.segments[0].frame_end = 5
    checks.check(bounds(state) == [(10, 21), (22, 157)], f"shortest segment 0.5 s (12 frames): {bounds(state)}")
    state.segments[1].frame_start = 200
    checks.check(bounds(state) == [(10, 145), (146, 157)], f"start edited, previous one follows: {bounds(state)}")
    state.segments[1].frame_end = 1000
    checks.check(bounds(state) == [(10, 145), (146, 385)], f"longest segment 10 s (240 frames): {bounds(state)}")
    state.segments[0].frame_start = 0
    checks.check(bounds(state) == [(0, 145), (146, 385)], f"track start moved: {bounds(state)}")

    start, end, _keys = generation.generation_range(rig, _profile(rig))
    checks.check((start, end) == (0, 385), f"the generation covers the track: {start}-{end}")

    # Split at the current frame, then remove: the one before takes the frames
    scene.frame_set(50)
    bpy.ops.retargetor.segment_split()
    checks.check(bounds(state) == [(0, 49), (50, 145), (146, 385)], f"split at frame 50: {bounds(state)}")
    checks.check(state.segments_active_index == 1 and state.segments[1].prompt == "walks forward",
                 "the second part is active and keeps the prompt")
    scene.frame_set(1)
    try:
        bpy.ops.retargetor.segment_split()
        refused = False
    except RuntimeError as e:
        refused = "too close" in str(e)
    checks.check(refused and len(state.segments) == 3, "no split 1 frame from a segment's start")
    bpy.ops.retargetor.segment_remove(index=1)
    checks.check(bounds(state) == [(0, 145), (146, 385)], f"removed, the previous one takes it: {bounds(state)}")

    # Generated state
    checks.check(segment_track.segment_state(state.segments[0]) == 'NEW', "never generated")
    segment_track.mark_generated(state)
    checks.check(segment_track.segment_state(state.segments[0]) == 'GENERATED', "generated")
    state.segments[1].prompt = "jumps"
    checks.check(segment_track.segment_state(state.segments[1]) == 'MODIFIED', "edited since generated")
    checks.check(segment_track.segment_state(state.segments[0]) == 'GENERATED', "the other one is unchanged")

    # Selection from another character, and the arrows
    other = bootstrap.make_armature("OTHER", bootstrap.TARGET_BONES)
    scene.retargetor_target = other
    bpy.ops.retargetor.segment_select(character=rig.name, index=0)
    checks.check(scene.retargetor_target == rig and state.segments_active_index == 0,
                 "selecting a segment makes its character the panel's")
    bpy.ops.retargetor.segment_step(step=1)
    checks.check(state.segments_active_index == 1, "next segment")
    bpy.ops.retargetor.segment_step(step=5)
    checks.check(state.segments_active_index == 1, "stays on the last one")

    errors = draw_panels([ui.RETARGETOR_PT_GeneratePanel])
    checks.check(not errors, f"Generate panel with segments draws: {errors}")

    bpy.ops.retargetor.segment_remove()
    bpy.ops.retargetor.segment_remove()
    checks.check(len(state.segments) == 0, "every segment removed")
    checks.check(generation.generation_range(rig, _profile(rig))[:2] == (10, 109), "back to the custom range")
    check_layout(checks)
    checks.finish()


def check_layout(checks):
    """Where the bands are, and what is under a point"""
    from retargetor import segment_draw as sd
    characters = [("rig", True, [(1, 40), (41, 80)]), ("other", False, [(1, 120)])]
    bands = sd.band_layout(characters, lambda frame: 10.0 * frame, 2.0, tag_x0=0.0, tag_width=lambda name: 30.0)
    checks.check([(b.y0, b.y1) for b in bands] == [(44.0, 112.0), (120.0, 188.0)], "bands stacked, UI scale 2")
    checks.check([(bar.x0, bar.x1) for bar in bands[0].bars] == [(5.0, 405.0), (405.0, 805.0)],
                 "segments from half a frame before to half a frame after")
    y = 60.0
    checks.check(sd.hit_test(bands, 200.0, y, 2.0) == ("rig", 0, 'BODY'), "body of the first segment")
    checks.check(sd.hit_test(bands, 412.0, y, 2.0) == ("rig", 1, 'START'), "boundary: start of the next segment")
    checks.check(sd.hit_test(bands, 800.0, y, 2.0) == ("rig", 1, 'END'), "track's end")
    checks.check(sd.hit_test(bands, 20.0, y, 2.0) == ("rig", None, 'TAG'), "name tag")
    checks.check(sd.hit_test(bands, 900.0, y, 2.0) is None, "after the track")
    checks.check(sd.hit_test(bands, 900.0, 150.0, 2.0) == ("other", 0, 'BODY'), "second band")
    checks.check(sd.hit_test(bands, 200.0, 20.0, 2.0) is None, "below the bands")


def _profile(rig):
    """A profile writing one control of the small test rig, enough to find its key poses"""
    from retargetor.core.profile import PROFILE_FORMAT, RigProfile
    return RigProfile.from_dict({"format": PROFILE_FORMAT, "version": 1, "roles": [{"role": "hips", "read_bone": "hips",
                                                          "write_bone": "hips"}]})


if __name__ == "__main__":
    main()
