import os
import bpy


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

