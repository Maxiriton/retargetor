# type: ignore
"""This module contains operator for kimodo retargeting"""
import bpy
from bpy.types import Operator
from bpy.props import BoolProperty
from mathutils import Quaternion, Vector

def get_items_by_target_name(collection, target_name):
    """
    Retourne la liste de tous les BoneRetargetInfo ayant le target_name spécifié.
    
    :param collection: La CollectionProperty (ex: context.scene.my_retarget_collection)
    :param target_name: Le nom de l'os cible à rechercher (str)
    :return: List[BoneRetargetInfo]
    """
    return [item for item in collection if item.target_name == target_name]

class RTGTR_SimpleRetarget(Operator):
    bl_idname = "retargetor.simple_retarget"
    bl_label = "Retarget"
    bl_options = {'REGISTER', 'UNDO'}


    @classmethod
    def poll(cls, context):
        return (context.scene.retarget_source_armature is not None and \
               context.scene.retarget_target_armature is not None and  \
               context.scene.retarget_json_path != "") 

    def execute(self, context): 
        scene = context.scene

        target_obj = scene.retarget_target_armature 
        source_obj = scene.retarget_source_armature 

        start_frame = scene.frame_start 
        end_frame = scene.frame_end
    
        for frame in range(start_frame, end_frame + 1):
            scene.frame_set(frame)
            for item in scene.retarget_bones:
                if not item.is_setup :
                    continue
 
                if item.target_name in ["mixamorig1:Hips"]:
                    print('on ignore le hips')
                    continue

                src_bone = source_obj.pose.bones.get(item.src_name)
                tgt_bone = target_obj.pose.bones.get(item.target_name)

                tgt_bone.rotation_mode = 'QUATERNION'
                tgt_bone.matrix = src_bone.matrix

                q_correction = Quaternion.identity
                if item.offset_mode == 'ROLL':
                    q_correction = Quaternion(Vector((0.0,1.0,0.0)), item.roll_offset)
                elif item.offset_mode == 'REST_OFFSET' :
                    q_correction = Quaternion(item.rest_offset)
                
                
                q_rot = tgt_bone.rotation_quaternion
                tgt_bone.rotation_quaternion = q_rot @ q_correction

                tgt_bone.location = Vector((0.0, 0.0, 0.0))  # Reset location to avoid unwanted translation
                
                # Gestion de la translation pour les Hips / Root
                if "hips" in item.target_name.lower() or "root" in item.target_name.lower():
                    tgt_bone.keyframe_insert(data_path="location", frame=frame)
                
                tgt_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)

        self.report({'INFO'}, f"Reciblage réussi sur {end_frame - start_frame + 1} frames.")
        return {'FINISHED'}

class RTGTR_snap_selected_bone(Operator):
    """Snap the current selected bone"""

    bl_idname = "retargetor.snap_selected_bone"
    bl_label = "Snap active bone"
    bl_options = {'REGISTER', 'UNDO'}

    add_roll : BoolProperty(
        name="Add roll rotation",
        default=False
    )

    @classmethod
    def poll(cls, context):
        return context.scene.retarget_source_armature is not None and \
               context.scene.retarget_target_armature is not None and \
               context.mode == 'POSE' and \
               context.active_object.name == context.scene.retarget_target_armature.name
    
    
    def execute(self, context):
        target_obj = context.scene.retarget_target_armature 
        source_obj = context.scene.retarget_source_armature 
    
        tgt_bone = context.active_object.data.bones.active
        matching_items = get_items_by_target_name(context.scene.retarget_bones, tgt_bone.name)

        if len(matching_items) != 1:
            return {'CANCELLED'}

        item = matching_items[0]
        src_bone = context.scene.retarget_source_armature.data.bones[item.src_name]
        print(f"Le bone actif est {tgt_bone.name} et le bone source est {src_bone.name}")

        src_pose_bone = source_obj.pose.bones.get(src_bone.name)
        tgt_pose_bone = target_obj.pose.bones.get(tgt_bone.name)

        tgt_pose_bone.rotation_mode = 'QUATERNION'
        tgt_pose_bone.matrix = src_pose_bone.matrix


        if self.add_roll: 
            q_correction = Quaternion.identity
            if item.offset_mode == 'ROLL':
                q_correction = Quaternion(Vector((0.0,1.0,0.0)), item.roll_offset)
            elif item.offset_mode == 'REST_OFFSET' :
                q_correction = Quaternion(item.rest_offset)
        
            q_rot = tgt_pose_bone.rotation_quaternion
            tgt_pose_bone.rotation_quaternion = q_rot @ q_correction


        tgt_pose_bone.location = Vector((0.0, 0.0, 0.0))  # Reset location to avoid unwanted translation
                
        return {'FINISHED'}

    


### Registration
classes = (
    RTGTR_SimpleRetarget,
    RTGTR_snap_selected_bone,
)

def register():
    for cl in classes:  
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)
