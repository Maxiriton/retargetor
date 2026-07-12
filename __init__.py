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

#type: ignore

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

from . import ui
from . import retarget_operators


def register_retarget_properties():
    """Register retargeting properties"""
    bpy.types.Scene.retarget_source_armature = bpy.props.PointerProperty( 
        type=bpy.types.Object,
        name="Armature Source",
        poll=lambda self, obj: obj.type == 'ARMATURE' 
    )

    bpy.types.Scene.lerp_rotation = bpy.props.FloatProperty( 
        name="Lerp Rotation",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        description="Lerp factor for rotation blending between source and target bones",
        update=retarget_operators.callback_update_lerp_property)

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

# classes = ()

addon_modules = (
    ui,
    retarget_operators
)

def register():
    # for cls in classes:
    #     bpy.utils.register_class(cls)

    for mod in addon_modules:
        mod.register()
    register_retarget_properties()

def unregister():
    unregister_retarget_properties()

    for mod in reversed(addon_modules):
        mod.unregister()

    # for cls in reversed(classes):
    #     bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()