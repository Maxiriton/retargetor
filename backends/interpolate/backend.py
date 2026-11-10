"""What the add-on knows about the interpolation backend."""
from ...core.roles import ROLES
from ..base import Backend, Capabilities, blender_python, worker_script


class InterpolateBackend(Backend):
    id = "interpolate"
    label = "Interpolation (test)"
    description = "Spherical interpolation between the key poses, without any model. For tests"
    developer_only = True
    # The motion around a range: the frames next to it are interpolated from, like key poses
    capabilities = Capabilities(streaming=True, min_key_poses=2, motion_context=True)
    # Its skeleton has one joint per role, named after the role
    joint_map = {role.id: role.id for role in ROLES}
    load_timeout = 60.0
    generate_timeout = 120.0

    def worker_command(self, python, settings, layout):
        return [blender_python(), "-I", "-u", worker_script(__file__)], {}
