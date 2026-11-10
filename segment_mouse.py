# type: ignore
"""The prompt segments' bands handled with the mouse, like NLA strips (see segment_draw).

The add-on's keymap items in the Dope Sheet and Graph Editor run these operators on every click and mouse move
in the main region; off the bands they let the event through (PASS_THROUGH), so Blender's own tools get it.
- hover: highlights what is under the mouse, a left-right cursor on a boundary.
- click (select mouse): on a segment, selects it and drags it (both boundaries) or a boundary; on a name tag,
  makes the character the panel's; on "+", adds a segment. Esc or the other button cancels a drag.
- the other mouse button: the segment's menu. Double click: the segment's popup (prompt, seed, frames).
"""
import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Menu, Operator

from . import segment_draw, segment_track
from .core import segments as core_segments

# Mouse moves under this many pixels keep a click a click (no drag)
DRAG_THRESHOLD = 3


def _region_ok(context):
    region = context.region
    return region is not None and region.type == 'WINDOW' and hasattr(region, "view2d")


def under_mouse(context, event):
    """(character object, segment index or None, part) under the mouse, or None"""
    if not _region_ok(context):
        return None
    bands, _shown = segment_draw.region_bands(context, context.region)
    if not bands:
        return None
    hit = segment_draw.hit_test(bands, event.mouse_region_x, event.mouse_region_y,
                                context.preferences.system.ui_scale)
    if hit is None:
        return None
    rig = bpy.data.objects.get(hit[0])
    return (rig, hit[1], hit[2]) if rig is not None else None


def select_mouse(context):
    """'LEFT' or 'RIGHT': the mouse button selecting, from the keymap preferences"""
    keyconfig = context.window_manager.keyconfigs.active
    preferences = getattr(keyconfig, "preferences", None)
    return getattr(preferences, "select_mouse", 'LEFT') if preferences is not None else 'LEFT'


def _select(context, rig, index=None):
    """Make the character the panel's, and the segment its active one"""
    scene = context.scene
    if scene.retargetor_target != rig:
        scene.retargetor_target = rig
    state = rig.retargetor
    if index is not None and state.segments_active_index != index:
        state.segments_active_index = index
    segment_track.tag_redraw()


class RTGTR_OT_SegmentHover(Operator):
    """Highlight the prompt segment under the mouse"""
    bl_idname = "retargetor.segment_hover"
    bl_label = "Prompt Segment Hover"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        hit = under_mouse(context, event)
        new = (hit[0].name, hit[1], hit[2]) if hit is not None else None
        if new != segment_draw.hover:
            was_edge = segment_draw.hover is not None and segment_draw.hover[2] in ('START', 'END')
            segment_draw.hover = new
            is_edge = new is not None and new[2] in ('START', 'END')
            if is_edge != was_edge:
                context.window.cursor_set('MOVE_X' if is_edge else 'DEFAULT')
            context.region.tag_redraw()
        return {'PASS_THROUGH'}


