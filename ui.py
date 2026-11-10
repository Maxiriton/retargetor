# type: ignore
import bpy
from bpy.types import Menu, Panel, UIList

from . import generation
from .backends import process, registry
from .preferences import active_backend, ADDON_ID
from .properties import get_character

class RETARGETOR_PT_RetargetPanel(Panel):
    bl_label = "Retarget"
    bl_idname = "RETARGETOR_PT_RetargetPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Retarget Tool'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="Setup", icon='SETTINGS')

        box = layout.box()
        box.prop(scene, "retargetor_target", text="Target")
        target_obj, state = get_character(context)
        if target_obj is None:
            if scene.retargetor_target is not None:
                layout.label(text=f"'{scene.retargetor_target.name}' isn't in the scene anymore", icon='ERROR')
            layout.label(text="Choose the armature that receives the animation")
            return

        box.prop(state, "source", text="Source")

        row = box.row(align=True)
        row.prop(state, "translation_scale", text="Translation Scale")
        row.operator("retargetor.auto_translation_scale", icon='FIXED_SIZE')

        if len(state.bones) == 0 :
            layout.label(text="Bone list is empty: build it or import a JSON")
            row = layout.row(align=True)
            s = row.split(factor=0.7)
            s.operator("retargetor.setup_bone_list")
            c = s.column()
            c.operator("retargetor.import_retarget_json")
        else:
            row = layout.row(align=True)
            s = row.split(factor=0.7)
            c = s.column()
            c.operator("retargetor.setup_bone_list", text="Rebuild bone list")
            c = s.column()
            c.operator("retargetor.import_retarget_json")
            layout.label(text="Bone list")
            layout.template_list(
                "RTGTR_UL_Bones", "bones",
                state, "bones",
                state, "bones_active_index"
            )
            layout.operator('retargetor.export_setup_to_json', text="Export to JSON")


        layout.separator()
        layout.label(text="Retarget", icon='ARMATURE_DATA')

        # Retarget and snap buttons
        layout.operator("retargetor.simple_retarget", icon='ANIM_DATA')
        layout.operator("retargetor.snap_selected_bone", icon='ANIM_DATA')
        layout.operator("retargetor.snap_full_pose", icon='ANIM_DATA')

