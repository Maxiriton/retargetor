# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


# type : ignore

bl_info = {
    "name": "Retargetor",
    "author": "Henri Hebeisen",
    "description": "",
    "blender": (5, 1, 0),
    "version": (0, 0, 1),
    "location": "",
    "warning": "",
    "category": "Generic",
}

import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty, FloatVectorProperty, EnumProperty, CollectionProperty
from bpy.types import PropertyGroup
from bpy.app.handlers import persistent

from . import ui
from . import retarget_operators
from . import setup_operators

#Bone offset
offset_items = [
    ('ROLL',"Roll","Subtract the edit bones roll difference", 0),
    ("REST_OFFSET","Offset","Subtract the rotation offset between two rest poses", 1)
]

def set_active_item_by_target(scene, target_name):
    collection = scene.retarget_bones
    for index, item in enumerate(collection):
        if item.target_name == target_name:
            scene.retarget_bones_active_index = index 
            return True
    return False

def set_active_item_by_source(scene, target_name):
    collection = scene.retarget_bones
    for index, item in enumerate(collection):
        if item.src_name == target_name:
            scene.retarget_bones_active_index = index 
            return True
    return False


def on_bone_selection_changed(scene, pose_bone):
    active_obj = bpy.context.active_object
    if active_obj is scene.retarget_source_armature:
        found = set_active_item_by_source(scene, pose_bone.name)
        if not found:
            print(f"Pas de bone défini pour {pose_bone.name} dans l'armature target")
    elif active_obj is scene.retarget_target_armature:
        found = set_active_item_by_target(scene, pose_bone.name)
        if not found:
            print(f"Pas de bone défini pour {pose_bone.name} dans l'armature source")


@persistent
def check_bone_selection_handler(scene):
    active_obj = bpy.context.active_object
    if active_obj and active_obj.type == 'ARMATURE' and active_obj.mode == 'POSE':
        active_bone = active_obj.data.bones.active
        
        if active_bone:
            # 3. Si l'os actif a changé par rapport à notre dernière sauvegarde
            if active_bone.name != scene.last_active_bone_name:
                scene.last_active_bone_name = active_bone.name
                pose_bone = active_obj.pose.bones.get(active_bone.name)
                on_bone_selection_changed(scene, pose_bone)
        else:
            scene.last_active_bone_name = ""
    else:
        scene.last_active_bone_name = ""


class BoneRetargetInfo(PropertyGroup):
    """Property group to store bone retarget data"""
    src_name: StringProperty(name="Bone source name")
    target_name : StringProperty(name="Bone target name",update=setup_operators.update_target_bone)
    rest_offset: FloatVectorProperty(name="Rest Offset",description="Quaternion difference between the two bones in their respective rest position",size=4,default=(1.0, 0.0, 0.0, 0.0))
    roll_offset: FloatProperty(name="Roll Offset", description="Rotation offset along target's local Y axis to match source coordinate system", subtype="ANGLE", default=0)
    is_setup: BoolProperty(name="Is Recorded", default=False)
    offset_mode: EnumProperty(items=offset_items, description="Select the offset to apply after aligning bones.")
    corrective_offset : FloatVectorProperty(name="Corrective Offset", description="Additional corrective offset to apply after aligning bones.", size=4, default=(1.0, 0.0, 0.0, 0.0))

def register_retarget_properties():
    """Register retargeting properties"""

    bpy.types.Scene.retarget_bones = CollectionProperty(
        type=BoneRetargetInfo,
        name="Retarget Bones",
        description="A collection of all bones info"
    )



    bpy.types.Scene.retarget_bones_active_index = bpy.props.IntProperty(
        name="Bones Index",
        default=0,
        # update=setup_operators.on_shape_key_index_changed
    )

    bpy.types.Scene.retarget_is_recording = bpy.props.BoolProperty(
        name="Is Recording",
        default=False,
        description="Indicates if the user is currently recording an adjustement rotation"
    )

    bpy.types.Scene.retarget_current_initial_rotation = bpy.props.FloatVectorProperty(
        name="Initial Rotation",
        description="Stores the initial rotation of the bone when recording starts",
        size=4,
        default=(1.0, 0.0, 0.0, 0.0)
    )

    bpy.types.Scene.last_active_bone_name = bpy.props.StringProperty(
        default="",
        name="Last Selected Bone name"
    )

    bpy.types.Scene.retarget_source_armature = bpy.props.PointerProperty( 
        type=bpy.types.Object,
        name="Armature Source",
        poll=lambda self, obj: obj.type == 'ARMATURE' 
    )

    bpy.types.Scene.retarget_target_armature = bpy.props.PointerProperty( 
        type=bpy.types.Object,
        name="Armature Target",
        poll=lambda self, obj: obj.type == 'ARMATURE' 
    )
    
    bpy.types.Scene.retarget_json_path = bpy.props.StringProperty( 
        name="Chemin du fichier JSON",
        default="",
        subtype='FILE_PATH'
    )

def unregister_retarget_properties():
    """Unregister retargeting properties"""
    del bpy.types.Scene.retarget_source_armature 
    del bpy.types.Scene.retarget_target_armature 
    del bpy.types.Scene.retarget_json_path 

classes = (
    BoneRetargetInfo,
)

addon_modules = (
    ui,
    setup_operators,
    retarget_operators,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    for mod in addon_modules:
        mod.register()
    register_retarget_properties()

    if check_bone_selection_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(check_bone_selection_handler)

def unregister():
    if check_bone_selection_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(check_bone_selection_handler)
    unregister_retarget_properties()

    for mod in reversed(addon_modules):
        mod.unregister()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()