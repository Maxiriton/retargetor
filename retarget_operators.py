# type: ignore
"""This module contains operator for kimodo retargeting"""

import json
import math
import os

import os

import bpy
from bpy.types import Operator
from bpy.props import StringProperty

from mathutils import Matrix, Quaternion, Vector


def callback_update_lerp_property(self, context):
    lerp_value = self.lerp_rotation
    tgt_armature = context.scene.retarget_target_armature

    for bone_name, bone_info in tgt_armature['bone_mapping'].items():
        if bone_name != "mixamorig1:LeftShoulder":
            continue
        tgt_armature.pose.bones[bone_name].rotation_mode = 'QUATERNION'
        offset = Quaternion(bone_info.get('offset', Matrix.Identity(4).to_quaternion()))
        tgt_armature.pose.bones[bone_name].rotation_quaternion = Matrix.Identity(4).to_quaternion().slerp(offset, lerp_value)
    return None



def add_empties_at_target_bones(context):
    """Add empties at the location of target bones for visualization"""
    target_armature = context.scene.retarget_target_armature
    src_armature = context.scene.retarget_source_armature
    scene = context.scene
    if not target_armature or not src_armature:
        return
    
    for obj in bpy.data.objects:
        if obj.name.startswith("Empty_"):
            bpy.data.objects.remove(obj, do_unlink=True)

    for bone_name, bone_info in target_armature['bone_mapping'].items():
        bone_tgt = target_armature.pose.bones.get(bone_name)
        bone_scr = src_armature.pose.bones.get(bone_info.get("src_bone", ""))

        if bone_tgt:
            empty_name = f"Empty_{bone_name}"
            empty = bpy.data.objects.new(empty_name, None)
            context.collection.objects.link(empty)
            empty.location = target_armature.matrix_world @ bone_tgt.head
            empty.empty_display_size = 0.03
            empty.empty_display_type = 'ARROWS'
            empty.rotation_mode = 'QUATERNION'

            const = empty.constraints.new('COPY_ROTATION')
            const.target = context.scene.retarget_source_armature
            const.subtarget = bone_info.get('src_bone', "")

            const_loc = empty.constraints.new('COPY_LOCATION')
            const_loc.target = context.scene.retarget_target_armature
            const_loc.subtarget = bone_tgt.name

            # start_frame = scene.frame_start 
            # end_frame = scene.frame_end
    
            # for frame in range(start_frame, end_frame + 1):
            #     scene.frame_set(frame)
            #     empty.rotation_quaternion = bone_scr.matrix.to_quaternion()
            #     empty.keyframe_insert(data_path="rotation_quaternion", frame=frame)






def init_bone_mapping_from_json(context, json_path):
    """Initializes the bone_tgt mapping from a JSON file and store bone_tgt mapping in a dict as a custom property of the target armature"""

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    bone_mapping = {}
    with open(json_path, 'r', encoding='utf-8') as f:
        for item in json.load(f):
            if item.get("en", False) and "src" in item and "tgt" in item:
                bone_mapping[item["tgt"]] = {"src_bone": item["src"]}

    context.scene.retarget_target_armature['bone_mapping'] = bone_mapping

def fill_bone_mapping_offset(context, source_armature, target_armature):
    """Fill the bone_tgt mapping with rotation offsets based on the rest pose of source and target armatures"""

    for tgt_bone_name, bone_info in context.scene.retarget_target_armature['bone_mapping'].items():

        matrix_src_edit_local = source_armature.data.bones[bone_info["src_bone"]].matrix_local.copy()
        matrix_tgt_edit_local = target_armature.data.bones[tgt_bone_name].matrix_local.copy()


        rot_src = (source_armature.matrix_world @ matrix_src_edit_local).to_quaternion()
        rot_tgt = (target_armature.matrix_world @ matrix_tgt_edit_local).to_quaternion()

        rot_offset = rot_tgt.rotation_difference(rot_src)
        rot_offset = rot_src.rotation_difference(rot_tgt)
        bone_info['rot_tgt'] = rot_tgt
        bone_info['rot_src'] = rot_src
        bone_info['offset'] = rot_offset #we store the rotation offset 
        context.scene.retarget_target_armature['bone_mapping'][tgt_bone_name] = bone_info



class RTG_SimpleRetarget(Operator):
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

        #we create a dictionary to store the bone_tgt mapping and store it in the scene for later use
        init_bone_mapping_from_json(context, scene.retarget_json_path)  
        #we fill the dict with the rotation offsets based on the rest pose of source and target armatures
        fill_bone_mapping_offset(context, source_obj, target_obj)  

        add_empties_at_target_bones(context)  # Add empties at target bone_tgt locations for visualization

        start_frame = scene.frame_start 
        end_frame = scene.frame_end
    

        for frame in range(start_frame, end_frame + 1):
            scene.frame_set(frame)
            for tgt_bone_name, bone_info in target_obj['bone_mapping'].items():
                if tgt_bone_name not in ["mixamorig1:LeftShoulder","mixamorig1:LeftArm","mixamorig1:LeftForeArm","mixamorig1:LeftHand"]:
                    continue

                src_bone_name = bone_info["src_bone"]
                src_bone = source_obj.pose.bones.get(src_bone_name)
                tgt_bone = target_obj.pose.bones.get(tgt_bone_name)

                tgt_bone.rotation_mode = 'QUATERNION'
                tgt_bone.matrix = src_bone.matrix

                angle_rad = math.radians(90)  # 90
                q_correction = Quaternion(Vector((0.0,1.0,0.0)), angle_rad)
                q_offset = Quaternion(bone_info['offset'])
                
                
                q_actuel = tgt_bone.rotation_quaternion.copy()

                tgt_bone.rotation_quaternion = q_actuel @ q_correction
                # tgt_bone.rotation_quaternion = q_actuel @ q_offset




                tgt_bone.location = Vector((0.0, 0.0, 0.0))  # Reset location to avoid unwanted translation
                
                # Gestion de la translation pour les Hips / Root
                if "hips" in tgt_bone_name.lower() or "root" in tgt_bone_name.lower():
                    # Optionnel : Tu peux copier la position du Hips monde si nécessaire
                    # tgt_bone.location = (target_obj.matrix_world.inverted() @ matrix_src_current_world).to_translation()
                    tgt_bone.keyframe_insert(data_path="location", frame=frame)
                
                tgt_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)

        self.report({'INFO'}, f"Reciblage réussi sur {end_frame - start_frame + 1} frames.")
        return {'FINISHED'}

