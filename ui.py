# type: ignore
import bpy
from bpy.types import Panel, UIList

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
    """Rig profile of the active armature: its bones for each humanoid role"""
    bl_label = "Rig Profile"
    bl_idname = "RETARGETOR_PT_RigProfilePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Retarget Tool'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE':
            layout.label(text="Select an armature")
            return

        armature = obj.data
        profile = armature.retargetor_profile
        layout.label(text=f"Armature: {armature.name}", icon='ARMATURE_DATA')
        if not armature.is_editable:
            layout.label(text="Linked armature: edit the profile in its library file", icon='LIBRARY_DATA_DIRECT')

        row = layout.row(align=True)
        row.operator("retargetor.profile_load_preset", icon='PRESET')
        row.operator("retargetor.profile_add_roles", icon='ADD')
        row = layout.row(align=True)
        row.operator("retargetor.profile_import_json", icon='IMPORT')
        row.operator("retargetor.profile_export_json", icon='EXPORT')

        if len(profile.roles) == 0:
            layout.label(text="No role mapped yet: load a preset or add the roles")
        else:
            row = layout.row()
            row.label(text="Role")
            row.label(text="Read")
            row.label(text="Write")
            layout.template_list("RTGTR_UL_Roles", "roles", profile, "roles", profile, "roles_active_index", rows=6)

        if len(profile.limbs) > 0:
            layout.label(text="IK limbs", icon='CON_KINEMATIC')
            layout.template_list("RTGTR_UL_Limbs", "limbs", profile, "limbs", profile, "limbs_active_index", rows=2)
            if 0 <= profile.limbs_active_index < len(profile.limbs):
                limb = profile.limbs[profile.limbs_active_index]
                box = layout.box()
                box.prop_search(limb, "switch_bone", obj.pose, "bones")
                box.prop(limb, "switch_property")
                box.prop(limb, "fk_value")
                for pair in limb.controls:
                    row = box.row(align=True)
                    row.prop_search(pair, "fk_control", obj.pose, "bones", text="")
                    row.label(icon='FORWARD')
                    row.prop_search(pair, "followed_bone", obj.pose, "bones", text="")
            layout.operator("retargetor.snap_fk_to_ik", icon='SNAP_ON')


class RTGTR_UL_Roles(UIList):
    """Humanoid roles of a rig profile: the bone read and the control written for each"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        obj = context.active_object
        split = layout.split(factor=0.25, align=True)
        split.label(text=item.label)
        split = split.split(factor=0.4, align=True)
        split.prop_search(item, "read_bone", obj.pose, "bones", text="")
        split = split.split(factor=0.67, align=True)
        split.prop_search(item, "write_bone", obj.pose, "bones", text="")
        row = split.row(align=True)
        row.prop(item, "use_translation", text="", icon='CON_LOCLIKE', toggle=True)
        row.prop(item, "offset_mode", text="")


class RTGTR_UL_Limbs(UIList):
    """Limbs whose FK controls can be snapped to their IK pose"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False)
        row.label(text=f"{len(item.controls)} FK controls")


### Registration
classes = (
    RTGTR_UL_Bones,
    RTGTR_UL_Roles,
    RTGTR_UL_Limbs,
    RETARGETOR_PT_RetargetPanel,
    RETARGETOR_PT_RigProfilePanel,
)

def register():
    for cl in classes:
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)
