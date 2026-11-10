# type: ignore
"""The models' setup, Blender side: each backend's environment, its install and check, the Models section of the
preferences. The work itself is in backends/setup (no bpy); here are the operators, the timer that follows the
installs and checks, and the drawing.

A backend with something to install (Backend.installable) runs from an environment installed by the add-on in the
models' folder, or from an existing one (its Python set in the preferences). Nothing outside backends/ names a model.
"""
import os
import shutil
import textwrap
import threading
import time

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from .backends import process, registry
from .backends.setup import checks, installer, machine as machine_info, paths, signin
from .backends.setup import weights as weights_status
from .preferences import ADDON_ID, active_backend, backend_settings, get_preferences, setup_settings

# backend id -> Installer (kept once finished, for its result)
installers = {}
# backend id -> CheckRun (the last check)
check_runs = {}
_timer_running = False


def machine():
    return machine_info.detect()


# Where things are

def models_root(context):
    prefs = get_preferences(context)
    folder = bpy.path.abspath(prefs.models_folder) if prefs is not None and prefs.models_folder else ""
    return os.path.normpath(folder) if folder else paths.default_root(machine().system)


def is_managed(context, backend):
    setup = setup_settings(context, backend)
    return setup is None or setup.environment == 'MANAGED'


def existing_python(context, backend):
    setup = setup_settings(context, backend)
    return os.path.normpath(bpy.path.abspath(setup.python)) if setup is not None and setup.python else ""


def layout_for(context, backend):
    """The backend's paths.Layout: in the models' folder, its weights next to an existing environment if it has one"""
    root = models_root(context)
    system = machine().system
    if is_managed(context, backend):
        return paths.Layout(root, backend.id, system)
    python = existing_python(context, backend)
    weights_root = (paths.env_root(python) or os.path.dirname(os.path.dirname(python))) if python else None
    return paths.Layout(root, backend.id, system, weights_root=weights_root)


def environment_python(context, backend):
    return layout_for(context, backend).python if is_managed(context, backend) else existing_python(context, backend)


def requirements_for(context, backend):
    return backend.requirements(machine(), backend_settings(context, backend))


def installing(backend):
    current = installers.get(backend.id)
    return current is not None and current.active


def worker_for(context, backend):
    """The backend's worker (backends.registry.worker_for) with its environment.
    Raises ValueError saying what is missing (not installed, Python not found...)."""
    settings = backend_settings(context, backend)
    if not backend.installable:
        return registry.worker_for(backend, None, settings, None)
    layout = layout_for(context, backend)
    python = environment_python(context, backend)
    if is_managed(context, backend):
        if installing(backend):
            raise ValueError(f"{backend.label} is still being installed (Preferences > Add-ons > Models).")
        if not installer.is_complete(layout):
            raise ValueError(f"{backend.label} isn't installed: install it in the add-on's preferences (Models).")
    elif not python:
        raise ValueError(f"Set the Python executable of the {backend.label} environment in the add-on's "
                         f"preferences (Models).")
    elif not os.path.isfile(python):
        raise ValueError(f"The {backend.label} Python executable doesn't exist: {python}")
    return registry.worker_for(backend, python, settings, layout)


# State, for the panels and headers (cheap: read on every redraw)

_status_cache = {}


def setup_problem(context, backend):
    """Why the backend can't run yet ("" if it can, as far as the files tell): for the headers and panels"""
    if not backend.installable:
        return ""
    if installing(backend):
        return "Installing"
    key = (backend.id, is_managed(context, backend), environment_python(context, backend))
    cached = _status_cache.get(key)
    now = time.perf_counter()
    if cached is not None and now - cached[0] < 2.0:
        return cached[1]
    if is_managed(context, backend):
        state = installer.read_state(layout_for(context, backend))
        if state is None:
            problem = "Not installed"
        elif not state.get("complete") or not os.path.isfile(environment_python(context, backend)):
            problem = "Install incomplete"
        else:
            problem = ""
    else:
        python = existing_python(context, backend)
        problem = "" if python and os.path.isfile(python) else "Python not found"
    run = check_runs.get(backend.id)
    if (not problem and run is not None and not run.running and run.python == key[2] and run.items
            and not checks.ready(run.items)):
        problem = "Setup problem"
    _status_cache[key] = (now, problem)
    return problem