class SetupArmatureConstraint(Operator):
    """Read a json file with the list of pairing bones from source to target and setup the constraints on the target armature"""
    bl_idname = "retargetor.setup_armature_constraint"
    bl_label = "Setup Armature Constraint"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype="FILE_PATH")

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None and 
                context.active_object.type == 'ARMATURE' and 
                context.mode in {'OBJECT', 'POSE'})
    
    def invoke(self, context, event):  
        context.window_manager.fileselect_add(self) 
        return {'RUNNING_MODAL'}
    
    def execute(self, context): 
        if not os.path.exists(self.filepath):
            self.report({'ERROR'}, f"Fichier introuvable : {self.filepath}")
            return {'CANCELLED'}

        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Erreur de lecture JSON : {e}")
            return {'CANCELLED'}

        tgt_arm_obj = context.active_object
        
        # 2. Identifier l'Armature Source (on la cherche dynamiquement dans la scène)
        # On va inspecter le premier élément du JSON pour trouver l'armature contenant l'os source
        src_arm_obj = None
        if mapping_data:
            first_src_bone = mapping_data[0].get("src")
            for obj in context.scene.objects: 
                if obj.type == 'ARMATURE' and obj != tgt_arm_obj:
                    if first_src_bone in obj.data.bones: 
                        src_arm_obj = obj
                        break

        if not src_arm_obj:
            self.report({'ERROR'}, "Impossible de trouver automatiquement l'Armature Source dans la scène.")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Source détectée : {src_arm_obj.name} -> Destination : {tgt_arm_obj.name}") 

        print("\n" + "="*50)
        print(f"ANALYSE DES DIFFÉRENCES D'ANGLES (REST POSE)")
        print(f"Source: {src_arm_obj.name} -> Target: {tgt_arm_obj.name}") 
        print("="*50)

        # Dictionnaire pour stocker les résultats si tu veux les réutiliser plus tard
        angle_offsets = {}

        for bone_map in mapping_data:
            if not bone_map.get("en", True):
                continue

            src_bone_name = bone_map.get("src")
            tgt_bone_name = bone_map.get("tgt")

            if src_bone_name not in src_arm_obj.data.bones or tgt_bone_name not in tgt_arm_obj.data.bones: 
                continue

            # 1. Récupérer les matrices de repos locales à l'armature
            matrix_rest_src = src_arm_obj.data.bones[src_bone_name].matrix_local 
            matrix_rest_tgt = tgt_arm_obj.data.bones[tgt_bone_name].matrix_local 

            # 2. Extraire uniquement la partie rotation (Matrice 3x3)
            rot_src = matrix_rest_src.to_3x3()
            rot_tgt = matrix_rest_tgt.to_3x3()

            # 3. Calculer la matrice de rotation relative (la différence)
            # Quelle rotation faut-il appliquer à la source pour obtenir la cible ?
            # Formule : R_diff = R_src^-1 * R_tgt
            matrix_diff = rot_src.inverted() @ rot_tgt

            # 4. Convertir cette matrice de différence en angles d'Euler (en degrés)
            # On utilise l'ordre 'XYZ' par défaut, modifiable selon tes contraintes de destination
            euler_diff = matrix_diff.to_euler('XYZ')
            
            diff_x = math.degrees(euler_diff.x)
            diff_y = math.degrees(euler_diff.y)
            diff_z = math.degrees(euler_diff.z)

            # Stockage des données
            angle_offsets[tgt_bone_name] = (diff_x, diff_y, diff_z)

            print(f"Matrice diff : {matrix_diff}")

            # Affichage formaté dans la console
            print(f"Os Cible: {tgt_bone_name:<25} | Diff X: {diff_x:>7.2f}° | Diff Y: {diff_y:>7.2f}° | Diff Z: {diff_z:>7.2f}°")

        print("="*50 + "\n")
        self.report({'INFO'}, "Analyse terminée. Consultez la console système de Blender.")
        
        # Exemple d'utilisation : Tu peux stocker ce dictionnaire d'offsets 
        # dans une propriété de la scène ou de l'armature si besoin.
        return {'FINISHED'}
    

### Registration
classes = (
    SetupArmatureConstraint,
    RTG_SimpleRetarget
)

def register():
    for cl in classes:  
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)