class RTGTR_UL_Bones(UIList):
    """UI list for matching and setting up bones"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        row = layout.row(align=True)
        state = data

        if state.is_recording and state.bones_active_index != index:
            row.enabled = False

        split1 = row.split(factor=0.33, align=True)
        col1 = split1.column(align=True)

        # A check mark: both bones of the pair exist, so the rest offsets can be computed
        target_obj = context.scene.retargetor_target
        source_obj = state.source
        is_setup = bool(item.target_name) and source_obj is not None and target_obj is not None and \
            source_obj.data.bones.get(item.src_name) is not None and \
            target_obj.data.bones.get(item.target_name) is not None
        col1.label(text=item.src_name, icon='CHECKMARK' if is_setup else 'DECORATE')

        split2 = split1.split(factor=0.5, align=True)
        col2 = split2.column(align=True)

        if target_obj:
            col2.prop_search(
                item,
                "target_name",
                target_obj.pose,
                "bones",
                text=""
            )
        else:
            col2.label(text=item.target_name)

        col3 = split2.column(align=True)
        row2 = col3.row(align=True)
        row2.prop(item, "use_translation", text="", icon='CON_LOCLIKE', toggle=True)
        row2.prop(item, "offset_mode", text="")

        if state.is_recording and state.bones_active_index == index:
            row2.operator(
                "retargetor.finish_record",
                text="Finish Recording",
                icon='REC'
            )
        elif item.has_corrective_offset:
            row2.operator(
                "retargetor.record_adjustment",
                text="Update Record",
                icon='ARMATURE_DATA'
            )
            row2.operator(
                "retargetor.clear_record",
                text="",
                icon='X'
            )
        else:
            row2.operator(
                "retargetor.record_adjustment",
                text="Record Correction",
                icon='ARMATURE_DATA'
            )


class RETARGETOR_PT_RigProfilePanel(Panel):
    """Rig setup of the active armature: its bones for each humanoid role, and the check of what its controls do"""
    bl_label = "Rig Setup"
    bl_idname = "RETARGETOR_PT_RigProfilePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Retarget Tool'

    def draw(self, context):
        from . import rig_check
        from .core.roles import missing_required
        from .profile_operators import detect_profile, last_check, source_label
        layout = self.layout
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE':
            layout.label(text="Select the character's armature")
            return

        armature = obj.data
        profile = armature.retargetor_profile
        layout.label(text=armature.name, icon='ARMATURE_DATA')
        if not armature.is_editable:
            layout.label(text="Linked armature: set it up in its library file", icon='LIBRARY_DATA_DIRECT')

        if len(profile.roles) > 0:
            layout.label(text=f"Bones {source_label(profile.source)}", icon='PRESET')
            if len(profile.limbs) > 0:
                snapped = sum(1 for limb in profile.limbs if len(limb.ik_snap) > 0)
                layout.label(text=f"{len(profile.limbs)} IK/FK limbs: pose in IK or FK"
                                  + ("" if snapped == len(profile.limbs) else f" ({len(profile.limbs) - snapped} FK after generating)"),
                             icon='CON_KINEMATIC')
        else:
            detected = detect_profile(armature)
            if detected is not None:
                layout.label(text=f"Recognized: {source_label(detected[0])}", icon='PRESET')
                layout.label(text="Applied when the character is chosen or generates", icon='BLANK1')
            else:
                layout.label(text="Not set up: detect the bones, or assign them", icon='INFO')

        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("retargetor.profile_detect", icon='VIEWZOOM')
        row.operator("retargetor.check_rig", icon='CHECKMARK')
        row.menu("RTGTR_MT_ProfileFiles", text="", icon='DOWNARROW_HLT')

        problems = None
        try:
            problems = last_check(armature, profile.to_core()) if len(profile.roles) > 0 else None
        except ValueError:
            pass
        by_subject = {}
        if problems is not None:
            box = layout.box()
            errors = [p for p in problems if p.level == rig_check.ERROR]
            if not problems:
                box.label(text="Checked: the rig is ready", icon='CHECKMARK')
            else:
                title = f"{len(errors)} problem(s) to fix" if errors else f"Ready, {len(problems)} warning(s)"
                box.label(text=title, icon='ERROR' if errors else 'INFO')
                for problem in problems[:6]:
                    _wrapped(box, problem.message, 'CANCEL' if problem.level == rig_check.ERROR else 'DOT')
                if len(problems) > 6:
                    box.label(text=f"... and {len(problems) - 6} more", icon='BLANK1')
            for problem in problems:
                by_subject.setdefault(problem.subject, problem)

        if len(profile.roles) == 0:
            return
        layout.prop(profile, "use_controls")
        missing = set(missing_required([b.role for b in profile.roles if b.read_bone]))
        bindings = {b.role: b for b in profile.roles}
        for title, role_ids in _ROLE_GROUPS:
            box = layout.box()
            box.label(text=title)
            for role_id in role_ids:
                _draw_role(box, obj, profile, role_id, bindings.get(role_id), missing, by_subject)


def _wrapped(layout, text, icon, width=44):
    import textwrap
    for i, line in enumerate(textwrap.wrap(text, width)):
        layout.label(text=line, icon=icon if i == 0 else 'BLANK1')


_ROLE_GROUPS = (
    ("Spine and Head", ("hips", "spine", "chest", "upper_chest", "neck", "upper_neck", "head")),
    ("Left Arm", ("shoulder.L", "upper_arm.L", "forearm.L", "hand.L")),
    ("Right Arm", ("shoulder.R", "upper_arm.R", "forearm.R", "hand.R")),
    ("Left Leg", ("thigh.L", "shin.L", "foot.L", "toes.L")),
    ("Right Leg", ("thigh.R", "shin.R", "foot.R", "toes.R")),
)


def _draw_role(layout, obj, profile, role_id, binding, missing, by_subject):
    """One role: its status, its bone (and control), assign / select / clear"""
    from . import rig_check
    from .core.roles import get_role
    role = get_role(role_id)
    problem = by_subject.get(role_id)
    if binding is None or not binding.read_bone:
        icon = 'ERROR' if role_id in missing else 'RADIOBUT_OFF'
    elif problem is not None:
        icon = 'ERROR' if problem.level == rig_check.ERROR else 'INFO'
    else:
        icon = 'CHECKMARK'
    label = role.label.replace(" (L)", "").replace(" (R)", "")
    split = layout.split(factor=0.36, align=True)
    split.label(text=label, icon=icon)
    row = split.row(align=True)
    if binding is None:
        row.label(text="(optional)" if role_id not in missing else "missing")
    else:
        row.prop_search(binding, "read_bone", obj.pose, "bones", text="")
        if profile.use_controls:
            row.prop_search(binding, "write_bone", obj.pose, "bones", text="")
    sub = row.row(align=True)
    if profile.use_controls:
        op = sub.operator("retargetor.profile_assign", text="", icon='EYEDROPPER')
        op.role, op.which = role_id, 'READ'
        op = sub.operator("retargetor.profile_assign", text="", icon='BONE_DATA')
        op.role, op.which = role_id, 'WRITE'
    else:
        op = sub.operator("retargetor.profile_assign", text="", icon='EYEDROPPER')
        op.role, op.which = role_id, 'BOTH'
    if binding is not None:
        sub.operator("retargetor.profile_select_role", text="", icon='RESTRICT_SELECT_OFF').role = role_id
        sub.operator("retargetor.profile_clear_role", text="", icon='X').role = role_id


class RTGTR_MT_ProfileFiles(Menu):
    bl_label = "Rig Profile"

    def draw(self, context):
        layout = self.layout
        layout.operator("retargetor.profile_load_preset", icon='PRESET')
        layout.separator()
        layout.operator("retargetor.profile_import_json", icon='IMPORT')
        layout.operator("retargetor.profile_export_json", icon='EXPORT')
        layout.separator()
        layout.operator("retargetor.profile_add_roles", icon='ADD')


def _profile_panel_poll(context):
    obj = context.active_object
    return obj is not None and obj.type == 'ARMATURE' and len(obj.data.retargetor_profile.roles) > 0


class RETARGETOR_PT_RigLimbsPanel(Panel):
    """The limbs switching between IK and FK: how the add-on snaps them before and after a generation"""
    bl_label = "IK/FK Limbs"
    bl_idname = "RETARGETOR_PT_RigLimbsPanel"
    bl_parent_id = "RETARGETOR_PT_RigProfilePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Retarget Tool'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _profile_panel_poll(context)

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        profile = obj.data.retargetor_profile
        if len(profile.limbs) == 0:
            layout.label(text="No IK/FK limb: the rig is posed and written in FK", icon='INFO')
            return
        layout.template_list("RTGTR_UL_Limbs", "limbs", profile, "limbs", profile, "limbs_active_index", rows=2)
        if 0 <= profile.limbs_active_index < len(profile.limbs):
            limb = profile.limbs[profile.limbs_active_index]
            box = layout.box()
            box.prop_search(limb, "switch_bone", obj.pose, "bones")
            box.prop(limb, "switch_property")
            box.prop(limb, "fk_value")
            box.label(text="FK controls, and the bones they follow")
            for pair in limb.controls:
                row = box.row(align=True)
                row.prop_search(pair, "fk_control", obj.pose, "bones", text="")
                row.label(icon='FORWARD')
                row.prop_search(pair, "followed_bone", obj.pose, "bones", text="")
            if len(limb.ik_controls) > 0:
                box.label(text="IK controls (their keys make key poses)")
                for ref in limb.ik_controls:
                    box.prop_search(ref, "bone", obj.pose, "bones", text="")
            if len(limb.ik_snap) > 0:
                box.label(text="IK snap (after generating, in order)")
                for snap in limb.ik_snap:
                    row = box.row(align=True)
                    row.prop_search(snap, "ik_control", obj.pose, "bones", text="")
                    row.prop(snap, "mode", text="")
                    sub = row.row(align=True)
                    sub.enabled = snap.mode != 'REST'
                    sub.prop_search(snap, "followed_bone", obj.pose, "bones", text="")
            else:
                box.label(text="No IK snap: the limb plays in FK after generating", icon='INFO')
        layout.operator("retargetor.snap_fk_to_ik", icon='SNAP_ON')


class RETARGETOR_PT_RigAdvancedPanel(Panel):
    """Per role: how the rest pose difference is compensated, and which bones carry the root motion"""
    bl_label = "Advanced"
    bl_idname = "RETARGETOR_PT_RigAdvancedPanel"
    bl_parent_id = "RETARGETOR_PT_RigProfilePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Retarget Tool'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _profile_panel_poll(context)

    def draw(self, context):
        from .core.roles import get_role
        layout = self.layout
        for item in context.active_object.data.retargetor_profile.roles:
            row = layout.split(factor=0.4, align=True)
            row.label(text=get_role(item.role).label if item.role else "?")
            sub = row.row(align=True)
            sub.prop(item, "offset_mode", text="")
            sub.prop(item, "use_translation", text="", icon='CON_LOCLIKE', toggle=True)


def worker_status(backend):
    """The backend's model, for the panel and the animation editors' headers: (label, icon, start button text or
    "", stop button shown, error message or "")"""
    worker = registry.existing_worker(backend.id)
    if worker is None or worker.state == process.STOPPED:
        return "Stopped", 'RADIOBUT_OFF', "Start", False, worker.error if worker is not None else ""
    if worker.state == process.STARTING:
        label, icon = "Starting", 'SORTTIME'
    elif worker.busy and not worker.loaded:
        label, icon = "Loading", 'SORTTIME'
    elif worker.busy:
        label, icon = "Busy", 'SORTTIME'
    elif worker.loaded:
        label, icon = "Model loaded", 'CHECKMARK'
    else:
        label, icon = "Running", 'RADIOBUT_ON'
    start = "Load" if not worker.loaded and not worker.busy else ""
    return label, icon, start, True, worker.error or ""


def draw_progress(layout, task, width=None):
    """The running generation's progress bar and its cancel button"""
    row = layout.row(align=True)
    if width is not None:
        row.ui_units_x = width
    row.progress(factor=task.fraction, type='BAR', text=f"{task.message} {task.fraction * 100:.0f}%")
    row.operator("retargetor.cancel_generation", text="", icon='CANCEL')