def _forget_status(backend_id=None):
    for key in list(_status_cache):
        if backend_id is None or key[0] == backend_id:
            del _status_cache[key]


class CheckRun:
    """A setup check running in a thread (it imports the model's packages: a few seconds)"""

    def __init__(self, backend, requirements, layout, python, managed, access):
        self.backend_id = backend.id
        # The environment checked: a result is only shown for it
        self.python = python
        self.items = []
        self.error = ""
        self.running = True
        self.started = time.time()
        self._thread = threading.Thread(target=self._run, args=(requirements, layout, python, managed, access),
                                        daemon=True)
        self._thread.start()

    def _run(self, requirements, layout, python, managed, access):
        report, error = None, ""
        try:
            if python and os.path.isfile(python):
                report = checks.run_env_check(python, requirements, access=access)
        except checks.CheckError as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001 - shown in the preferences
            error = f"{type(e).__name__}: {e}"
        try:
            self.items = checks.evaluate(requirements, machine(), layout, python, managed, report, error)
        except Exception as e:  # noqa: BLE001
            self.items = [checks.CheckItem("check", "Check", checks.ERROR, f"The check failed: {e}")]
        self.running = False

    def wait(self, timeout=None):
        self._thread.join(timeout)
        return self


def start_check(context, backend, online=False):
    """Start the backend's setup check. online: also ask Hugging Face whether gated weights are accessible."""
    requirements = requirements_for(context, backend)
    layout = layout_for(context, backend)
    access = []
    if online and bpy.app.online_access:
        access = [w.repo_id for w in requirements.weights
                  if w.gated and not weights_status.status(w, layout).present]
    run = CheckRun(backend, requirements, layout, environment_python(context, backend),
                   is_managed(context, backend), access)
    check_runs[backend.id] = run
    _forget_status(backend.id)
    ensure_timer()
    return run


def start_install(context, backend, repair=False):
    if installing(backend):
        raise ValueError(f"{backend.label} is being installed already.")
    requirements = requirements_for(context, backend)
    current = installer.Installer(backend.id, backend.label, requirements, layout_for(context, backend), machine(),
                                  repair=repair)
    registry.stop(backend.id)
    installers[backend.id] = current.start()
    check_runs.pop(backend.id, None)
    _forget_status(backend.id)
    ensure_timer()
    return current


# Timer: follows the installs and checks, redraws the preferences and the animation editors

def _redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in ('PREFERENCES', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'VIEW_3D'):
                area.tag_redraw()


_finished_seen = set()


def _tick():
    global _timer_running
    busy = False
    for backend_id, current in list(installers.items()):
        if current.active:
            busy = True
        elif id(current) not in _finished_seen:
            _finished_seen.add(id(current))
            _forget_status(backend_id)
            if current.state == installer.DONE:
                try:
                    start_check(bpy.context, registry.get(backend_id))
                    busy = True
                except (KeyError, ValueError):
                    pass
    if any(run.running for run in check_runs.values()):
        busy = True
    else:
        _forget_status()
    try:
        _redraw()
    except (AttributeError, ReferenceError):
        pass
    if not busy:
        _timer_running = False
        return None
    return 0.5


def ensure_timer():
    global _timer_running
    if not _timer_running:
        _timer_running = True
        bpy.app.timers.register(_tick, first_interval=0.2)


# Operators

def _backend(backend_id):
    try:
        return registry.get(backend_id)
    except KeyError:
        return None


def _gb(value):
    return f"{value:.1f} GB" if value >= 0.95 else f"{value * 1000:.0f} MB"


def wrap(text, width=96):
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        lines += textwrap.wrap(paragraph, width) or [""]
    return lines


