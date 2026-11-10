"""Run every test: the plain-Python unit tests, then the headless Blender tests.

    python tests/run_tests.py [--blender <blender.exe>] [--spikes <folder with phase0/out and phase1/out>]
                              [--kimodo-python <Kimodo venv python.exe>] [--models-folder <folder>]
                              [--rigs <rigs.json>] [--gui]

Blender 5.2+ is needed (default: the BLENDER environment variable, else the standard Windows install path).
The unit tests run with Blender's own Python (it has numpy), found next to blender.exe.
The chain tests need the spike outputs (not committed): they are skipped when missing. Default: spikes/ in this
repository, or the RETARGETOR_SPIKES environment variable.
The Kimodo tests run only with --kimodo-python (or the RETARGETOR_KIMODO_PYTHON environment variable): the
conversions against Kimodo itself, then generations on the GPU (a few minutes).
--gui also runs the tests needing Blender's interface (the prompt segments with the mouse): a Blender window
opens for about a minute, with its own empty user folder (BLENDER_USER_RESOURCES), so your preferences can't be
touched, and simulated events (the real mouse and keyboard are ignored meanwhile).
--rigs: a JSON mapping the file keys of tests/fixtures/real_rigs.json to the rigs' files on this machine (not
committed; default: the RETARGETOR_RIGS environment variable): each rig is set up, checked and generated on, with
Kimodo too when --kimodo-python is given. Rigs whose file is missing are skipped.
--models-folder: a models' folder where the add-on installed Kimodo (default: the RETARGETOR_MODELS_FOLDER environment
variable): its setup is checked and a generation runs with it (GPU). Nothing is installed by the tests.
The migration test builds a legacy file with the add-on as it was before Phase 2 (commit LEGACY_COMMIT).
"""
import argparse
import glob
import os
import subprocess
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BLENDER_TESTS = os.path.join(REPO, "tests", "blender")
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
# Last commit before the Phase 2 refactor: its add-on stores the setup in scene.retarget_*
LEGACY_COMMIT = "62864b7"
LEGACY_FILES = ["__init__.py", "setup_operators.py", "retarget_operators.py", "ui.py"]