class RETARGETOR_PT_GeneratePanel(Panel):
    """Generate the in-betweens of the character with the active backend"""
    bl_label = "Generate"
    bl_idname = "RETARGETOR_PT_GeneratePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Retarget Tool'

    def draw(self, context):
        layout = self.layout
        backend = active_backend(context)

        row = layout.row(align=True)
        row.label(text=f"Backend: {backend.label}", icon='OUTLINER_OB_ARMATURE')
        props = row.operator("preferences.addon_show", text="", icon='PREFERENCES')
        props.module = ADDON_ID

        from .model_setup import setup_problem
        problem = setup_problem(context, backend)
        label, icon, start, stop, error = worker_status(backend)
        row = layout.row(align=True)
        if problem:
            row.label(text=f"{problem}: see the add-on's preferences (Models)", icon='ERROR')
            start = ""
        else:
            row.label(text=label, icon=icon)
        if start:
            row.operator("retargetor.backend_start", text=start, icon='PLAY')
        if stop:
            row.operator("retargetor.backend_stop", text="Stop", icon='PAUSE')
        if error:
            box = layout.box()
            for line in error.splitlines()[:6]:
                box.label(text=line, icon='ERROR')

        rig, state = get_character(context)
        if rig is None:
            layout.label(text="Choose the character in the Retarget panel")
            return
        layout.label(text=f"Character: {rig.name}", icon='ARMATURE_DATA')
        draw_profile_status(layout, rig)
        active = context.active_object
        if (active is not None and active != rig and active.type == 'ARMATURE'
                and active != rig.retargetor.model_armature):
            layout.label(text=f"The active armature is '{active.name}', not the character", icon='ERROR')
        if len(state.segments) > 0:
            problem = draw_segments(context, layout, rig, state, backend)
        else:
            caps = backend.capabilities
            if caps.prompt:
                layout.prop(state, "prompt", text="")
            if caps.seed:
                layout.prop(state, "seed")
            problem = draw_range(context, layout, rig, state, backend)
            if caps.prompt:
                layout.operator("retargetor.segment_add", icon='SEQ_STRIP_META')

        task = generation.current_task
        if task is not None:
            draw_progress(layout, task)
        else:
            if len(state.segments) == 0:
                # The first generation: it becomes prompt segment 1. With segments, the segment's own button
                # generates it, and the timeline's Generate the whole track
                row = layout.row()
                row.enabled = not problem
                row.operator("retargetor.generate_inbetweens", text="Generate", icon='ANIM')
            layout.operator("retargetor.clear_generated_keys", icon='TRASH')


