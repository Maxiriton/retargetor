"""The prompt segments' bands with the mouse, through simulated events in Blender's interface (not headless).

    BLENDER_USER_RESOURCES=<scratch folder> blender --factory-startup -y --enable-event-simulate
        <rig_keyposes.blend> --python tests/blender/test_segment_mouse.py

Opens a window for about a minute. tests/run_tests.py --gui runs it with its own user folder, so nothing it does
can reach your preferences; --enable-event-simulate makes Blender ignore the real mouse and keyboard meanwhile.
Checks: the add-on's keymap items come before Blender's own on the bands (a click there leaves the keys' selection
alone) and let the events through elsewhere (a click off the bands deselects the keys), hover, select, drag a
boundary, drag a segment, Esc, "+", a name tag, the Graph Editor, and right-click select.
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402

checks = bootstrap.Checks("test_segment_mouse")
TICK = 0.05


def bounds(rig):
    return [(s.frame_start, s.frame_end) for s in rig.retargetor.segments]


def selected_keys(rig):
    from retargetor import generation
    return sum(p.select_control_point for fc in generation.bone_fcurves(rig) for p in fc.keyframe_points)


def select_all_keys(rig, value=True):
    from retargetor import generation
    for fc in generation.bone_fcurves(rig):
        for p in fc.keyframe_points:
            p.select_control_point = value


class Ui:
    def __init__(self):
        self.window = bpy.context.window_manager.windows[0]
        self.area = max(self.window.screen.areas, key=lambda a: a.width * a.height)

    @property
    def region(self):
        return next(r for r in self.area.regions if r.type == 'WINDOW')

    def override(self):
        return bpy.context.temp_override(window=self.window, area=self.area, region=self.region)

    def bands(self):
        from retargetor import segment_draw
        with self.override():
            return segment_draw.region_bands(bpy.context, self.region)[0]

    def frame_x(self, frame):
        """Window x of a frame"""
        return self.region.x + round(self.region.view2d.view_to_region(frame, 0.0, clip=False)[0])

    def band_y(self, row=0):
        band = self.bands()[row]
        return self.region.y + round((band.y0 + band.y1) / 2)

    def event(self, kind, value, x, y):
        self.window.event_simulate(kind, value, x=int(x), y=int(y))


def steps():
    ui = Ui()
    scene = bpy.context.scene
    rig = bpy.data.objects["rig"]
    from retargetor import segment_draw, segment_track
    from retargetor.core.segments import PromptSegment

    other = rig.copy()
    other.name = "other"
    scene.collection.objects.link(other)
    other.retargetor.segments.clear()
    segment_track.write_track(other.retargetor, [PromptSegment(1, 120, "waits", 2)])
    scene.retargetor_target = rig
    segment_track.write_track(rig.retargetor, [PromptSegment(1, 40, "walks", 0), PromptSegment(41, 80, "turns", 0),
                                               PromptSegment(81, 120, "sits", 0)], active=0)
    for obj in scene.objects:
        obj.select_set(obj in (rig, other))
    bpy.context.view_layer.objects.active = rig
    ui.area.ui_type = 'DOPESHEET'
    ui.area.spaces.active.mode = 'ACTION'
    ui.area.spaces.active.show_region_ui = False  # the sidebar would take the clicks on the right
    yield 0.5
    with ui.override():
        bpy.ops.action.view_all()
    yield 0.5

    # The first events reach the window once it is ready: a few moves first
    bands = ui.bands()
    checks.check(len(bands) == 2 and bands[0].character == "rig" and bands[1].character == "other",
                 f"two bands, the panel's character first ({[b.character for b in bands]})")
    y = ui.band_y()

    # One event per timer tick, as a real mouse would send them
    def move(x, y):
        ui.event('MOUSEMOVE', 'NOTHING', x, y)
        yield TICK

    def click(x, y, button='LEFTMOUSE'):
        yield from move(x, y)
        ui.event(button, 'PRESS', x, y)
        yield TICK
        ui.event(button, 'RELEASE', x, y)
        yield TICK

    def key(kind, x, y):
        ui.event(kind, 'PRESS', x, y)
        yield TICK
        ui.event(kind, 'RELEASE', x, y)
        yield TICK

    def drag(x0, x1, y, button='LEFTMOUSE', cancel=False):
        yield from move(x0, y)
        ui.event(button, 'PRESS', x0, y)
        yield TICK
        for k in range(1, 6):
            yield from move(x0 + (x1 - x0) * k / 5, y)
        if cancel:
            yield from key('ESC', x1, y)
        ui.event(button, 'RELEASE', x1, y)
        yield TICK

    # Warm-up (the first simulated events don't reach the editor): a drag cancelled with Esc
    yield from drag(ui.frame_x(60), ui.frame_x(62), y, cancel=True)

    # Hover
    yield from move(ui.frame_x(60), y)
    checks.check(segment_draw.hover == ("rig", 1, 'BODY'), f"hover on the second segment ({segment_draw.hover})")
    yield from move(ui.frame_x(40.5), y)
    checks.check(segment_draw.hover == ("rig", 1, 'START'), f"hover on a boundary ({segment_draw.hover})")

    # A click on a band selects the segment, and doesn't reach Blender's key selection
    select_all_keys(rig)
    keys = selected_keys(rig)
    yield from click(ui.frame_x(100), y)
    yield 0.3
    checks.check(rig.retargetor.segments_active_index == 2, "click selects the third segment")
    checks.check(selected_keys(rig) == keys, f"the click on the band left the keys alone ({selected_keys(rig)}/{keys})")

    # Off the bands, Blender gets the click: clicking between the key poses deselects the keys
    yield from click(ui.frame_x(30), ui.region.y + ui.region.height - 60)
    yield 0.3
    checks.check(selected_keys(rig) == 0, f"a click off the bands reaches Blender ({selected_keys(rig)} keys selected)")
    checks.check(rig.retargetor.segments_active_index == 2, "and leaves the segments alone")

    # Drag a boundary: segment 1 grows, segment 2 shrinks
    yield from drag(ui.frame_x(40.5), ui.frame_x(50.5), y)
    yield 0.3
    checks.check(bounds(rig) == [(1, 50), (51, 80), (81, 120)], f"boundary dragged to frame 51 ({bounds(rig)})")
    checks.check(rig.retargetor.segments_active_index == 1, "the dragged segment is active")
    # Drag a segment: both boundaries
    yield from drag(ui.frame_x(65), ui.frame_x(60), y)
    yield 0.3
    checks.check(bounds(rig) == [(1, 45), (46, 75), (76, 120)], f"segment dragged 5 frames back ({bounds(rig)})")
    # Esc cancels a drag
    yield from drag(ui.frame_x(60), ui.frame_x(70), y, cancel=True)
    yield 0.3
    checks.check(bounds(rig) == [(1, 45), (46, 75), (76, 120)], f"Esc puts the segments back ({bounds(rig)})")
    # The track's end
    yield from drag(ui.frame_x(120.5), ui.frame_x(110.5), y)
    yield 0.3
    checks.check(bounds(rig)[-1] == (76, 110), f"the track's end dragged to frame 110 ({bounds(rig)})")

    # "+" adds a segment
    band = ui.bands()[0]
    yield from click(ui.region.x + (band.add_x0 + band.add_x1) / 2, y)
    yield 0.3
    checks.check(len(rig.retargetor.segments) == 4, f"\"+\" adds a segment ({bounds(rig)})")

    # The other character's name tag makes it the panel's
    band = ui.bands()[1]
    yield from click(ui.region.x + (band.tag_x0 + band.tag_x1) / 2, ui.band_y(1))
    yield 0.3
    checks.check(scene.retargetor_target == other, "a click on a name tag makes that character the panel's")
    scene.retargetor_target = rig
    yield 0.3

    # Right click: the segment's menu (the segment is selected first)
    y = ui.band_y()
    yield from click(ui.frame_x(20), y, 'RIGHTMOUSE')
    yield 0.3
    checks.check(rig.retargetor.segments_active_index == 0, "right click selects the segment under the mouse")
    yield from key('ESC', ui.frame_x(20), y)
    yield 0.3

    # The Graph Editor
    ui.area.ui_type = 'FCURVES'
    ui.area.spaces.active.show_region_ui = False
    yield 0.5
    with ui.override():
        bpy.ops.graph.view_all()
    yield 0.5
    y = ui.band_y()
    yield from click(ui.frame_x(60), y)
    yield 0.3
    checks.check(rig.retargetor.segments_active_index == 1, "click selects a segment in the Graph Editor")
    yield from drag(ui.frame_x(45.5), ui.frame_x(40.5), y)
    yield 0.3
    checks.check(bounds(rig)[:2] == [(1, 40), (41, 75)], f"boundary dragged in the Graph Editor ({bounds(rig)})")

    # Right-click select: the right button selects and drags, the left one opens the menu
    ui.area.ui_type = 'DOPESHEET'
    keyconfig = bpy.context.window_manager.keyconfigs.active
    keyconfig.preferences.select_mouse = 'RIGHT'
    yield 0.5
    y = ui.band_y()
    yield from drag(ui.frame_x(40.5), ui.frame_x(35.5), y, 'RIGHTMOUSE')
    yield 0.3
    checks.check(bounds(rig)[:2] == [(1, 35), (36, 75)], f"right-click select: right drag moves a boundary ({bounds(rig)})")
    yield from click(ui.frame_x(100), y)
    yield 0.3
    checks.check(rig.retargetor.segments_active_index == 2, "right-click select: left click selects and opens the menu")
    yield from key('ESC', ui.frame_x(100), y)
    keyconfig.preferences.select_mouse = 'LEFT'
    yield 0.3


_steps = None


def tick():
    global _steps
    try:
        if _steps is None:
            _steps = steps()
        return next(_steps)
    except StopIteration:
        pass
    except Exception:  # noqa: BLE001 - reported as a failed check
        import traceback
        traceback.print_exc()
        checks.check(False, "the test ran to its end")
    sys.stdout.flush()
    checks.finish()
    bpy.ops.wm.quit_blender()
    return None


def main():
    if bpy.app.background:
        raise SystemExit("test_segment_mouse needs Blender's interface (no -b)")
    bootstrap.register_addon()
    bootstrap.set_backend("kimodo")
    bpy.app.timers.register(tick, first_interval=1.0)


main()
