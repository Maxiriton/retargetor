"""The models' setup in Blender: the preferences' Models section, a model not installed, an existing environment
checked, the worker's command.

    blender -b --factory-startup --python tests/blender/test_model_setup.py -- <scratch dir> [<Kimodo python>]

Nothing is downloaded: the install itself is tested with fake steps in tests/unit/test_setup.py, and for real only by
hand (it downloads several GB). With a Kimodo environment, its setup is checked (a few seconds: it imports torch).
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402
from test_panel import CheckingLayout  # noqa: E402


def refused(operator, **kwargs):
    """The operator stops with an error"""
    try:
        return operator(**kwargs) == {'CANCELLED'}
    except RuntimeError:
        return True


def draw(function, *args):
    errors = []
    function(CheckingLayout(errors), *args)
    return errors


def main(scratch, kimodo_python=None):
    checks = bootstrap.Checks("test_model_setup")
    bootstrap.register_addon()
    from retargetor import model_setup, ui
    from retargetor.backends import registry
    from retargetor.backends.setup import checks as setup_checks

    prefs = bootstrap.set_backend("kimodo")
    prefs.models_folder = os.path.join(scratch, "models")
    kimodo = registry.get("kimodo")
    interpolate = registry.get("interpolate")
    context = bpy.context

    checks.check(hasattr(prefs, "setup_kimodo") and not hasattr(prefs, "setup_interpolate"),
                 "only a backend with something to install gets an environment setting")
    checks.check(model_setup.models_root(context) == os.path.normpath(os.path.join(scratch, "models")),
                 "the models' folder comes from the preferences")
    checks.check(model_setup.setup_problem(context, kimodo) == "Not installed", "a model never installed says so")
    try:
        model_setup.worker_for(context, kimodo)
        checks.check(False, "no worker for a model not installed")
    except ValueError as e:
        checks.check("isn't installed" in str(e), f"no worker for a model not installed ({e})")
    checks.check(model_setup.setup_problem(context, interpolate) == "", "the interpolation backend needs nothing")
    worker = model_setup.worker_for(context, interpolate)
    checks.check(worker.command[0] == sys.executable, "the interpolation worker runs with Blender's Python")

    checks.check(draw(model_setup.draw_models, context, prefs) == [], "the Models section draws")
    prefs.developer = True
    checks.check(draw(model_setup.draw_models, context, prefs) == [], "the Models section draws, developer on")
    header = type("Header", (), {"layout": None})()
    errors = []
    header.layout = CheckingLayout(errors)
    ui.draw_editor_header(header, context)
    checks.check(errors == [], "the editors' header draws with a model not installed")

    if not bpy.app.online_access:
        checks.check(refused(bpy.ops.retargetor.model_install, backend_id="kimodo"),
                     "no install without online access")

    # An existing environment
    setup = prefs.setup_kimodo
    setup.environment = 'EXISTING'
    setup.python = os.path.join(scratch, "nowhere", "python.exe")
    checks.check(model_setup.setup_problem(context, kimodo) == "Python not found", "an existing Python not found")
    run = model_setup.start_check(context, kimodo).wait(30)
    checks.check(run.items[0].fix == setup_checks.FIX_PYTHON, "the check asks for another Python")
    checks.check(refused(bpy.ops.retargetor.model_remove, backend_id="kimodo"),
                 "an existing environment isn't removed")

    if kimodo_python:
        setup.python = kimodo_python
        checks.check(model_setup.setup_problem(context, kimodo) == "", "an existing Kimodo environment is used")
        worker = model_setup.worker_for(context, kimodo)
        venv = os.path.dirname(os.path.dirname(kimodo_python))
        checks.check(os.path.normcase(worker.command[0]) == os.path.normcase(os.path.normpath(kimodo_python))
                     and os.path.normcase(worker.env["KIMODO_TEXT_ENCODER_DIR"])
                     == os.path.normcase(os.path.join(venv, "llm2vec-model")),
                     "the Kimodo worker gets the existing environment's text encoder")
        run = model_setup.start_check(context, kimodo).wait(300)
        for item in run.items:
            print(f"    {item.level:8} {item.label}: {item.message}")
        checks.check(setup_checks.ready(run.items), "the existing Kimodo environment is ready")
        checks.check(draw(model_setup.draw_models, context, prefs) == [], "the Models section draws a check")

    installed = os.environ.get("RETARGETOR_MODELS_FOLDER")
    if installed:
        # Kimodo as the add-on installed it
        setup.environment = 'MANAGED'
        prefs.models_folder = installed
        checks.check(model_setup.setup_problem(context, kimodo) == "", "the installed Kimodo is found")
        layout = model_setup.layout_for(context, kimodo)
        worker = model_setup.worker_for(context, kimodo)
        checks.check(os.path.normcase(worker.env["KIMODO_TEXT_ENCODER_DIR"])
                     == os.path.normcase(os.path.join(layout.backend_dir, "llm2vec-model")),
                     "the installed Kimodo's worker gets its text encoder")
        run = model_setup.start_check(context, kimodo).wait(300)
        for item in run.items:
            print(f"    {item.level:8} {item.label}: {item.message}")
        checks.check(setup_checks.ready(run.items), "the installed Kimodo is ready")
    checks.finish()


if __name__ == "__main__":
    args = bootstrap.script_args()
    main(args[0], args[1] if len(args) > 1 else None)
