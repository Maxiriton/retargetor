# type: ignore
"""Operators generating the in-betweens, clearing them, and starting / stopping the backend's model."""
import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from . import generated_keys, generation
from .backends import process, registry
from .preferences import active_backend
from .properties import get_character

GENERATION_ERRORS = (ValueError, KeyError, generation.GenerationError, process.WorkerError)
# Events still handled by Blender while the keys are written: looking around, nothing that edits
NAVIGATION_EVENTS = {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                     'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE', 'MOUSESMARTZOOM', 'NDOF_MOTION', 'TIMER'}


def tag_redraw(context=None):
    window_manager = (context or bpy.context).window_manager
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type in ('VIEW_3D', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'TIMELINE'):
                area.tag_redraw()


def _pump_timer():
    """Handles the workers' messages while one of them is busy (model loading from the panel...)"""
    if registry.pump_all():
        tag_redraw()
    return 0.2 if registry.any_busy() else None


def ensure_pump_timer():
    if not bpy.app.timers.is_registered(_pump_timer):
        bpy.app.timers.register(_pump_timer, first_interval=0.1)


def _character(context):
    rig, _state = get_character(context)
    return rig


def _cancelled(operator, task, context):
    """A cancelled generation. If the rig was already changed (FK snap...), the operator still finishes, so the
    changes are one undo step of their own instead of being merged with the next one."""
    task.abandon(context)
    if task.modified:
        operator.report({'WARNING'}, "Generation cancelled; the changes made to the rig before it are kept "
                                     "(Ctrl+Z to undo them)")
        return {'FINISHED'}
    operator.report({'WARNING'}, "Generation cancelled")
    return {'CANCELLED'}


def _failed(operator, task, error, context):
    """An error. If the rig was already changed (FK snap...), the operator still finishes: one undo step."""
    task.abandon(context)
    operator.report({'ERROR'}, str(error.args[0]) if error.args else str(error))
    if task.modified:
        operator.report({'WARNING'}, "The changes made to the rig before the error are kept (Ctrl+Z to undo them)")
        return {'FINISHED'}
    return {'CANCELLED'}


def _report_result(operator, task):
    frames, removed = task.result
    timings = ", ".join(f"{name} {seconds:.1f} s" for name, seconds in task.timings.items())
    what = f"segment {task.segment_index + 1}, " if task.segment_index is not None else ""
    operator.report({'INFO'}, f"{frames} frames generated on '{task.rig_name}' with {task.backend.label} "
                              f"({what}frames {task.start_frame}-{task.end_frame}, {len(task.key_frames)} key poses; "
                              f"{timings})")
    for note in task.notes:
        operator.report({'INFO'}, note)
    if task.errors:
        operator.report({'WARNING'}, "Some bones were skipped: " + "; ".join(sorted(task.errors)))


class GenerateBase:
    """Runs a GenerationTask: blocking from execute, step by step from invoke (a modal operator following it from a
    timer). Subclasses say which prompt segment (_segment)."""
    _timer = None
    _task = None

    @classmethod
    def poll(cls, context):
        rig = _character(context)
        return rig is not None and generation.current_task is None and rig.is_editable

    def _segment(self, context):
        """Index of the prompt segment to regenerate alone, or None for the whole generation"""
        raise NotImplementedError

    def execute(self, context):
        """Blocking: used from scripts and tests (invoke runs the same steps without freezing Blender)"""
        rig = _character(context)
        task = generation.GenerationTask()
        try:
            if not task.run(context, rig, segment=self._segment(context)):
                return _cancelled(self, task, context)
        except GENERATION_ERRORS as e:
            return _failed(self, task, e, context)
        _report_result(self, task)
        return {'FINISHED'}

    def invoke(self, context, event):
        rig = _character(context)
        task = generation.GenerationTask()
        try:
            task.start(context, rig, self._segment(context))
        except GENERATION_ERRORS as e:
            return _failed(self, task, e, context)
        self._task = task
        generation.current_task = task
        window_manager = context.window_manager
        self._timer = window_manager.event_timer_add(0.05, window=context.window)
        window_manager.modal_handler_add(self)
        self._status(context)
        return {'RUNNING_MODAL'}

    def _status(self, context, note=""):
        task = self._task
        note = note or ("Esc to cancel" if task.cancellable else "can't be cancelled")
        context.workspace.status_text_set(
            f"{task.backend.label}: {task.message} {task.fraction * 100:.0f}%  ({note})")
        tag_redraw(context)

    def _finish(self, context):
        context.window_manager.event_timer_remove(self._timer)
        context.workspace.status_text_set(None)
        generation.current_task = None
        tag_redraw(context)

    def modal(self, context, event):
        task = self._task
        if event.type == 'ESC' or task.cancel_requested:
            task.cancel_requested = False
            if task.cancellable:
                task.cancel()
            else:
                self._status(context, "writing the keys can't be cancelled")
        if event.type != 'TIMER':
            # While the keys are written, nothing may edit the rig or undo (the keys belong to this undo step)
            if task.stage == generation.WRITING and event.type not in NAVIGATION_EVENTS:
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}
        try:
            finished = task.update(context)
        except GENERATION_ERRORS as e:
            self._finish(context)
            return _failed(self, task, e, context)
        if not finished:
            self._status(context)
            return {'PASS_THROUGH'}
        self._finish(context)
        if task.cancelled:
            return _cancelled(self, task, context)
        _report_result(self, task)
        return {'FINISHED'}


