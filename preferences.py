# type: ignore
"""Add-on preferences: the active backend, the developer option and each backend's own settings.

Each backend declares its settings (backends.base.Backend.settings_class); they are added here as
settings_<backend id>, so nothing specific to a backend is written in this file.
"""
import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty
from bpy.types import AddonPreferences

from .backends import registry

ADDON_ID = __package__

# Enum items are kept alive here: Blender doesn't keep the strings returned by an items callback
_backend_items = []


def backend_items(self, _context):
    _backend_items.clear()
    for number, backend in enumerate(registry.BACKENDS):
        if self.developer or not backend.developer_only:
            _backend_items.append((backend.id, backend.label, backend.description, number))
    return _backend_items


def _settings_classes():
    return [(b, b.settings_class()) for b in registry.BACKENDS if b.settings_class() is not None]


class RTGTR_Preferences(AddonPreferences):
    bl_idname = ADDON_ID

    backend: EnumProperty(name="Backend", items=backend_items,
                          description="Motion model generating the in-betweens")
    developer: BoolProperty(name="Developer", default=False,
                            description="Show the backends made for testing (interpolation without any model)")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "backend")
        backend = active_backend(context)
        settings = backend_settings(context, backend)
        if settings is not None:
            box = layout.box()
            box.label(text=f"{backend.label} settings")
            backend.draw_settings(box, settings)
        layout.prop(self, "developer")


def get_preferences(context):
    """The add-on preferences, or None if the add-on isn't enabled through Blender (some scripts and tests)"""
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon is not None else None


def active_backend(context):
    """The backend chosen in the preferences; the first visible backend if that one is hidden or unknown"""
    prefs = get_preferences(context)
    developer = prefs.developer if prefs is not None else False
    visible = registry.visible(developer)
    if prefs is not None:
        for backend in visible:
            if backend.id == prefs.backend:
                return backend
    return visible[0]


def backend_settings(context, backend):
    """The backend's settings (its settings_class instance), or None"""
    prefs = get_preferences(context)
    if prefs is None:
        return None
    return getattr(prefs, f"settings_{backend.id}", None)


def register():
    for backend, cls in _settings_classes():
        bpy.utils.register_class(cls)
        RTGTR_Preferences.__annotations__[f"settings_{backend.id}"] = PointerProperty(type=cls)
    bpy.utils.register_class(RTGTR_Preferences)


def unregister():
    bpy.utils.unregister_class(RTGTR_Preferences)
    for backend, cls in reversed(_settings_classes()):
        RTGTR_Preferences.__annotations__.pop(f"settings_{backend.id}", None)
        bpy.utils.unregister_class(cls)
    registry.stop_all()
