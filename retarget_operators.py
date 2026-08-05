# type : ignore
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

def snap_bone_rotation(context, bone_target_name, add_roll=True, add_corrective_offset=True):
    target_obj = context.scene.retarget_target_armature 
    source_obj = context.scene.retarget_source_armature 
    
    if not target_obj or not source_obj:
        raise ValueError("Les armatures source ou cible ne sont pas définies dans la scène.")
        
    tgt_bone = target_obj.data.bones.get(bone_target_name)
    if not tgt_bone:
        raise KeyError(f"L'os cible '{bone_target_name}' n'existe pas dans l'armature '{target_obj.name}'.")

    matching_items = get_items_by_target_name(context.scene.retarget_bones, tgt_bone.name)
    
    if len(matching_items) == 0:
        raise KeyError(f"Aucune correspondance trouvée dans 'retarget_bones' pour l'os cible '{tgt_bone.name}'.")
    elif len(matching_items) > 1:
        raise ValueError(f"Plusieurs correspondances ({len(matching_items)}) ont été trouvées pour l'os cible '{tgt_bone.name}'.")

    item = matching_items[0]

    # Vérification que l'os source existe dans la data de l'armature source
    if item.src_name not in source_obj.data.bones:
        raise KeyError(f"L'os source '{item.src_name}' n'existe pas dans l'armature source '{source_obj.name}'.")

    src_bone = source_obj.data.bones[item.src_name]

    src_pose_bone = source_obj.pose.bones.get(src_bone.name)
    tgt_pose_bone = target_obj.pose.bones.get(tgt_bone.name)
    
    if not src_pose_bone or not tgt_pose_bone:
        raise AttributeError("Impossible d'accéder aux PoseBones (vérifiez que les armatures sont valides).")
    
    tgt_pose_bone.rotation_mode = 'QUATERNION'
    tgt_pose_bone.matrix = src_pose_bone.matrix
    
    if add_roll: 
        q_correction = Quaternion()  # Quaternion Identité par défaut
        
        if item.offset_mode == 'ROLL':
            q_correction = Quaternion(Vector((0.0, 1.0, 0.0)), item.roll_offset)
        elif item.offset_mode == 'REST_OFFSET':
            # Utilisation de rest_offset_quat si c'est le nom de ta FloatVectorProperty
            q_correction = Quaternion(item.rest_offset)
    
        q_rot = tgt_pose_bone.rotation_quaternion
        tgt_pose_bone.rotation_quaternion = q_rot @ q_correction

    if add_corrective_offset and item.is_setup:
        q_corrective = Quaternion(item.corrective_offset)  # Quaternion stocké dans l'item
        q_rot = tgt_pose_bone.rotation_quaternion
        tgt_pose_bone.rotation_quaternion = q_rot @ q_corrective
    
    tgt_pose_bone.location = Vector((0.0, 0.0, 0.0))  # Reset location

    return True


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
        tgt_bone = context.active_object.data.bones.active
        try:
            snap_bone_rotation(context, tgt_bone.name, add_roll=True)
            self.report({'INFO'}, "Alignement réussi !")
            return {'FINISHED'}
        
        except (KeyError, ValueError, AttributeError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


def snap_bone_hierarchy_recursive(context, bone, level=0):
    """
    Fonction récursive qui affiche un os et parcourt tous ses enfants.
    """
    # Création d'une indentation visuelle selon le niveau dans l'arbre
    indent = "    " * level
    prefix = "└── " if level > 0 else ""
    
    print(f"{indent}{prefix}{bone.name}")
    try:
        snap_bone_rotation(context, bone.name)
    except (KeyError, ValueError, AttributeError) as e:
        print(f"{e}")
    
    # Appel récursif pour chaque enfant de cet os
    for child in bone.children:
        snap_bone_hierarchy_recursive(context, child, level + 1)

class RTGTR_snap_full_pose(Operator):
    """Snap the full pose at the current frame"""
    bl_idname = "retargetor.snap_full_pose"
    bl_label = "Snap full pose"
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
        armature_obj =  context.scene.retarget_target_armature
        bones = armature_obj.data.bones
        
        root_bones = [b for b in bones if b.parent is None]
        
        if not root_bones:
            self.report({'WARNING'}, f"L'armature '{armature_obj.name}' ne contient aucun os.")
            return {'CANCELLED'}

        for root in root_bones:
            snap_bone_hierarchy_recursive(context, root)
            
        print("="*40 + "\n")

        self.report({'INFO'}, "Hiérarchie affichée dans la console System (Window -> Toggle System Console)")
        return {'FINISHED'}

       

    


### Registration
classes = (
    RTGTR_SimpleRetarget,
    RTGTR_snap_selected_bone,
    RTGTR_snap_full_pose,
)

def register():
    for cl in classes:  
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)