def _error(layout, text, width=48):
    """An error message as labels, cut into lines"""
    import textwrap
    for i, line in enumerate(textwrap.wrap(text, width) if text else []):
        layout.label(text=line, icon='ERROR' if i == 0 else 'BLANK1')


def draw_profile_status(layout, rig):
    """Where the character's rig profile comes from"""
    from .profile_operators import detect_profile, source_label
    profile = rig.data.retargetor_profile
    if len(profile.roles) > 0:
        layout.label(text=f"Rig: {source_label(profile.source)}", icon='OUTLINER_DATA_ARMATURE')
        return
    detected = detect_profile(rig.data)
    if detected is not None:
        layout.label(text=f"Rig: {source_label(detected[0])} (detected)", icon='OUTLINER_DATA_ARMATURE')
    else:
        _error(layout, "Rig not set up: open the Rig Setup panel")


def draw_range(context, layout, rig, state, backend):
    """The frames the next generation covers, and why the backend can't generate them ("" if it can)"""
    box = layout.box()
    box.row().prop(state, "range_mode", expand=True)
    if state.range_mode == 'CUSTOM':
        row = box.row(align=True)
        row.prop(state, "range_start")
        row.operator("retargetor.range_start_here", text="", icon='TIME')
        row.prop(state, "range_duration")
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base
    from .profile_operators import detect_profile
    rig_profile = rig.data.retargetor_profile.to_core()
    detected = detect_profile(rig.data) if not rig_profile.roles else None
    try:
        start, end, key_frames = generation.generation_range(rig, detected[1] if detected else rig_profile)
    except ValueError as e:
        _error(box, str(e))
        return str(e)
    keys = ", ".join(str(f) for f in key_frames[:6]) + (" ..." if len(key_frames) > 6 else "")
    box.label(text=f"Frames {start}-{end} ({(end - start + 1) / fps:.1f} s)", icon='TIME')
    box.label(text=f"{len(key_frames)} key poses" + (f": {keys}" if key_frames else " (prompt only)"),
              icon='KEYFRAME')
    problem = backend.range_problem(start, end, fps, len(key_frames))
    _error(box, problem)
    return problem


