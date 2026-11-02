# type: ignore
"""Operators generating the in-betweens, and starting / stopping the backend's model."""
import bpy
from bpy.types import Operator

from . import generation
from .backends import process, registry
from .preferences import active_backend, backend_settings
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


def _cancelled(operator, task):
    """A cancelled generation. If the rig was already changed (FK snap...), the operator still finishes, so the
    changes are one undo step of their own instead of being merged with the next one."""
    if task.modified:
        operator.report({'WARNING'}, "Generation cancelled; the changes made to the rig before it are kept "
                                     "(Ctrl+Z to undo them)")
        return {'FINISHED'}
    operator.report({'WARNING'}, "Generation cancelled")
    return {'CANCELLED'}


def _report_result(operator, task):
    frames, removed = task.result
    timings = ", ".join(f"{name} {seconds:.1f} s" for name, seconds in task.timings.items())
    operator.report({'INFO'}, f"{frames} frames generated on '{task.rig_name}' with {task.backend.label} "
                              f"(frames {task.start_frame}-{task.end_frame}, {len(task.key_frames)} key poses; "
                              f"{timings})")
    if task.errors:
        operator.report({'WARNING'}, "Some bones were skipped: " + "; ".join(sorted(task.errors)))


class RTGTR_OT_GenerateInbetweens(Operator):
    """Generate the character's motion with the active backend, from the first key pose to the last one, or on
    its custom range. Key poses are the frames where a control of the rig profile has a key that isn't
    Generated; the result is written as Generated keys, never on a key pose. Esc cancels"""
    bl_idname = "retargetor.generate_inbetweens"
    bl_label = "Generate In-betweens"
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None
    _task = None

    @classmethod
    def poll(cls, context):
        rig = _character(context)
        return rig is not None and generation.current_task is None and rig.is_editable

    def execute(self, context):
        """Blocking: used from scripts and tests (invoke runs the same steps without freezing Blender)"""
        rig = _character(context)
        task = generation.GenerationTask()
        try:
            if not task.run(context, rig):
                return _cancelled(self, task)
        except GENERATION_ERRORS as e:
            self.report({'ERROR'}, str(e.args[0]) if e.args else str(e))
            return {'CANCELLED'}
        _report_result(self, task)
        return {'FINISHED'}

    def invoke(self, context, event):
        rig = _character(context)
        task = generation.GenerationTask()
        try:
            task.start(context, rig)
        except GENERATION_ERRORS as e:
            self.report({'ERROR'}, str(e.args[0]) if e.args else str(e))
            return {'CANCELLED'}
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
            self.report({'ERROR'}, str(e.args[0]) if e.args else str(e))
            return {'CANCELLED'}
        if not finished:
            self._status(context)
            return {'PASS_THROUGH'}
        self._finish(context)
        if task.cancelled:
            return _cancelled(self, task)
        _report_result(self, task)
        return {'FINISHED'}


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


class RTGTR_OT_BackendStart(Operator):
    """Start the active backend and load its model, so the first generation doesn't wait for it"""
    bl_idname = "retargetor.backend_start"
    bl_label = "Start Model"

    def execute(self, context):
        backend = active_backend(context)
        try:
            worker = registry.worker_for(backend, backend_settings(context, backend))
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
    RTGTR_OT_RangeStartHere,
    RTGTR_OT_CancelGeneration,
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
