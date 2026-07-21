# type: ignore
import bpy
import math
from bpy.types import Operator
from mathutils import Vector

def update_target_bone(self, context):
    """Callback function call when a user setup a match for bone source/target"""
    self.roll_offset = compute_bone_offset(context, self.src_name, self.target_name)
    self.rest_offset = compute_rest_offset(context, self.src_name, self.target_name)
    self.is_setup = True


def compute_bone_offset(context, bone_source_name, bone_target_name):
    """Calculate the bone """

    rot_src_edit_local = context.scene.retarget_source_armature.data.bones[bone_source_name].matrix_local.copy().to_3x3()
    rot_tgt_edit_local = context.scene.retarget_target_armature.data.bones[bone_target_name].matrix_local.copy().to_3x3()

    x_src = rot_src_edit_local @ Vector((1.0,0.0,0.0))

    x_src_in_tgt_local = rot_tgt_edit_local.inverted() @ x_src

    return math.atan2(x_src_in_tgt_local.z, x_src_in_tgt_local.x)

def compute_rest_offset(context, bone_source_name, bone_target_name):
    """Get the rotation difference between the two bones"""
    rot_src = context.scene.retarget_source_armature.data.bones[bone_source_name].matrix_local.copy().to_quaternion()
    rot_tgt = context.scene.retarget_target_armature.data.bones[bone_target_name].matrix_local.copy().to_quaternion()
    return rot_tgt.rotation_difference(rot_src)

def find_bone_in_target(context, target_bone_name):
    """ Find a bone in the target armature"""
    tg_name = target_bone_name.lower()
    for bone in context.scene.retarget_target_armature.pose.bones:
        name = bone.name.lower()
        if name in tg_name or tg_name in name:
            return bone.name
    return ""

class RTGTR_Setup_Bone_List(Operator):
    bl_idname = "retargetor.setup_bone_list"
    bl_label = "Setup Bone list"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.retarget_source_armature is not None and \
               context.scene.retarget_target_armature is not None 
    
    def execute(self, context):
        scene = context.scene
        scene.retarget_bones.clear()

        target_obj = scene.retarget_target_armature 
        source_obj = scene.retarget_source_armature

        for bone in source_obj.pose.bones:
            rtg_item = scene.retarget_bones.add()
            rtg_item.src_name = bone.name

            #we try to find the matching bones in target_armature (based on names only)
            print(f"on va chercher la target pour {bone.name}")
            rtg_item.target_name = find_bone_in_target(context, bone.name)
            if rtg_item.target_name: 
                rtg_item.roll_offset = compute_bone_offset(context, rtg_item.src_name, rtg_item.target_name)
                rtg_item.rest_offset = compute_rest_offset(context, rtg_item.src_name, rtg_item.target_name)
                rtg_item.is_setup = True

        self.report({'INFO'}, f"Found {len(scene.retarget_bones)} bones")
        return {'FINISHED'}


### Registration
classes = (
    RTGTR_Setup_Bone_List,
)

def register():
    for cl in classes:  
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)