class RTGTR_OT_ModelInstall(Operator):
    """Install the model: its Python environment, its packages and its weights (downloaded)"""
    bl_idname = "retargetor.model_install"
    bl_label = "Install Model"

    backend_id: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    repair: BoolProperty(name="Repair", default=False, options={'SKIP_SAVE'},
                         description="Make a new environment, install every package again and complete the weights")

    @classmethod
    def description(cls, _context, properties):
        if properties.repair:
            return "Repair the install: a new environment, every package installed again, the weights completed"
        return cls.__doc__

    def invoke(self, context, _event):
        backend = _backend(self.backend_id)
        if backend is None:
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=560, title=f"Install {backend.label}",
                                                          confirm_text="Repair" if self.repair else "Install")

    def draw(self, context):
        backend = _backend(self.backend_id)
        requirements = requirements_for(context, backend)
        layout_ = layout_for(context, backend)
        col = self.layout.column(align=True)
        col.label(text=f"Into {layout_.backend_dir}", icon='FILE_FOLDER')
        col.label(text=f"Python {requirements.python} and its packages: about {_gb(requirements.disk_gb)}",
                  icon='SCRIPTPLUGINS')
        for weights in requirements.weights:
            present = weights_status.status(weights, layout_).present
            where = layout_.weights_dir(weights) and "with the model" or "Hugging Face cache"
            text = f"{weights.label}: {_gb(weights.size_gb)} ({where})" + (", already there" if present else "")
            col.label(text=text, icon='CHECKMARK' if present else 'IMPORT')
            if weights.gated and not present:
                col.label(text="    Needs your Hugging Face access (requested on its page, then Sign In)",
                          icon='LOCKED')
        col.separator()
        for note in requirements.notes:
            for line in wrap(note, 100):
                col.label(text=line)
        for label, _url in requirements.licences:
            col.label(text=label, icon='INFO')
        col.label(text="By installing, you accept these licences.")

    def execute(self, context):
        backend = _backend(self.backend_id)
        if backend is None or not backend.installable:
            self.report({'ERROR'}, f"Nothing to install for '{self.backend_id}'.")
            return {'CANCELLED'}
        if not bpy.app.online_access:
            self.report({'ERROR'}, "Installing a model downloads it: allow online access in Preferences > System "
                                   "> Network.")
            return {'CANCELLED'}
        if not is_managed(context, backend):
            self.report({'ERROR'}, f"{backend.label} uses an existing environment: choose 'Installed by the "
                                   f"Add-on' to install it.")
            return {'CANCELLED'}
        try:
            start_install(context, backend, repair=self.repair)
        except (ValueError, OSError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class RTGTR_OT_ModelCancelInstall(Operator):
    """Stop the install; it resumes where it stopped next time"""
    bl_idname = "retargetor.model_cancel_install"
    bl_label = "Cancel Install"

    backend_id: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, _context):
        current = installers.get(self.backend_id)
        if current is not None and current.active:
            current.cancel()
        return {'FINISHED'}


class RTGTR_OT_ModelCheck(Operator):
    """Check the model's setup: its environment, packages, GPU and weights"""
    bl_idname = "retargetor.model_check"
    bl_label = "Check Setup"

    backend_id: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    online: BoolProperty(default=True, options={'SKIP_SAVE'},
                         description="Also ask Hugging Face whether your account may download gated weights")

    def execute(self, context):
        backend = _backend(self.backend_id)
        if backend is None or not backend.installable:
            return {'CANCELLED'}
        start_check(context, backend, online=self.online)
        return {'FINISHED'}


def _repos_needed_elsewhere(context, backend):
    """Repositories in the Hugging Face cache needed by another installed backend"""
    needed = set()
    for other in registry.BACKENDS:
        if other is backend or not other.installable:
            continue
        other_layout = layout_for(context, other)
        if is_managed(context, other) and not other_layout.is_own_folder():
            continue
        for weights in requirements_for(context, other).weights:
            if not weights.folder:
                needed.add(weights.repo_id)
    return needed


def removable_cache_weights(context, backend):
    """The backend's weights in the Hugging Face cache that no other installed backend needs"""
    needed = _repos_needed_elsewhere(context, backend)
    found = []
    for weights in requirements_for(context, backend).weights:
        if weights.folder or weights.repo_id in needed:
            continue
        folder = paths.hf_repo_dir(weights.repo_id, paths.hf_cache_dir())
        if os.path.isdir(folder):
            found.append((weights, folder))
    return found


