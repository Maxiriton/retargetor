# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


#type: ignore

bl_info = {
    "name": "Retargetor",
    "author": "Henri Hebeisen",
    "description": "Retarget animation between armatures with different rest poses",
    "blender": (5, 2, 0),
    "version": (0, 0, 1),
    "location": "View3D > Sidebar > Retarget Tool",
    "warning": "",
    "category": "Animation",
}

import bpy
from bpy.app.handlers import persistent

from . import preferences
from . import properties
from . import migration
from . import ui
from . import retarget_operators
from . import setup_operators
from . import profile_operators
from . import generate_operators
from . import generated_keys
from . import segment_operators
from . import segment_draw
from . import segment_mouse
from .properties import get_character

# Name of the last active bone seen by the selection handler (UI state, not saved)
_last_active_bone_name = ""


def set_active_item(state, field, bone_name):
    """Make the list item whose `field` ("src_name" or "target_name") equals bone_name the active one"""
    for index, item in enumerate(state.bones):
        if getattr(item, field) == bone_name:
            if state.bones_active_index != index:
                state.bones_active_index = index
            return True
    return False


def on_bone_selection_changed(context, bone_name):
    target_obj, state = get_character(context)
    if target_obj is None or not target_obj.is_editable:
        return
    active_obj = context.active_object
    if active_obj == state.source:
        set_active_item(state, "src_name", bone_name)
    elif active_obj == target_obj:
        set_active_item(state, "target_name", bone_name)


@persistent
def check_bone_selection_handler(scene):
    # Properties are only written when the value really changes:
    # writing from a depsgraph handler can trigger another depsgraph update.
    global _last_active_bone_name
    context = bpy.context
    active_obj = context.active_object
    if active_obj and active_obj.type == 'ARMATURE' and active_obj.mode == 'POSE':
        active_bone = active_obj.data.bones.active

        if active_bone:
            if active_bone.name != _last_active_bone_name:
                _last_active_bone_name = active_bone.name
                on_bone_selection_changed(context, active_bone.name)
        else:
            _last_active_bone_name = ""
    else:
        _last_active_bone_name = ""


addon_modules = (
    preferences,
    properties,
    migration,
    ui,
    setup_operators,
    retarget_operators,
    profile_operators,
    generate_operators,
    generated_keys,
    segment_operators,
    segment_draw,
    segment_mouse,
)

def register():
    for mod in addon_modules:
        mod.register()

    if check_bone_selection_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(check_bone_selection_handler)

def unregister():
    if check_bone_selection_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(check_bone_selection_handler)

    for mod in reversed(addon_modules):
        mod.unregister()


if __name__ == "__main__":
    register()