class RTGTR_OT_GenerateInbetweens(GenerateBase, Operator):
    """Generate the character's motion with the active backend: its whole track of prompt segments, or without
    segments its prompt from the first key pose to the last one or on its custom range (it becomes prompt segment 1). Key poses are the frames where a control of the rig
    profile has a key that isn't Generated; the result is written as Generated keys, never on a key pose. Esc
    cancels"""
    bl_idname = "retargetor.generate_inbetweens"
    bl_label = "Generate"
    bl_options = {'REGISTER', 'UNDO'}

    def _segment(self, context):
        return None


class RTGTR_OT_RegenerateSegment(GenerateBase, Operator):
    """Regenerate one prompt segment of the character, the rest of its track left as it is. With a backend that
    continues the motion around it, the segment joins its neighbours already generated without a jump (the
    transition is the model's). Only the segment's frames get new Generated keys. Esc cancels"""
    bl_idname = "retargetor.regenerate_segment"
    bl_label = "Regenerate Segment"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="Segment", description="Index of the segment (-1: the active one)", default=-1,
                       options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        rig = _character(context)
        if rig is None or generation.current_task is not None or not rig.is_editable:
            return False
        if len(rig.retargetor.segments) == 0:
            cls.poll_message_set("The character has no prompt segment")
            return False
        return True

    def _segment(self, context):
        state = _character(context).retargetor
        return state.segments_active_index if self.index < 0 else self.index


class RTGTR_OT_RangeStartHere(Operator):
    """Start the character's custom range on the current frame"""
    bl_idname = "retargetor.range_start_here"
    bl_label = "Start Here"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig = _character(context)
        return rig is not None and rig.is_editable

    def execute(self, context):
        _character(context).retargetor.range_start = context.scene.frame_current
        return {'FINISHED'}


class RTGTR_OT_CancelGeneration(Operator):
    """Cancel the running generation"""
    bl_idname = "retargetor.cancel_generation"
    bl_label = "Cancel"

    @classmethod
    def poll(cls, context):
        return generation.current_task is not None and generation.current_task.cancellable

    def execute(self, context):
        task = generation.current_task
        task.cancel_requested = True
        task.cancel()
        return {'FINISHED'}


class RTGTR_OT_ClearGeneratedKeys(Operator):
    """Remove the keys the add-on made on the character: its Generated keys, and the keys it made on the key poses
    (FK controls snapped to the IK pose, IK controls, IK/FK switch) unless you changed them since. Your own keys
    stay. Controls left without any key go back to their rest pose"""
    bl_idname = "retargetor.clear_generated_keys"
    bl_label = "Clear Generated Keys"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig = _character(context)
        return (rig is not None and generation.current_task is None and rig.is_editable
                and rig.animation_data is not None and rig.animation_data.action is not None)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        rig = _character(context)
        with generated_keys.suspended():
            removed_generated, removed_added, kept, reset = generated_keys.clear(rig)
            rig.update_tag()
            context.view_layer.update()
        if not (removed_generated or removed_added):
            self.report({'INFO'}, f"No key made by the add-on on '{rig.name}'")
            return {'CANCELLED'}
        message = (f"Removed {removed_generated} Generated keys and {removed_added} keys made on the key poses "
                   f"from '{rig.name}'")
        if reset:
            message += f"; {reset} channels left without keys put back to rest"
        self.report({'INFO'}, message)
        if kept:
            self.report({'INFO'}, f"{kept} key{'s' if kept > 1 else ''} made by the add-on kept: you changed "
                                  f"{'them' if kept > 1 else 'it'}")
        tag_redraw(context)
        return {'FINISHED'}


class RTGTR_OT_BackendStart(Operator):
    """Start the active backend and load its model, so the first generation doesn't wait for it"""
    bl_idname = "retargetor.backend_start"
    bl_label = "Start Model"

    def execute(self, context):
        backend = active_backend(context)
        try:
            from . import model_setup
            worker = model_setup.worker_for(context, backend)
            worker.submit("load")
        except GENERATION_ERRORS as e:
            self.report({'ERROR'}, str(e.args[0]) if e.args else str(e))
            return {'CANCELLED'}
        ensure_pump_timer()
        return {'FINISHED'}


class RTGTR_OT_BackendStop(Operator):
    """Stop the active backend's worker and free its memory"""
    bl_idname = "retargetor.backend_stop"
    bl_label = "Stop Model"

    @classmethod
    def poll(cls, context):
        worker = registry.existing_worker(active_backend(context).id)
        return worker is not None and worker.alive and generation.current_task is None

    def execute(self, context):
        registry.stop(active_backend(context).id)
        tag_redraw(context)
        return {'FINISHED'}


classes = (
    RTGTR_OT_GenerateInbetweens,
    RTGTR_OT_RegenerateSegment,
    RTGTR_OT_RangeStartHere,
    RTGTR_OT_CancelGeneration,
    RTGTR_OT_ClearGeneratedKeys,
    RTGTR_OT_BackendStart,
    RTGTR_OT_BackendStop,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    if bpy.app.timers.is_registered(_pump_timer):
        bpy.app.timers.unregister(_pump_timer)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