def run_blender(blender, script, args=(), blend=None, env=None):
    command = [blender, "-b", "--factory-startup"] + ([blend] if blend else [])
    command += ["--python", os.path.join(BLENDER_TESTS, script), "--"] + list(args)
    result = subprocess.run(command, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    lines = [line for line in result.stdout.splitlines() if line.startswith(("[ok", "[FAIL", "test_", "FINDING"))]
    print("\n".join(lines))
    ok = result.returncode == 0 and any(line.endswith(": OK") for line in lines)
    if not ok:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
    return ok


def run_blender_gui(blender, script, blend, env, scratch):
    """A test in Blender's interface, with simulated events and a user folder of its own (never the real one)"""
    user = os.path.join(scratch, "gui_user_resources")
    os.makedirs(user, exist_ok=True)
    env = dict(env, BLENDER_USER_RESOURCES=user)
    command = [blender, "--factory-startup", "-y", "--enable-event-simulate", "--window-geometry", "0", "0", "1600",
               "900", blend, "--python", os.path.join(BLENDER_TESTS, script)]
    result = subprocess.run(command, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace",
                            timeout=300)
    lines = [line for line in result.stdout.splitlines() if line.startswith(("[ok", "[FAIL", "test_"))]
    print("\n".join(lines))
    ok = result.returncode == 0 and any(line.endswith(": OK") for line in lines)
    if not ok:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
    return ok


def blender_python(blender):
    """The Python executable shipped with Blender: <blender dir>/<version>/python/bin/python.exe"""
    found = sorted(glob.glob(os.path.join(os.path.dirname(blender), "*", "python", "bin", "python*")))
    found = [path for path in found if os.path.basename(path).lower() in ("python.exe", "python3", "python")]
    if not found:
        raise SystemExit(f"Blender's Python not found next to {blender}")
    return found[-1]


def run_unit_tests(python):
    result = subprocess.run([python, "-I", "-m", "unittest", "discover", "-s", os.path.join(REPO, "tests", "unit")],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "")
    if result.returncode != 0:
        print(result.stderr[-3000:])
    return result.returncode == 0


def run_kimodo_tests(args, env, scratch, rig_file, ik_rig_file):
    """Kimodo: conversions against Kimodo itself (no GPU), then generations on the Phase 1 rig (GPU)"""
    results = {}
    command = [args.kimodo_python, "-I", os.path.join(REPO, "tests", "kimodo", "test_kimodo_reference.py")]
    result = subprocess.run(command, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    print(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "")
    if result.returncode != 0:
        print(result.stderr[-3000:])
    results["kimodo_reference"] = result.returncode == 0

    out_dir = os.path.join(scratch, "kimodo")
    os.makedirs(out_dir)
    base_args = ["base", args.kimodo_python, out_dir]
    spike_result = os.path.join(args.spikes, "phase1", "out", "result.blend")
    if os.path.exists(spike_result):
        dump = os.path.join(out_dir, "spike_rig_result.json")
        run_blender(args.blender, "dump_pose.py", ["rig", dump, "1", "120"], blend=spike_result)
        base_args.append(dump)
    results["kimodo_base"] = run_blender(args.blender, "test_generate_kimodo.py", base_args, blend=rig_file, env=env)
    for mode in ("heading", "fps24", "range", "ik", "partial", "segments", "segment"):
        results[f"kimodo_{mode}"] = run_blender(args.blender, "test_generate_kimodo.py",
                                                [mode, args.kimodo_python, out_dir],
                                                blend=ik_rig_file if mode in ("ik", "segments", "segment") else rig_file,
                                                env=env)
    return results


def run_real_rigs(args, env):
    """tests/blender/test_rigs.py on each rig of tests/fixtures/real_rigs.json present on this machine"""
    import json
    results = {}
    with open(os.path.join(REPO, "tests", "fixtures", "real_rigs.json"), encoding="utf-8") as f:
        manifest = json.load(f)["rigs"]
    paths = {}
    if args.rigs and os.path.exists(args.rigs):
        with open(args.rigs, encoding="utf-8") as f:
            paths = json.load(f)
    for rig in manifest:
        name = f"rig_{rig['object']}"
        path = paths.get(rig["file"])
        if not path or not os.path.exists(path):
            print(f"{name}: SKIPPED, no file for '{rig['file']}' (--rigs)")
            results[name] = None
            continue
        test_args = [rig["object"], rig["expect"]] + ([args.kimodo_python] if args.kimodo_python else [])
        if rig.get("fbx"):
            results[name] = run_blender(args.blender, "test_rigs.py", test_args + ["--fbx", path], env=env)
        else:
            results[name] = run_blender(args.blender, "test_rigs.py", test_args, blend=path, env=env)
    return results


def extract_legacy_addon(folder):
    archive = subprocess.run(["git", "-C", REPO, "archive", LEGACY_COMMIT, "--"] + LEGACY_FILES,
                             capture_output=True, check=True).stdout
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(folder, filter="data")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", default=os.environ.get("BLENDER", DEFAULT_BLENDER))
    parser.add_argument("--spikes", default=os.environ.get("RETARGETOR_SPIKES", os.path.join(REPO, "spikes")))
    parser.add_argument("--kimodo-python", default=os.environ.get("RETARGETOR_KIMODO_PYTHON"))
    parser.add_argument("--models-folder", default=os.environ.get("RETARGETOR_MODELS_FOLDER"),
                        help="models' folder where the add-on installed Kimodo")
    parser.add_argument("--rigs", default=os.environ.get("RETARGETOR_RIGS"),
                        help="JSON mapping the files of tests/fixtures/real_rigs.json to this machine's paths")
    parser.add_argument("--gui", action="store_true", help="also run the tests needing Blender's interface")
    args = parser.parse_args()

    results = {}
    results["unit"] = run_unit_tests(blender_python(args.blender))

    env = dict(os.environ, RETARGETOR_SPIKES=args.spikes)
    if args.models_folder:
        env["RETARGETOR_MODELS_FOLDER"] = args.models_folder
    with tempfile.TemporaryDirectory(prefix="retargetor_tests_") as scratch:
        results["panel"] = run_blender(args.blender, "test_panel.py", [scratch], env=env)
        results["segments"] = run_blender(args.blender, "test_segments.py", env=env)
        results["pose_io"] = run_blender(args.blender, "test_pose_io.py", env=env)
        results["skeleton_io"] = run_blender(args.blender, "test_skeleton_io.py", env=env)
        results["rig_setup"] = run_blender(args.blender, "test_rig_setup.py", env=env)
        setup_dir = os.path.join(scratch, "model_setup")
        os.makedirs(setup_dir)
        results["model_setup"] = run_blender(args.blender, "test_model_setup.py",
                                             [setup_dir] + ([args.kimodo_python] if args.kimodo_python else []),
                                             env=env)
        lib_dir = os.path.join(scratch, "library")
        os.makedirs(lib_dir)
        results["library_override"] = run_blender(args.blender, "test_library_override.py", [lib_dir], env=env)

        # The Phase 1 Rigify rig with its key poses, made fresh (needs only Rigify)
        rig_dir = os.path.join(scratch, "rig")
        os.makedirs(rig_dir)
        run_blender(args.blender, os.path.join(REPO, "spikes", "phase1", "make_rig.py"), [rig_dir])
        test_rig = os.path.join(rig_dir, "rig_keyposes.blend")
        if os.path.exists(test_rig):
            results["generate"] = run_blender(args.blender, "test_generate.py", blend=test_rig, env=env)
            # Its hips control turned on the key poses: between torso (written) and ORG-spine (read)
            results["rig_rigify"] = run_blender(args.blender, "test_rigs.py",
                                                ["rig", "Rigify", "--pose", "hips"],
                                                blend=test_rig, env=env)
            if args.gui:
                results["segment_mouse"] = run_blender_gui(args.blender, "test_segment_mouse.py", test_rig, env,
                                                           scratch)
            # The same key poses made with the IK controls only
            run_blender(args.blender, os.path.join(REPO, "spikes", "phase1", "make_rig_ik.py"),
                        [rig_dir, "1", "61", "120"], blend=test_rig)
            ik_rig = os.path.join(rig_dir, "rig_keyposes_ik.blend")
            results["generate_ik"] = (os.path.exists(ik_rig)
                                      and run_blender(args.blender, "test_generate_ik.py", blend=ik_rig, env=env))
        else:
            print("generate: the test rig could not be made (spikes/phase1/make_rig.py)")
            results["generate"] = False

        legacy_addon, legacy_out = os.path.join(scratch, "legacy_addon"), os.path.join(scratch, "legacy")
        os.makedirs(legacy_addon)
        os.makedirs(legacy_out)
        extract_legacy_addon(legacy_addon)
        run_blender(args.blender, "legacy_setup.py", [legacy_addon, legacy_out], env=env)
        results["migration"] = run_blender(args.blender, "test_migration.py", [legacy_out], env=env)

        phase1 = os.path.join(args.spikes, "phase1", "out")
        for mode, rig_file, spike_dir in (("fk", "rig_keyposes.blend", phase1),
                                          ("ik2fk", "rig_keyposes_ik.blend", os.path.join(phase1, "ik2fk"))):
            needed = [os.path.join(phase1, rig_file), os.path.join(spike_dir, "rig_to_soma.blend"),
                      os.path.join(spike_dir, "result.blend"), os.path.join(spike_dir, "generated.bvh"),
                      os.path.join(args.spikes, "phase0", "out", "soma_reference.blend")]
            missing = [p for p in needed if not os.path.exists(p)]
            if missing:
                print(f"chain {mode}: SKIPPED, missing spike outputs: {missing}")
                results[f"chain_{mode}"] = None
                continue
            reference = os.path.join(scratch, f"reference_{mode}")
            os.makedirs(reference)
            run_blender(args.blender, "dump_pose.py", ["SOMA", os.path.join(reference, "soma_keyposes.json"), "1", "120"],
                        blend=os.path.join(spike_dir, "rig_to_soma.blend"))
            run_blender(args.blender, "dump_pose.py", ["rig", os.path.join(reference, "rig_result.json"), "1", "120"],
                        blend=os.path.join(spike_dir, "result.blend"))
            results[f"chain_{mode}"] = run_blender(args.blender, "test_chain.py", [mode, spike_dir, reference],
                                                   blend=os.path.join(phase1, rig_file), env=env)

        results.update(run_real_rigs(args, env))

        if args.kimodo_python and os.path.exists(test_rig):
            results.update(run_kimodo_tests(args, env, scratch, test_rig,
                                            os.path.join(rig_dir, "rig_keyposes_ik.blend")))
        if args.models_folder and os.path.exists(test_rig):
            # Kimodo as the add-on installed it
            out_dir = os.path.join(scratch, "kimodo_installed")
            os.makedirs(out_dir)
            results["kimodo_installed"] = run_blender(args.blender, "test_generate_kimodo.py",
                                                      ["base", "managed", out_dir], blend=test_rig, env=env)

    print("\nSummary:")
    for name, ok in results.items():
        print(f"  {name}: {'skipped' if ok is None else 'OK' if ok else 'FAILED'}")
    sys.exit(0 if all(ok is not False for ok in results.values()) else 1)


if __name__ == "__main__":
    main()