def draw_segments(context, layout, rig, state, backend):
    """The active prompt segment (chosen in the timeline, or with the arrows), the buttons editing the track, and
    why the backend can't generate it ("" if it can)"""
    from . import segment_track
    count = len(state.segments)
    item = segment_track.active_segment(state)
    row = layout.row(align=True)
    row.operator("retargetor.segment_step", text="", icon='TRIA_LEFT').step = -1
    row.label(text=f"Segment {state.segments_active_index + 1} / {count}", icon='SEQ_STRIP_META')
    row.operator("retargetor.segment_step", text="", icon='TRIA_RIGHT').step = 1
    row.separator()
    row.operator("retargetor.segment_add", text="", icon='ADD')
    row.operator("retargetor.segment_remove", text="", icon='REMOVE')
    row.operator("retargetor.segment_split", text="", icon='MOD_EDGESPLIT')
    caps = backend.capabilities
    if item is not None:
        if caps.prompt:
            layout.prop(item, "prompt", text="")
        else:
            layout.label(text=f"{backend.label} takes no prompt", icon='INFO')
        row = layout.row(align=True)
        row.prop(item, "frame_start")
        row.prop(item, "frame_end")
        if caps.seed:
            layout.prop(item, "seed")
        state_label = {'NEW': "Not generated yet", 'MODIFIED': "Edited since the last generation"}
        label = state_label.get(segment_track.segment_state(item))
        if label:
            layout.label(text=label, icon='INFO')
        layout.operator("retargetor.regenerate_segment", text=f"{segment_track.generate_verb(item)} Segment",
                        icon='FILE_REFRESH')

    box = layout.box()
    scene = context.scene
    fps = segment_track.scene_fps(scene)
    track = segment_track.read_track(state)
    start, end = track[0].start_frame, track[-1].end_frame
    from .segment_operators import character_profile
    rig_profile = character_profile(rig)
    if rig_profile is None:
        problem = "No rig profile"
        _error(box, problem)
        return problem
    try:
        key_frames = [f for f in generation.find_key_frames(rig, rig_profile) if start <= f <= end]
    except ValueError as e:
        _error(box, str(e))
        return str(e)
    keys = ", ".join(str(f) for f in key_frames[:6]) + (" ..." if len(key_frames) > 6 else "")
    box.label(text=f"Track: frames {start}-{end} ({(end - start + 1) / fps:.1f} s), {count} segments", icon='TIME')
    box.label(text=f"{len(key_frames)} key poses" + (f": {keys}" if key_frames else " (prompts only)"),
              icon='KEYFRAME')
    if not caps.prompt_segments and count > 1:
        box.label(text=f"{backend.label}: segments generated one by one, no transition", icon='INFO')
    problem = backend.segments_problem(track, fps, key_frames)
    _error(box, problem)
    return problem


### The animation editors' headers: everything from the timeline

