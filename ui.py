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
        box.prop(scene, "retarget_json_path", text="Lien JSON")

        if len(context.scene.retarget_bones) == 0 :
            layout.label(text='Il va falloir remplir ca')
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
        # layout.prop(scene, "lerp_rotation", text="Lerp Rotation")

class RTGTR_UL_Bones(UIList):
    """UI List for bones matching and setuping"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index): # type: ignore
        row = layout.row(align=True)

        split = row.split(factor=0.3)
        c = split.column()
        if item.is_setup:
            c.label(text=item.src_name, icon='CHECKMARK')
        else:
            c.label(text=item.src_name, icon='DECORATE')
        
        split = split.split(factor=0.5)
        c = split.column()
        c.prop_search(
            item,
            "target_name",
            context.scene.retarget_target_armature.pose,
            "bones",
            text=""
        )
        c = split.column()
        row = c.row(align=True)
        row.prop(item, "roll_offset", text="")
        row.prop(item, "offset_mode", text="")

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