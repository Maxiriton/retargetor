# type: ignore
import bpy
import json
import math
from bpy.types import Operator
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Vector, Quaternion

def update_target_bone(self, context):
    """Callback function call when a user setup a match for bone source/target"""
    self.roll_offset = compute_bone_offset(context, self.src_name, self.target_name)
    self.rest_offset = compute_rest_offset(context, self.src_name, self.target_name)
    self.is_setup = True


def compute_bone_offset(context, bone_source_name, bone_target_name):
    """Calculate the bone offset along the Y axis"""
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
    
class RTGTR_Record_to_json(Operator, ExportHelper):
    """Export retarget setup to json"""
    
    bl_idname = "retargetor.export_setup_to_json"
    bl_label = "Export to JSON"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    filter_glob: StringProperty(
        default="*.json",
        options={'HIDDEN'},
        maxlen=255,
    )

    def execute(self, context):
        scene = context.scene
        
        collection_data = []
        for item in scene.retarget_bones:
            data = {
                "src_name": item.src_name,
                "target_name": item.target_name,
                # Conversion du FloatVectorProperty (Quaternion size=4) en liste de floats
                "rest_offset": list(item.rest_offset),
                "roll_offset": item.roll_offset,
                "is_setup": item.is_setup,
                "offset_mode": item.offset_mode,
            }
            collection_data.append(data)

        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(collection_data, f, indent=4)
                
            self.report({'INFO'}, f"Export Successfull : {self.filepath}")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Export failed : {str(e)}")
            return {'CANCELLED'}

class RTGTR_import_retarget_json(Operator, ImportHelper):
    """Importe la configuration de reciblage depuis un fichier JSON"""
    
    bl_idname = "retargetor.import_retarget_json"
    bl_label = "Import from JSON"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    filter_glob: StringProperty(
        default="*.json",
        options={'HIDDEN'},
        maxlen=255,
    )

    def execute(self, context):
        scene = context.scene
        
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Impossible de lire le fichier : {str(e)}")
            return {'CANCELLED'}

        if not isinstance(data, list):
            self.report({'ERROR'}, "Le fichier JSON n'est pas au bon format (une liste d'éléments est attendue)")
            return {'CANCELLED'}

        collection = scene.retarget_bones
        
        collection.clear()

        for item_data in data:
            new_item = collection.add()
            
            # Utilisation de .get() pour éviter que ça plante si une clé est manquante dans le JSON
            new_item.src_name = item_data.get("src_name", "")
            new_item.target_name = item_data.get("target_name", "")
            
            # Reconstruction du Quaternion/FloatVectorProperty
            rest_offset = item_data.get("rest_offset", [1.0, 0.0, 0.0, 0.0])
            if len(rest_offset) == 4:
                new_item.rest_offset = Quaternion(rest_offset)
                
            new_item.roll_offset = item_data.get("roll_offset", 0.0)
            new_item.is_setup = item_data.get("is_setup", False)
            
            # Pour l'enum, on vérifie qu'on injecte bien une valeur valide
            if "offset_mode" in item_data:
                new_item.offset_mode = item_data["offset_mode"]

        self.report({'INFO'}, f"Importation réussie ({len(data)} os importé(s))")
        return {'FINISHED'}


### Registration
classes = (
    RTGTR_Setup_Bone_List,
    RTGTR_Record_to_json,
    RTGTR_import_retarget_json
)

def register():
    for cl in classes:  
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)