class RTGTR_OT_ModelRemove(Operator):
    """Delete the model's environment and the weights installed with it"""
    bl_idname = "retargetor.model_remove"
    bl_label = "Remove Model"

    backend_id: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    weights: BoolProperty(name="Also Delete Its Weights From the Hugging Face Cache", default=False,
                          options={'SKIP_SAVE'},
                          description="Weights another installed model needs are kept")

    def invoke(self, context, _event):
        backend = _backend(self.backend_id)
        if backend is None:
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=520, title=f"Remove {backend.label}",
                                                          confirm_text="Delete")

    def draw(self, context):
        backend = _backend(self.backend_id)
        col = self.layout.column(align=True)
        col.label(text="Deleted for good (it can't be undone):", icon='ERROR')
        col.label(text=layout_for(context, backend).backend_dir, icon='FILE_FOLDER')
        col.label(text="(the environment, its packages, the weights installed with it, the log)")
        cache = removable_cache_weights(context, backend)
        if cache:
            col.separator()
            col.prop(self, "weights")
            for weights, _folder in cache:
                col.label(text=f"    {weights.repo_id} ({_gb(weights.size_gb)})")
        kept = sorted(_repos_needed_elsewhere(context, backend) &
                      {w.repo_id for w in requirements_for(context, backend).weights})
        for repo in kept:
            col.label(text=f"Kept: {repo} (another model needs it)", icon='INFO')

    def execute(self, context):
        backend = _backend(self.backend_id)
        if backend is None or not backend.installable:
            return {'CANCELLED'}
        if installing(backend):
            self.report({'ERROR'}, f"{backend.label} is being installed: cancel the install first.")
            return {'CANCELLED'}
        if not is_managed(context, backend):
            self.report({'ERROR'}, "An existing environment isn't removed by the add-on.")
            return {'CANCELLED'}
        cache = removable_cache_weights(context, backend) if self.weights else []
        registry.stop(backend.id)
        try:
            installer.remove(layout_for(context, backend))
            for _weights, folder in cache:
                shutil.rmtree(folder)
        except (OSError, ValueError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        installers.pop(backend.id, None)
        check_runs.pop(backend.id, None)
        _forget_status(backend.id)
        removed = f" and {len(cache)} weights from the Hugging Face cache" if cache else ""
        self.report({'INFO'}, f"{backend.label} removed{removed}.")
        return {'FINISHED'}


class RTGTR_OT_ModelSignIn(Operator):
    """Sign in to Hugging Face, for gated weights: opens a terminal running Hugging Face's own sign-in (from the
    browser, or with a token you paste there). The add-on never sees the token"""
    bl_idname = "retargetor.model_sign_in"
    bl_label = "Sign In to Hugging Face"

    backend_id: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        backend = _backend(self.backend_id)
        if backend is None:
            return {'CANCELLED'}
        python = environment_python(context, backend)
        if not python or not os.path.isfile(python):
            self.report({'ERROR'}, f"Install {backend.label} first: its environment holds Hugging Face's sign-in.")
            return {'CANCELLED'}
        if signin.open_terminal(python, machine().system):
            self.report({'INFO'}, "Sign in in the terminal window, then install again.")
        else:
            command = signin.command_line(python)
            context.window_manager.clipboard = command
            self.report({'WARNING'}, f"No terminal found: run this command in one (copied): {command}")
        return {'FINISHED'}


class RTGTR_OT_ModelUse(Operator):
    """Make this model the one generating the motion"""
    bl_idname = "retargetor.model_use"
    bl_label = "Use This Model"

    backend_id: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        prefs = get_preferences(context)
        if prefs is None or _backend(self.backend_id) is None:
            return {'CANCELLED'}
        prefs.backend = self.backend_id
        return {'FINISHED'}


class RTGTR_OT_ModelOpenFolder(Operator):
    """Open the model's folder, or its install log"""
    bl_idname = "retargetor.model_open_folder"
    bl_label = "Open Folder"

    backend_id: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    log: BoolProperty(default=False, options={'SKIP_SAVE'})

    def execute(self, context):
        backend = _backend(self.backend_id)
        if backend is None:
            return {'CANCELLED'}
        layout_ = layout_for(context, backend)
        path = layout_.log_file if self.log else layout_.backend_dir
        if not os.path.exists(path):
            self.report({'ERROR'}, f"Nothing there yet: {path}")
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=path)
        return {'FINISHED'}