class RTGTR_OT_SegmentClick(Operator):
    """Select a prompt segment and drag it or its boundaries; its menu with the other mouse button"""
    bl_idname = "retargetor.segment_click"
    bl_label = "Move Prompt Segment"
    bl_options = {'REGISTER', 'UNDO'}

    button: StringProperty(name="Button", default='LEFT', options={'SKIP_SAVE', 'HIDDEN'})

    def invoke(self, context, event):
        hit = under_mouse(context, event)
        if hit is None:
            return {'PASS_THROUGH'}
        rig, index, part = hit
        if self.button != select_mouse(context):
            if index is None:
                return {'PASS_THROUGH'}
            _select(context, rig, index)
            bpy.ops.wm.call_menu(name=RTGTR_MT_SegmentMenu.bl_idname)
            return {'FINISHED'}
        if part == 'TAG':
            _select(context, rig)
            return {'FINISHED'}
        if not rig.is_editable:
            _select(context, rig, index)
            self.report({'WARNING'}, f"'{rig.name}' is linked: its segments can't be edited")
            return {'FINISHED'}
        if part == 'ADD':
            _select(context, rig)
            bpy.ops.retargetor.segment_add()
            return {'FINISHED'}
        _select(context, rig, index)
        self.rig_name = rig.name
        self.index, self.part = index, part
        self.original = segment_track.read_track(rig.retargetor)
        self.start_x = event.mouse_region_x
        self.start_frame = context.region.view2d.region_to_view(event.mouse_region_x, 0)[0]
        self.dragging = False
        self.limits = segment_track.length_limits(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _apply(self, context, event):
        frame = context.region.view2d.region_to_view(event.mouse_region_x, 0)[0]
        delta = round(frame - self.start_frame)
        min_frames, max_frames = self.limits
        if self.part == 'BODY':
            track = core_segments.move_segment(self.original, self.index, delta, min_frames, max_frames)
        else:
            boundary = self.index if self.part == 'START' else self.index + 1
            current = (self.original[boundary].start_frame if boundary < len(self.original)
                       else self.original[-1].end_frame + 1)
            track = core_segments.move_boundary(self.original, boundary, current + delta, min_frames, max_frames)
        rig = bpy.data.objects.get(self.rig_name)
        segment_track.write_track(rig.retargetor, track)
        segment = track[self.index]
        context.area.header_text_set(f"Segment {self.index + 1}: frames {segment.start_frame}-{segment.end_frame} "
                                     f"({segment.frame_count} frames)")

    def _end(self, context):
        context.area.header_text_set(None)
        context.window.cursor_modal_restore()

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            if not self.dragging and abs(event.mouse_region_x - self.start_x) >= DRAG_THRESHOLD:
                self.dragging = True
                context.window.cursor_modal_set('MOVE_X')
            if self.dragging:
                self._apply(context, event)
            return {'RUNNING_MODAL'}
        if event.type == 'ESC' or (event.type in {'LEFTMOUSE', 'RIGHTMOUSE'} and event.value == 'PRESS'):
            rig = bpy.data.objects.get(self.rig_name)
            if rig is not None:
                segment_track.write_track(rig.retargetor, self.original)
            self._end(context)
            return {'CANCELLED'}
        if event.type in {'LEFTMOUSE', 'RIGHTMOUSE'} and event.value == 'RELEASE':
            self._end(context)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class RTGTR_OT_SegmentEdit(Operator):
    """Edit a prompt segment in a popup: prompt, seed and frames"""
    bl_idname = "retargetor.segment_edit"
    bl_label = "Edit Prompt Segment"
    bl_options = {'REGISTER', 'UNDO'}

    character: StringProperty(name="Character", options={'SKIP_SAVE', 'HIDDEN'})
    index: IntProperty(name="Segment", default=-1, options={'SKIP_SAVE', 'HIDDEN'})

    def _item(self):
        rig = bpy.data.objects.get(self.character)
        if rig is None or not 0 <= self.index < len(rig.retargetor.segments):
            return None, None
        return rig, rig.retargetor.segments[self.index]

    def invoke(self, context, event):
        if not self.character:
            if event is not None and event.type != 'NONE':
                hit = under_mouse(context, event)
                if hit is None or hit[1] is None:
                    return {'PASS_THROUGH'}
                rig, index, _part = hit
            else:
                rig = context.scene.retargetor_target
                index = rig.retargetor.segments_active_index if rig is not None else -1
            if rig is None:
                return {'CANCELLED'}
            self.character, self.index = rig.name, index
            _select(context, rig, index)
        if self._item()[1] is None:
            return {'CANCELLED'}
        return context.window_manager.invoke_popup(self, width=400)

    def draw(self, context):
        from .preferences import active_backend
        rig, item = self._item()
        layout = self.layout
        if item is None:
            layout.label(text="No segment")
            return
        layout.label(text=f"{rig.name}: segment {self.index + 1} / {len(rig.retargetor.segments)}",
                     icon='SEQ_STRIP_META')
        caps = active_backend(context).capabilities
        layout.enabled = rig.is_editable
        layout.prop(item, "prompt", text="")
        row = layout.row(align=True)
        row.prop(item, "frame_start")
        row.prop(item, "frame_end")
        if caps.seed:
            layout.prop(item, "seed")
        if rig == context.scene.retargetor_target:
            layout.operator_context = 'INVOKE_DEFAULT'
            layout.operator("retargetor.regenerate_segment", text=segment_track.generate_verb(item),
                            icon='FILE_REFRESH').index = self.index

    def execute(self, context):
        return {'FINISHED'}


class RTGTR_MT_SegmentMenu(Menu):
    """What can be done on the active prompt segment"""
    bl_idname = "RTGTR_MT_segment_menu"
    bl_label = "Prompt Segment"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        rig = context.scene.retargetor_target
        index = rig.retargetor.segments_active_index if rig is not None else 0
        props = layout.operator("retargetor.segment_edit", text="Edit...", icon='GREASEPENCIL')
        if rig is not None:
            props.character, props.index = rig.name, index
        layout.operator("retargetor.segment_split", icon='MOD_EDGESPLIT')
        layout.operator("retargetor.segment_add", icon='ADD')
        layout.operator("retargetor.segment_remove", icon='REMOVE')
        layout.separator()
        item = rig.retargetor.segments[index] if rig is not None and index < len(rig.retargetor.segments) else None
        props = layout.operator("retargetor.regenerate_segment", text=f"{segment_track.generate_verb(item)} Segment",
                                icon='FILE_REFRESH')
        props.index = index
        layout.operator("retargetor.generate_inbetweens", text="Generate Whole Track", icon='ANIM')


classes = (
    RTGTR_OT_SegmentHover,
    RTGTR_OT_SegmentClick,
    RTGTR_OT_SegmentEdit,
    RTGTR_MT_SegmentMenu,
)

# Keymaps of the editors showing the bands: (keymap name, space type)
KEYMAPS = (("Dopesheet", 'DOPESHEET_EDITOR'), ("Graph Editor", 'GRAPH_EDITOR'))
_keymap_items = []


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:  # background mode
        return
    for name, space_type in KEYMAPS:
        keymap = keyconfig.keymaps.new(name=name, space_type=space_type)
        for event_type, value, idname, props in (
                ('MOUSEMOVE', 'ANY', RTGTR_OT_SegmentHover.bl_idname, {}),
                ('LEFTMOUSE', 'DOUBLE_CLICK', RTGTR_OT_SegmentEdit.bl_idname, {}),
                ('LEFTMOUSE', 'PRESS', RTGTR_OT_SegmentClick.bl_idname, {"button": 'LEFT'}),
                ('RIGHTMOUSE', 'PRESS', RTGTR_OT_SegmentClick.bl_idname, {"button": 'RIGHT'})):
            item = keymap.keymap_items.new(idname, event_type, value)
            for prop, prop_value in props.items():
                setattr(item.properties, prop, prop_value)
            _keymap_items.append((keymap, item))


def unregister():
    for keymap, item in _keymap_items:
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass
    _keymap_items.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
