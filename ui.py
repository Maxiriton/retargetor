# type: ignore
import bpy
from bpy.types import Panel, UIList

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
        box.prop(scene, "retarget_source_armature", text="Source")
        box.prop(scene, "retarget_target_armature", text="Target")

        row = box.row(align=True)
        row.prop(scene, "retarget_translation_scale", text="Translation Scale")
        row.operator("retargetor.auto_translation_scale", icon='FIXED_SIZE')

        if len(context.scene.retarget_bones) == 0 :
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
                scene, "retarget_bones",
                scene, "retarget_bones_active_index"
            )
            layout.operator('retargetor.export_setup_to_json', text="Export to json")


        layout.separator()
        layout.label(text="Retarget", icon='ARMATURE_DATA')

        # Bouton pour lancer l'action
        layout.operator("retargetor.simple_retarget", icon='ANIM_DATA')
        layout.operator("retargetor.snap_selected_bone", icon='ANIM_DATA')
        layout.operator("retargetor.snap_full_pose", icon='ANIM_DATA')

class RTGTR_UL_Bones(UIList):
    """UI List for bones matching and setuping"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        row = layout.row(align=True)

        if context.scene.retarget_is_recording and context.scene.retarget_bones_active_index != index:
            row.enabled = False

        split1 = row.split(factor=0.33, align=True)
        col1 = split1.column(align=True)

        if item.is_setup:
            col1.label(text=item.src_name, icon='CHECKMARK')
        else:
            col1.label(text=item.src_name, icon='DECORATE')

        split2 = split1.split(factor=0.5, align=True)
        col2 = split2.column(align=True)

        target_obj = context.scene.retarget_target_armature
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

        if context.scene.retarget_is_recording and context.scene.retarget_bones_active_index == index:
            row2.operator(
                "retargetor.finish_record",
                text="Finish Recording",
                icon='REC'
            )
        elif item.has_corrective_offset:
            row2.operator(
                "retargetor.record_adjustement",
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
                "retargetor.record_adjustement",
                text="Record Correction",
                icon='ARMATURE_DATA'
            )




### Registration
classes = (
    RTGTR_UL_Bones,
    RETARGETOR_PT_RetargetPanel,
)

def register():
    for cl in classes:
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)