# Drawing

_LEVEL_ICONS = {checks.OK: 'CHECKMARK', checks.WARNING: 'ERROR', checks.ERROR: 'CANCEL'}


def capabilities_text(backend):
    caps = backend.capabilities
    parts = []
    if caps.prompt:
        parts.append("text prompt")
    if caps.seed:
        parts.append("seed")
    parts.append(f"{caps.min_key_poses}+ key poses")
    if caps.partial_poses:
        parts.append("partial poses")
    if caps.prompt_segments:
        parts.append("prompt segments")
    if caps.motion_context:
        parts.append("segment regeneration")
    parts.append(f"up to {caps.max_duration:g} s" + (" per segment" if caps.prompt_segments else "")
                 if caps.max_duration else "any length")
    if caps.native_fps:
        parts.append(f"{caps.native_fps:g} fps")
    if caps.streaming:
        parts.append("streaming")
    return ", ".join(parts)


def _fix_button(row, item, backend):
    if item.fix == checks.FIX_INSTALL:
        row.operator("retargetor.model_install", text="Install", icon='IMPORT').backend_id = backend.id
    elif item.fix == checks.FIX_REPAIR:
        props = row.operator("retargetor.model_install", text="Repair", icon='TOOL_SETTINGS')
        props.backend_id, props.repair = backend.id, True
    elif item.fix == checks.FIX_SIGN_IN:
        row.operator("wm.url_open", text="Request Access", icon='URL').url = item.url
        row.operator("retargetor.model_sign_in", text="Sign In", icon='USER').backend_id = backend.id
    elif item.fix == checks.FIX_URL and item.url:
        row.operator("wm.url_open", text="Open Page", icon='URL').url = item.url


def _draw_installer(col, backend, current):
    if current.active:
        number, total = current.step_number
        row = col.row(align=True)
        row.progress(factor=current.fraction, type='BAR',
                     text=f"{number}/{total} {current.message}  {current.fraction * 100:.0f}%")
        row.operator("retargetor.model_cancel_install", text="", icon='CANCEL').backend_id = backend.id
        if current.detail:
            col.label(text=current.detail[:110])
        return
    if current.state == installer.FAILED:
        box = col.box()
        for i, line in enumerate(wrap(current.error, 100)[:8]):
            box.label(text=line, icon='CANCEL' if i == 0 else 'BLANK1')
        problem = current.problem or {}
        if problem.get("gated"):
            row = box.row(align=True)
            row.operator("wm.url_open", text="Request Access", icon='URL').url = problem.get("url", "")
            row.operator("retargetor.model_sign_in", text="Sign In", icon='USER').backend_id = backend.id
        row = box.row(align=True)
        row.operator("retargetor.model_install", text="Resume Install", icon='IMPORT').backend_id = backend.id
        props = row.operator("retargetor.model_open_folder", text="Log", icon='TEXT')
        props.backend_id, props.log = backend.id, True
    elif current.state == installer.CANCELLED:
        col.label(text="Install cancelled: Install resumes it.", icon='INFO')


def _draw_checks(col, backend, run):
    if run.running:
        col.label(text="Checking the setup...", icon='SORTTIME')
        return
    for item in run.items:
        lines = wrap(f"{item.label}: {item.message}", 96)
        row = col.row(align=True)
        row.label(text=lines[0], icon=_LEVEL_ICONS.get(item.level, 'DOT'))
        if item.fix:
            _fix_button(row, item, backend)
        for line in lines[1:4]:
            col.label(text=line, icon='BLANK1')


def draw_worker(col, backend):
    from .ui import worker_status
    label, icon, start, stop, error = worker_status(backend)
    row = col.row(align=True)
    row.label(text=f"Model: {label}", icon=icon)
    if start:
        row.operator("retargetor.backend_start", text=start, icon='PLAY')
    if stop:
        row.operator("retargetor.backend_stop", text="Stop", icon='PAUSE')
    for line in wrap(error, 100)[:6] if error else []:
        col.label(text=line, icon='ERROR')