class RTGTR_MT_EditorMenu(Menu):
    """Retargetor in the animation editors: generate, the prompt segments, the model"""
    bl_idname = "RTGTR_MT_editor_menu"
    bl_label = "Retargetor"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        backend = active_backend(context)
        rig, state = get_character(context)
        if rig is None:
            layout.label(text="Choose the character in the Retarget panel", icon='INFO')
        else:
            layout.label(text=f"Character: {rig.name}", icon='ARMATURE_DATA')
        layout.operator("retargetor.generate_inbetweens", text="Generate Whole Track", icon='ANIM')
        layout.separator()
        if rig is not None and len(state.segments) > 0:
            from . import segment_track
            verb = segment_track.generate_verb(segment_track.active_segment(state))
            layout.operator("retargetor.regenerate_segment", text=f"{verb} Active Segment", icon='FILE_REFRESH')
            props = layout.operator("retargetor.segment_edit", text="Edit Active Segment...", icon='GREASEPENCIL')
            props.character, props.index = rig.name, state.segments_active_index
        layout.operator("retargetor.segment_add", icon='ADD')
        layout.operator("retargetor.segment_split", icon='MOD_EDGESPLIT')
        layout.operator("retargetor.segment_remove", icon='REMOVE')
        layout.prop(context.scene, "retargetor_show_segments")
        layout.separator()
        layout.operator("retargetor.clear_generated_keys", icon='TRASH')
        layout.separator()
        label, icon, start, stop, error = worker_status(backend)
        layout.label(text=f"{backend.label}: {label}", icon=icon)
        if start:
            layout.operator("retargetor.backend_start", text=f"{start} {backend.label}", icon='PLAY')
        if stop:
            layout.operator("retargetor.backend_stop", text=f"Stop {backend.label}", icon='PAUSE')
        for line in error.splitlines()[:6]:
            layout.label(text=line, icon='ERROR')
        props = layout.operator("preferences.addon_show", text="Preferences...", icon='PREFERENCES')
        props.module = ADDON_ID


def draw_editor_header(self, context):
    """Appended to the Dope Sheet (Timeline included) and Graph Editor headers: the model's state, the
    generation's progress or the Generate button, the bands' visibility and the Retargetor menu"""
    layout = self.layout
    scene = context.scene
    if not hasattr(scene, "retargetor_show_segments"):
        return
    backend = active_backend(context)
    layout.separator()
    row = layout.row(align=True)
    show = scene.retargetor_show_segments
    row.prop(scene, "retargetor_show_segments", text="", icon='HIDE_OFF' if show else 'HIDE_ON')
    row.menu(RTGTR_MT_EditorMenu.bl_idname, text="", icon='OUTLINER_OB_ARMATURE')
    task = generation.current_task
    if task is not None:
        draw_progress(layout, task, width=12)
        return
    from .model_setup import setup_problem
    problem = setup_problem(context, backend)
    label, icon, start, _stop, error = worker_status(backend)
    row = layout.row(align=True)
    if problem:
        row.label(text=f"{backend.label}: {problem}", icon='ERROR' if problem != "Installing" else 'SORTTIME')
        props = row.operator("preferences.addon_show", text="", icon='PREFERENCES')
        props.module = ADDON_ID
    else:
        row.label(text=backend.label, icon='ERROR' if error else icon)
        if start:
            row.operator("retargetor.backend_start", text="", icon='PLAY')
    layout.operator("retargetor.generate_inbetweens", text="Generate", icon='ANIM')


_HEADERS = ("DOPESHEET_HT_header", "GRAPH_HT_header")


class RTGTR_UL_Limbs(UIList):
    """Limbs whose FK controls can be snapped to their IK pose"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False)
        row.label(text=f"{len(item.controls)} FK controls")


### Registration
classes = (
    RTGTR_UL_Bones,
    RTGTR_UL_Limbs,
    RETARGETOR_PT_RetargetPanel,
    RETARGETOR_PT_RigProfilePanel,
    RETARGETOR_PT_RigLimbsPanel,
    RETARGETOR_PT_RigAdvancedPanel,
    RTGTR_MT_ProfileFiles,
    RETARGETOR_PT_GeneratePanel,
    RTGTR_MT_EditorMenu,
)

def register():
    for cl in classes:
        bpy.utils.register_class(cl)
    for name in _HEADERS:
        getattr(bpy.types, name).append(draw_editor_header)


def unregister():
    for name in _HEADERS:
        getattr(bpy.types, name).remove(draw_editor_header)
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)
