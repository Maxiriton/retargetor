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
        
        layout.separator()
        layout.label(text="Retarget", icon='ARMATURE_DATA')
        
        # Bouton pour lancer l'action
        layout.operator("retargetor.simple_retarget", icon='ANIM_DATA')
        layout.prop(scene, "lerp_rotation", text="Lerp Rotation")



### Registration
classes = (
    RETARGETOR_PT_RetargetPanel,
)

def register():
    for cl in classes:  
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)