def draw_backend(layout, context, prefs, backend, active):
    box = layout.box()
    header = box.row(align=True)
    header.label(text=backend.label, icon='RADIOBUT_ON' if active else 'RADIOBUT_OFF')
    problem = setup_problem(context, backend)
    if backend.installable:
        header.label(text=problem or "Ready", icon='ERROR' if problem and problem != "Installing" else 'NONE')
    if not active:
        header.operator("retargetor.model_use", text="Use").backend_id = backend.id
    col = box.column(align=True)
    for line in wrap(backend.description, 100):
        col.label(text=line)
    for line in wrap("Supports: " + capabilities_text(backend), 100):
        col.label(text=line)

    settings = backend_settings(context, backend)
    if backend.installable:
        setup = setup_settings(context, backend)
        col = box.column()
        col.row().prop(setup, "environment", expand=True)
        managed = setup.environment == 'MANAGED'
        if not managed:
            col.prop(setup, "python")
        if settings is not None:
            backend.draw_settings(col, settings)
        current = installers.get(backend.id)
        if current is not None:
            _draw_installer(col, backend, current)
        row = box.row(align=True)
        if managed:
            complete = installer.is_complete(layout_for(context, backend))
            if not installing(backend):
                state = installer.read_state(layout_for(context, backend))
                if not complete:
                    text = "Resume Install" if state is not None else "Install"
                    row.operator("retargetor.model_install", text=text, icon='IMPORT').backend_id = backend.id
                else:
                    props = row.operator("retargetor.model_install", text="Repair", icon='TOOL_SETTINGS')
                    props.backend_id, props.repair = backend.id, True
        row.operator("retargetor.model_check", text="Check Setup", icon='VIEWZOOM').backend_id = backend.id
        if managed:
            props = row.operator("retargetor.model_open_folder", text="", icon='FILE_FOLDER')
            props.backend_id = backend.id
            props = row.operator("retargetor.model_open_folder", text="", icon='TEXT')
            props.backend_id, props.log = backend.id, True
            sub = row.row(align=True)
            sub.enabled = layout_for(context, backend).is_own_folder() and not installing(backend)
            sub.operator("retargetor.model_remove", text="", icon='TRASH').backend_id = backend.id
        if any(w.gated for w in requirements_for(context, backend).weights):
            row.operator("retargetor.model_sign_in", text="", icon='USER').backend_id = backend.id
        run = check_runs.get(backend.id)
        if run is not None and run.python == environment_python(context, backend):
            _draw_checks(box.column(align=True), backend, run)
    elif settings is not None:
        backend.draw_settings(box.column(), settings)
    if active:
        draw_worker(box.column(align=True), backend)


def draw_models(layout, context, prefs):
    layout.prop(prefs, "backend")
    col = layout.column(align=True)
    col.prop(prefs, "models_folder")
    if not prefs.models_folder:
        col.label(text=f"Default: {paths.default_root(machine().system)}", icon='FILE_FOLDER')
    gpu = machine().gpu
    col.label(text=f"GPU: {gpu.name}, {gpu.memory_mb / 1024:.0f} GB" if gpu is not None else "No NVIDIA GPU found",
              icon='DESKTOP')
    if not bpy.app.online_access:
        col.label(text="Online access is off (Preferences > System > Network): models can't be installed.",
                  icon='ERROR')
    current = active_backend(context)
    for backend in registry.visible(prefs.developer):
        draw_backend(layout, context, prefs, backend.configured(backend_settings(context, backend)),
                     backend.id == current.id)


classes = (
    RTGTR_OT_ModelInstall,
    RTGTR_OT_ModelCancelInstall,
    RTGTR_OT_ModelCheck,
    RTGTR_OT_ModelRemove,
    RTGTR_OT_ModelSignIn,
    RTGTR_OT_ModelUse,
    RTGTR_OT_ModelOpenFolder,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for current in installers.values():
        if current.active:
            current.cancel()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


__all__ = ["ADDON_ID", "draw_models", "environment_python", "layout_for", "setup_problem", "worker_for", "process"]
