"""How the rig profile (Armature data) and the character state (Object) behave on a rig linked from a library.

    blender -b --factory-startup --python tests/blender/test_library_override.py -- <scratch dir>

1. lib.blend: a character collection with an armature, its rig profile and a character state.
2. A shot file links the collection: the profile can be read, not edited.
3. Library override of the collection (default, then fully editable), and an override where the armature
   data is overridden too: what can be edited, and what survives a save and reload.
4. The library's profile changes: what the shot files see.
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402

FINDINGS = []
VARIANTS = {
    "default": "default override",
    "full": "fully editable override",
    "data": "override with the armature data overridden too",
}


def finding(text):
    FINDINGS.append(text)
    print(f"FINDING: {text}")


def new_file():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bootstrap.register_addon()


def make_library(path):
    new_file()
    from retargetor.core import profile as core_profile
    scene = bpy.context.scene
    target = bootstrap.make_armature("CHAR_rig", bootstrap.TARGET_BONES)
    source = bootstrap.make_armature("CHAR_source", bootstrap.SOURCE_BONES)
    character = bpy.data.collections.new("Character")
    scene.collection.children.link(character)
    for obj in (target, source):
        scene.collection.objects.unlink(obj)
        character.objects.link(obj)

    rig_profile = core_profile.RigProfile(
        roles=[core_profile.RoleBinding("hips", "hips", "hips"), core_profile.RoleBinding("upper_arm.L", "arm.L", "arm.L")],
        limbs=[core_profile.LimbSnap("arm.L", "spine", "IK_FK", 1.0, [core_profile.FkPair("arm.L", "arm.L")])],
    )
    target.data.retargetor_profile.from_core(rig_profile)
    target.retargetor.source = source
    target.retargetor.translation_scale = 1.5
    item = target.retargetor.bones.add()
    item.src_name, item.target_name = "Hips", "hips"
    bpy.ops.wm.save_as_mainfile(filepath=path)


def link_character(lib_path):
    with bpy.data.libraries.load(lib_path, link=True) as (_data_from, data_to):
        data_to.collections = ["Character"]
    character = data_to.collections[0]
    instance = bpy.data.objects.new("Character_instance", None)
    instance.instance_type = 'COLLECTION'
    instance.instance_collection = character
    bpy.context.scene.collection.objects.link(instance)
    return character, instance


def try_set(obj, attr, value):
    try:
        setattr(obj, attr, value)
        return getattr(obj, attr) == value
    except (AttributeError, TypeError, RuntimeError):
        return False


def try_add(collection):
    try:
        collection.add()
        return True
    except (AttributeError, TypeError, RuntimeError):
        return False


def override_rig(lib_path, fully_editable):
    character, instance = link_character(lib_path)
    scene, view_layer = bpy.context.scene, bpy.context.view_layer
    override = character.override_hierarchy_create(scene, view_layer, reference=instance,
                                                   do_fully_editable=fully_editable)
    if instance.name in scene.collection.objects:
        scene.collection.objects.unlink(instance)
    rig = next(o for o in override.all_objects if o.name.startswith("CHAR_rig"))
    return rig


def main(scratch):
    checks = bootstrap.Checks("test_library_override")
    lib_path = os.path.join(scratch, "lib.blend")
    make_library(lib_path)

    # 2. Linked only
    new_file()
    character, _instance = link_character(lib_path)
    rig = character.objects["CHAR_rig"]
    profile = rig.data.retargetor_profile
    checks.check(rig.library is not None and not rig.data.is_editable, "linked armature is not editable")
    checks.check([b.read_bone for b in profile.to_core().roles] == ["hips", "arm.L"], "linked profile can be read")
    checks.check(rig.retargetor.translation_scale == 1.5 and len(rig.retargetor.bones) == 1,
                 "linked character state can be read")
    edited = try_set(profile.roles[0], "read_bone", "spine")
    linked_path = os.path.join(scratch, "shot_linked.blend")
    bpy.ops.wm.save_as_mainfile(filepath=linked_path)
    bpy.ops.wm.open_mainfile(filepath=linked_path)
    kept = bpy.data.objects["CHAR_rig"].data.retargetor_profile.roles[0].read_bone == "spine"
    checks.check(not kept, "linked profile: an edit is not saved")
    finding(f"Linked rig (no override): the profile and the character state come from the library. Python can "
            f"change them in memory (edit accepted={edited}) but nothing is saved (kept after reload={kept}); "
            f"the UI greys them out.")

    for variant in VARIANTS:
        label = VARIANTS[variant]
        shot_path = os.path.join(scratch, f"shot_{variant}.blend")
        new_file()
        rig = override_rig(lib_path, fully_editable=variant == "full")
        if variant == "data":
            rig.data = rig.data.override_create(remap_local_usages=True)
        data_override = rig.data.override_library
        system = data_override is not None and data_override.is_system_override
        finding(f"{label}: object override={rig.override_library is not None}, "
                f"armature data override={data_override is not None}, system override={system}, "
                f"armature is_editable={rig.data.is_editable}")

        profile = rig.data.retargetor_profile
        state = rig.retargetor
        profile_edit = try_set(profile.roles[0], "write_bone", "spine")
        profile_insert = try_add(profile.roles)
        state_edit = try_set(state, "translation_scale", 2.0)
        state_insert = try_add(state.bones)
        if state_insert:
            state.bones[-1].src_name = "Spine"
            state.bones[-1].target_name = "spine"
        finding(f"{label}: edit a profile value={profile_edit}, add a profile role={profile_insert}, "
                f"edit the character state={state_edit}, add a bone list row={state_insert}")

        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        checks.check(bpy.ops.retargetor.profile_import_json.poll() == rig.data.is_editable,
                     f"{label}: Import Profile is available only when the armature data is editable")

        bpy.ops.wm.save_as_mainfile(filepath=shot_path)
        bpy.ops.wm.open_mainfile(filepath=shot_path)
        rig = next(o for o in bpy.data.objects if o.name.startswith("CHAR_rig") and o.override_library)
        profile, state = rig.data.retargetor_profile, rig.retargetor
        kept_profile = profile.roles[0].write_bone == "spine"
        kept_insert = len(profile.roles) == 3
        kept_state = state.translation_scale == 2.0
        kept_rows = [i.src_name for i in state.bones]
        finding(f"{label}, after save and reload: profile edit kept={kept_profile}, added role kept={kept_insert}, "
                f"state edit kept={kept_state}, bone list={kept_rows}")
        checks.check(kept_state and kept_rows == ["Hips", "Spine"], f"{label}: character state edits survive a reload")
        if variant == "data":
            checks.check(kept_profile and kept_insert, f"{label}: profile edits survive a reload")
        else:
            checks.check(not rig.data.is_editable and not kept_profile,
                         f"{label}: the armature data stays linked, the profile is read-only")

    # 4. The library's profile changes
    bpy.ops.wm.open_mainfile(filepath=lib_path)
    rig = bpy.data.objects["CHAR_rig"]
    rig.data.retargetor_profile.roles[1].read_bone = "forearm.L"
    rig.data.retargetor_profile.roles[0].write_bone = "hips_lib"
    bpy.ops.wm.save_as_mainfile(filepath=lib_path)
    for name in VARIANTS:
        bpy.ops.wm.open_mainfile(filepath=os.path.join(scratch, f"shot_{name}.blend"))
        rig = next(o for o in bpy.data.objects if o.name.startswith("CHAR_rig") and o.override_library)
        roles = rig.data.retargetor_profile.roles
        finding(f"{name} override after the library changed: untouched role follows the library="
                f"{roles[1].read_bone == 'forearm.L'}, overridden value kept={roles[0].write_bone}")
        checks.check(roles[1].read_bone == "forearm.L", f"{name} override: untouched profile values follow the library")
        if name == "data":
            checks.check(roles[0].write_bone == "spine", f"{name} override: the local profile edit wins over the library")

    print("\n".join(["", "Library override findings:"] + [f"- {f}" for f in FINDINGS]))
    checks.finish()


if __name__ == "__main__":
    main(bootstrap.script_args()[0])
