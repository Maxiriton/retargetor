"""Run every test: the plain-Python unit tests, then the headless Blender tests.

    python tests/run_tests.py [--blender <blender.exe>] [--spikes <folder with phase0/out and phase1/out>]

Blender 5.1+ is needed (default: the BLENDER environment variable, else the standard Windows install path).
The chain tests need the spike outputs (not committed): they are skipped when missing. Default: spikes/ in this
repository, or the RETARGETOR_SPIKES environment variable.
The migration test builds a legacy file with the add-on as it was before Phase 2 (commit LEGACY_COMMIT).
"""
import argparse
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BLENDER_TESTS = os.path.join(REPO, "tests", "blender")
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
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
    args = parser.parse_args()

    results = {}
    suite = unittest.defaultTestLoader.discover(os.path.join(REPO, "tests", "unit"))
    results["unit"] = unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()

    env = dict(os.environ, RETARGETOR_SPIKES=args.spikes)
    with tempfile.TemporaryDirectory(prefix="retargetor_tests_") as scratch:
        results["panel"] = run_blender(args.blender, "test_panel.py", [scratch], env=env)
        results["pose_io"] = run_blender(args.blender, "test_pose_io.py", env=env)
        lib_dir = os.path.join(scratch, "library")
        os.makedirs(lib_dir)
        results["library_override"] = run_blender(args.blender, "test_library_override.py", [lib_dir], env=env)

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

    print("\nSummary:")
    for name, ok in results.items():
        print(f"  {name}: {'skipped' if ok is None else 'OK' if ok else 'FAILED'}")
    sys.exit(0 if all(ok is not False for ok in results.values()) else 1)


if __name__ == "__main__":
    main()
