"""The models' setup (backends/setup): machine, paths, weights on disk, uv, the installer's steps, the check. No
Blender, no download: the commands are replaced by fakes.

Run with Blender's Python (tests/run_tests.py does it), from the repository root:
    <blender>/5.2/python/bin/python.exe -I -m unittest discover -s tests/unit
"""
import json
import os
import sys
import tempfile
import unittest
import zipfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from backends.kimodo import install as kimodo_install  # noqa: E402
from backends.setup import checks, installer, machine, paths, signin, uv  # noqa: E402
from backends.setup import weights as weights_status  # noqa: E402
from backends.setup.spec import Gpu, Machine, Packages, Requirements, Weights, step_key  # noqa: E402

RTX3090 = Gpu("NVIDIA GeForce RTX 3090", 24576, (8, 6), "610.88")
RTX5090 = Gpu("NVIDIA GeForce RTX 5090", 32607, (12, 0), "610.88")
WINDOWS_3090 = Machine("windows", "x86_64", (RTX3090,))


class TestMachine(unittest.TestCase):
    def test_nvidia_smi(self):
        gpus = machine.parse_nvidia_smi("NVIDIA GeForce RTX 3090, 24576, 610.88, 8.6\n\nbroken line\n"
                                        "NVIDIA RTX A6000, 49140, 610.88, 8.6\n")
        self.assertEqual(gpus[0], RTX3090)
        self.assertEqual(len(gpus), 2)
        self.assertEqual(Machine("linux", "x86_64", gpus).gpu.name, "NVIDIA RTX A6000")
        self.assertIsNone(Machine("macos", "arm64").gpu)
        self.assertEqual(machine.parse_nvidia_smi("GPU, 8192, 500.1, [N/A]")[0].compute_capability, None)

    def test_names(self):
        self.assertEqual(machine.system_name("win32"), "windows")
        self.assertEqual(machine.system_name("darwin"), "macos")
        self.assertEqual(machine.system_name("linux"), "linux")
        self.assertEqual(machine.arch_name("AMD64"), "x86_64")
        self.assertEqual(machine.arch_name("aarch64"), "arm64")


class TestPaths(unittest.TestCase):
    def test_default_root(self):
        self.assertEqual(paths.default_root("windows", {"LOCALAPPDATA": r"C:\Users\A\AppData\Local"}),
                         os.path.join(r"C:\Users\A\AppData\Local", "Retargetor"))
        self.assertEqual(paths.default_root("linux", {}, home="/home/a"),
                         os.path.join("/home/a", ".local", "share", "retargetor"))
        self.assertEqual(paths.default_root("linux", {"XDG_DATA_HOME": "/data"}, home="/home/a"),
                         os.path.join("/data", "retargetor"))
        self.assertEqual(paths.default_root("macos", {}, home="/Users/a"),
                         os.path.join("/Users/a", "Library", "Application Support", "Retargetor"))

    def test_layout(self):
        layout = paths.Layout("/models", "kimodo", "windows")
        self.assertTrue(layout.python.endswith(os.path.join("models", "kimodo", "env", "Scripts", "python.exe")))
        self.assertTrue(paths.Layout("/m", "k", "linux").python.endswith(os.path.join("env", "bin", "python")))
        local = Weights("x", "org/x", 1.0, folder="enc")
        self.assertEqual(layout.weights_dir(local), os.path.join(layout.backend_dir, "enc"))
        self.assertIsNone(layout.weights_dir(Weights("x", "org/x", 1.0)))
        existing = paths.Layout("/models", "kimodo", "windows", weights_root="/venv")
        self.assertEqual(existing.weights_dir(local), os.path.join("/venv", "enc"))

    def test_env_root_and_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "Scripts"))
            open(os.path.join(folder, "pyvenv.cfg"), "w").close()
            self.assertEqual(paths.env_root(os.path.join(folder, "Scripts", "python.exe")), os.path.abspath(folder))
            self.assertEqual(paths.env_root(os.path.join(folder, "python.exe")), "")
        self.assertEqual(paths.hf_cache_dir({"HF_HOME": "/hf"}), os.path.join("/hf", "hub"))
        self.assertEqual(paths.hf_cache_dir({"HF_HUB_CACHE": "/c"}), "/c")
        self.assertEqual(paths.hf_cache_dir({}, home="/h"), os.path.join("/h", ".cache", "huggingface", "hub"))


def make_snapshot(cache, repo_id, files, commit="a" * 40, ref="main"):
    repo = paths.hf_repo_dir(repo_id, cache)
    os.makedirs(os.path.join(repo, "refs"), exist_ok=True)
    with open(os.path.join(repo, "refs", ref), "w") as f:
        f.write(commit)
    snapshot = os.path.join(repo, "snapshots", commit)
    for name, content in files.items():
        path = os.path.join(snapshot, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    return snapshot


class TestWeights(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "hub")
        self.layout = paths.Layout(os.path.join(self.tmp.name, "root"), "model", "windows")

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache(self):
        weights = Weights("Llama", "org/llama", 15.0, required_files=("config.json", "model.safetensors.index.json"))
        self.assertFalse(weights_status.status(weights, self.layout, self.cache).present)
        index = json.dumps({"weight_map": {"a": "model-1.safetensors", "b": "model-2.safetensors"}})
        snapshot = make_snapshot(self.cache, "org/llama", {"config.json": "{}", "model.safetensors.index.json": index,
                                                            "model-1.safetensors": "x"})
        status = weights_status.status(weights, self.layout, self.cache)
        self.assertFalse(status.present)
        self.assertEqual(status.missing, ["model-2.safetensors"])
        open(os.path.join(snapshot, "model-2.safetensors"), "w").close()
        status = weights_status.status(weights, self.layout, self.cache)
        self.assertTrue(status.present)
        self.assertEqual(status.revision, "a" * 40)
        # A pinned commit that isn't there
        pinned = Weights("Llama", "org/llama", 15.0, revision="b" * 40)
        self.assertFalse(weights_status.status(pinned, self.layout, self.cache).present)
        self.assertGreater(weights_status.repo_size_on_disk(weights, self.layout, self.cache), 0)

    def test_folder(self):
        weights = Weights("Encoder", "org/enc", 4.0, folder="enc", required_files=("model.safetensors",))
        self.assertFalse(weights_status.status(weights, self.layout, self.cache).present)
        os.makedirs(os.path.join(self.layout.backend_dir, "enc"))
        self.assertEqual(weights_status.status(weights, self.layout, self.cache).missing, ["model.safetensors"])
        open(os.path.join(self.layout.backend_dir, "enc", "model.safetensors"), "w").close()
        self.assertTrue(weights_status.status(weights, self.layout, self.cache).present)


def fake_wheel(path, system):
    name = "uv.exe" if system == "windows" else "uv"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"uv-{uv.UV_VERSION}.data/scripts/{name}", b"fake uv")
        archive.writestr("uv/__init__.py", b"")


class TestUv(unittest.TestCase):
    def test_install(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "source.whl")
            fake_wheel(source, "linux")
            digest = uv.sha256(source)

            def fetch(url, destination, progress, cancelled):
                with open(source, "rb") as f, open(destination, "wb") as out:
                    out.write(f.read())

            tools = os.path.join(folder, "tools")
            path = uv.install(tools, "linux", "x86_64", fetch=fetch, wheels={("linux", "x86_64"): ("url", digest)})
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"fake uv")
            self.assertEqual(path, uv.uv_path(tools, "linux"))
            # Already there: nothing fetched
            self.assertEqual(uv.install(tools, "linux", "x86_64", fetch=None), path)
            with self.assertRaisesRegex(uv.DownloadError, "checksum"):
                uv.install(os.path.join(folder, "other"), "linux", "x86_64", fetch=fetch,
                           wheels={("linux", "x86_64"): ("url", "0" * 64)})
            with self.assertRaisesRegex(uv.DownloadError, "No uv build"):
                uv.install(os.path.join(folder, "other"), "linux", "riscv", fetch=fetch)

    def test_pinned_wheels(self):
        for (system, arch), (url, digest) in uv.WHEELS.items():
            self.assertIn(f"uv-{uv.UV_VERSION}-", url)
            self.assertEqual(len(digest), 64)


class FakeInstaller(installer.Installer):
    """An Installer whose steps only record what they would run"""

    def __init__(self, *args, fail_on=None, **kwargs):
        self.calls = []
        self.fail_on = fail_on
        super().__init__(*args, **kwargs)

    def _record(self, name):
        self.calls.append(name)
        if name == self.fail_on:
            raise installer.InstallError(f"{name} failed")

    def _install_uv(self):
        self._record("uv")
        os.makedirs(os.path.dirname(self._uv), exist_ok=True)
        open(self._uv, "w").close()

    def _install_python(self):
        self._record("python")

    def _create_env(self):
        self._record("environment")
        os.makedirs(os.path.dirname(self.layout.python), exist_ok=True)
        open(self.layout.python, "w").close()

    def _install_packages(self, packages):
        self._record(packages.label)

    def _download(self, weights):
        self._record(weights.label)
        folder = self.layout.weights_dir(weights)
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(folder, "model.safetensors"), "w").close()


def requirements(torch="torch==2.5.1"):
    return Requirements("3.11", (Packages("PyTorch", (torch,)), Packages("Model", ("model",))),
                        (Weights("Weights", "org/w", 1.0, folder="w", required_files=("model.safetensors",)),),
                        imports=("torch",))


class TestInstaller(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.layout = paths.Layout(self.tmp.name, "model", "windows")

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, req=None, **kwargs):
        current = FakeInstaller("model", "Model", req or requirements(), self.layout, WINDOWS_3090, **kwargs)
        current.start().wait(10)
        return current

    def test_install_and_resume(self):
        first = self.run_install()
        self.assertEqual(first.state, installer.DONE, first.error)
        self.assertEqual(first.calls, ["uv", "python", "environment", "PyTorch", "Model", "Weights"])
        self.assertEqual(first.fraction, 1.0)
        self.assertTrue(installer.is_complete(self.layout))
        self.assertTrue(self.layout.is_own_folder())
        with open(self.layout.log_file, encoding="utf-8") as f:
            self.assertIn("Installing PyTorch", f.read())
        # Nothing to do again
        self.assertEqual(self.run_install().calls, [])
        # A step whose declaration changed is done again, alone
        self.assertEqual(self.run_install(requirements("torch==2.7.1")).calls, ["PyTorch"])
        # Weights deleted: downloaded again
        os.remove(os.path.join(self.layout.backend_dir, "w", "model.safetensors"))
        self.assertEqual(self.run_install(requirements("torch==2.7.1")).calls, ["Weights"])
        # Repair: a new environment, every package, the weights; uv and Python kept
        self.assertEqual(self.run_install(requirements("torch==2.7.1"), repair=True).calls,
                         ["environment", "PyTorch", "Model", "Weights"])

    def test_failure_resumes(self):
        failed = self.run_install(fail_on="Model")
        self.assertEqual(failed.state, installer.FAILED)
        self.assertIn("Model failed", failed.error)
        self.assertFalse(installer.is_complete(self.layout))
        resumed = self.run_install()
        self.assertEqual(resumed.calls, ["Model", "Weights"])
        self.assertTrue(installer.is_complete(self.layout))

    def test_new_environment_reinstalls_packages(self):
        self.run_install()
        os.remove(self.layout.python)
        self.assertEqual(self.run_install().calls, ["environment", "PyTorch", "Model"])

    def test_cancel(self):
        current = FakeInstaller("model", "Model", requirements(), self.layout, WINDOWS_3090)
        current.cancel()
        current.start().wait(10)
        self.assertEqual(current.state, installer.CANCELLED)
        self.assertEqual(current.calls, [])

    def test_remove(self):
        self.run_install()
        installer.remove(self.layout)
        self.assertFalse(os.path.exists(self.layout.backend_dir))
        # Never a folder the installer didn't make
        os.makedirs(self.layout.backend_dir)
        with self.assertRaisesRegex(ValueError, "wasn't made by the add-on"):
            installer.remove(self.layout)
        with self.assertRaisesRegex(ValueError, "not a model folder"):
            installer.remove(paths.Layout(self.tmp.name, os.path.join("..", ".."), "windows"))

    def test_real_command(self):
        """run_command: output logged, failure reported with the end of the output"""
        current = installer.Installer("model", "Model", requirements(), self.layout, WINDOWS_3090)
        current._log = open(os.path.join(self.tmp.name, "log.txt"), "w", encoding="utf-8")
        try:
            lines = current.run_command([sys.executable, "-c", "print('hello'); print('RESULT {\"ok\": true}')"])
            self.assertEqual(lines[0], "hello")
            self.assertEqual(current._result(lines), {"ok": True})
            with self.assertRaises(installer.InstallError) as caught:
                current.run_command([sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"])
            self.assertIn("exit code 3", str(caught.exception))
            self.assertIn("boom", str(caught.exception))
        finally:
            current._log.close()

    def test_python_stays_in_the_models_folder(self):
        """uv's Python install writes no executable in ~/.local/bin and no Windows registry entry"""
        commands = []

        class Recording(installer.Installer):
            def run_command(self, argv, extra_env=(), poll=None):
                commands.append((argv, self._command_env(extra_env)))
                return []

        for system in ("windows", "linux"):
            commands.clear()
            current = Recording("model", "Model", requirements(), paths.Layout(self.tmp.name, "m", system),
                                Machine(system, "x86_64"))
            current._install_python()
            argv, env = commands[0]
            self.assertIn("--no-bin", argv)
            self.assertEqual("--no-registry" in argv, system == "windows")
            self.assertEqual(argv[-1], "3.11")
            self.assertEqual((env["UV_PYTHON_INSTALL_BIN"], env["UV_PYTHON_INSTALL_REGISTRY"]), ("0", "0"))
            self.assertEqual(env["UV_PYTHON_INSTALL_DIR"], current.layout.python_dir)

    def test_download_messages(self):
        gated = Weights("Llama", "meta-llama/Meta-Llama-3-8B-Instruct", 15.0, gated=True)
        message = installer.Installer._download_message(gated, {"kind": "gated", "signed_in": False})
        self.assertIn("sign in", message)
        message = installer.Installer._download_message(gated, {"kind": "gated", "signed_in": True})
        self.assertIn("no access", message)
        problem = installer.Installer._download_problem(gated, {"kind": "gated"})
        self.assertEqual(problem["url"], "https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct")


class TestEnvScripts(unittest.TestCase):
    def test_env_check(self):
        """env_check.py with this Python (no torch here)"""
        req = Requirements("3.11", (), imports=("json", "no_such_module_xyz"),
                           optional_imports=(("sqlite3", "why"),))
        report = checks.run_env_check(sys.executable, req)
        self.assertTrue(report["imports"]["json"]["ok"])
        self.assertFalse(report["imports"]["no_such_module_xyz"]["ok"])
        self.assertIn("ModuleNotFoundError", report["imports"]["no_such_module_xyz"]["error"])
        self.assertIn("ok", report["torch"])
        self.assertIn("signed_in", report)

    def test_env_check_bad_python(self):
        with self.assertRaises(checks.CheckError):
            checks.run_env_check(os.path.join(REPO, "no_python.exe"), Requirements("3.11", ()))


def report(torch=None, imports=None, python="3.11.4", **extra):
    found = {"python": python, "imports": imports if imports is not None else {"torch": {"ok": True, "version": "2.5.1"}},
             "torch": torch if torch is not None else {"ok": True, "version": "2.5.1+cu121", "cuda": "12.1",
                                                       "available": True, "arch_list": ["sm_80", "sm_86", "sm_90"],
                                                       "devices": [{"name": "RTX 3090", "memory_mb": 24576,
                                                                    "capability": [8, 6]}]},
             "signed_in": False, "access": {}}
    found.update(extra)
    return found


class TestChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.layout = paths.Layout(self.tmp.name, "model", "windows")
        self.cache = os.path.join(self.tmp.name, "hub")
        os.makedirs(os.path.dirname(self.layout.python))
        open(self.layout.python, "w").close()
        installer.write_state(self.layout, {"format": 1, "backend": "model", "steps": {}, "complete": True})

    def tearDown(self):
        self.tmp.cleanup()

    def evaluate(self, req, rep, machine_=WINDOWS_3090, managed=True, python=None):
        return checks.evaluate(req, machine_, self.layout, python or self.layout.python, managed, rep,
                               cache_dir=self.cache)

    def by_id(self, items):
        return {item.id: item for item in items}

    def test_ready(self):
        req = Requirements("3.11", (), imports=("torch",), min_vram_gb=8.0)
        items = self.evaluate(req, report())
        self.assertTrue(checks.ready(items), items)
        self.assertEqual(self.by_id(items)["gpu"].level, checks.OK)

    def test_not_installed(self):
        req = Requirements("3.11", ())
        items = checks.evaluate(req, WINDOWS_3090, self.layout, os.path.join(self.tmp.name, "none.exe"), True, None)
        self.assertEqual(items[0].fix, checks.FIX_INSTALL)
        items = checks.evaluate(req, WINDOWS_3090, self.layout, "", False, None)
        self.assertEqual(items[0].fix, checks.FIX_PYTHON)
        self.assertFalse(checks.ready(items))
        installer.write_state(self.layout, {"format": 1, "backend": "model", "steps": {}, "complete": False})
        items = self.evaluate(req, report())
        self.assertEqual(self.by_id(items)["environment"].message, "The install stopped before the end.")

    def test_packages(self):
        req = Requirements("3.11", (), imports=("torch", "kimodo"), optional_imports=(("motion_correction", "x"),))
        imports = {"torch": {"ok": True}, "kimodo": {"ok": False, "error": "ImportError: DLL load failed"},
                   "motion_correction": {"ok": False}}
        items = self.by_id(self.evaluate(req, report(imports=imports)))
        self.assertEqual(items["packages"].level, checks.ERROR)
        self.assertIn("kimodo", items["packages"].message)
        self.assertEqual(items["packages"].fix, checks.FIX_REPAIR)
        self.assertEqual(items["optional:motion_correction"].level, checks.WARNING)
        # An existing environment isn't repaired by the add-on
        items = self.by_id(self.evaluate(req, report(imports=imports), managed=False))
        self.assertEqual(items["packages"].fix, "")

    def test_gpu(self):
        req = Requirements("3.11", (), imports=("torch",), min_vram_gb=30.0)
        self.assertEqual(self.by_id(self.evaluate(req, report()))["gpu"].level, checks.WARNING)
        blackwell = report(torch={"ok": True, "version": "2.5.1+cu121", "cuda": "12.1", "available": True,
                                  "arch_list": ["sm_80", "sm_86", "sm_90"],
                                  "devices": [{"name": "RTX 5090", "memory_mb": 32607, "capability": [12, 0]}]})
        item = self.by_id(self.evaluate(req, blackwell, Machine("windows", "x86_64", (RTX5090,))))["gpu"]
        self.assertEqual((item.level, item.fix), (checks.ERROR, checks.FIX_REPAIR))
        self.assertIn("sm_120", item.message)
        cpu_build = report(torch={"ok": True, "version": "2.5.1", "cuda": None, "available": False})
        self.assertIn("without CUDA", self.by_id(self.evaluate(req, cpu_build))["gpu"].message)
        driver = report(torch={"ok": True, "version": "2.7.1", "cuda": "12.8", "available": False})
        self.assertEqual(self.by_id(self.evaluate(req, driver))["gpu"].fix, checks.FIX_URL)
        no_gpu = self.by_id(self.evaluate(req, cpu_build, Machine("linux", "x86_64")))["gpu"]
        self.assertEqual(no_gpu.level, checks.WARNING)
        self.assertTrue(checks._ptx_covers(["sm_90", "compute_90"], 12, 0))

    def test_weights(self):
        public = Weights("Model", "nvidia/model", 1.0, required_files=("config.yaml",))
        gated = Weights("Llama", "meta-llama/llama", 15.0, gated=True, required_files=("config.json",))
        req = Requirements("3.11", (), imports=("torch",), weights=(public, gated))
        items = self.by_id(self.evaluate(req, report()))
        self.assertEqual(items["weights:nvidia/model"].fix, checks.FIX_INSTALL)
        self.assertEqual(items["weights:meta-llama/llama"].fix, checks.FIX_SIGN_IN)
        self.assertEqual(items["weights:meta-llama/llama"].url, "https://huggingface.co/meta-llama/llama")
        items = self.by_id(self.evaluate(req, report(signed_in=True, access={"meta-llama/llama": "gated"})))
        self.assertEqual(items["weights:meta-llama/llama"].fix, checks.FIX_URL)
        items = self.by_id(self.evaluate(req, report(signed_in=True, access={"meta-llama/llama": "ok"})))
        self.assertEqual(items["weights:meta-llama/llama"].fix, checks.FIX_INSTALL)
        make_snapshot(self.cache, "nvidia/model", {"config.yaml": ""})
        make_snapshot(self.cache, "meta-llama/llama", {"config.json": ""})
        self.assertTrue(checks.ready(self.evaluate(req, report())))


class TestSignIn(unittest.TestCase):
    def test_commands(self):
        python = r"C:\models\env\Scripts\python.exe"
        argv, kwargs = signin.terminal_argv(python, "windows")
        self.assertEqual(argv[:2], ["cmd.exe", "/k"])
        self.assertEqual(argv[2:], [python, "-m", "huggingface_hub.cli.hf", "auth", "login"])
        self.assertIn("creationflags", kwargs)
        argv, _ = signin.terminal_argv("/m/env/bin/python", "macos")
        self.assertEqual(argv[0], "osascript")
        self.assertIn("/m/env/bin/python -m huggingface_hub.cli.hf auth login", argv[2])
        argv, _ = signin.terminal_argv("/p", "linux", which=lambda name: "/usr/bin/xterm" if name == "xterm" else None)
        self.assertEqual(argv[:2], ["/usr/bin/xterm", "-e"])
        self.assertIsNone(signin.terminal_argv("/p", "linux", which=lambda name: None))
        self.assertIn('"C:\\Program Files\\py.exe"', signin.command_line(r"C:\Program Files\py.exe"))


class TestKimodoRequirements(unittest.TestCase):
    def test_torch_build(self):
        req = kimodo_install.requirements(WINDOWS_3090)
        torch = req.packages[0]
        self.assertEqual(torch.requirements, ("torch==2.5.1",))
        self.assertIn("cu121", torch.index_url)
        blackwell = kimodo_install.requirements(Machine("linux", "x86_64", (RTX5090,))).packages[0]
        self.assertIn("cu128", blackwell.index_url)
        self.assertIsNone(kimodo_install.requirements(Machine("macos", "arm64")).packages[0].index_url)

    def test_packages_and_weights(self):
        req = kimodo_install.requirements(WINDOWS_3090)
        self.assertEqual(req.python, "3.11")
        wheel = req.packages[1].requirements[0]
        self.assertTrue(wheel.startswith("motion_correction @ https://github.com/Aero-Ex/kimodo/releases/"))
        self.assertIn("cp311-cp311-win_amd64.whl#sha256=", wheel)
        kimodo = req.packages[2]
        self.assertIn(kimodo_install.FORK_COMMIT, kimodo.requirements[0])
        self.assertIn(("SKIP_MOTION_CORRECTION_IN_SETUP", "1"), kimodo.env)
        self.assertEqual([w.repo_id for w in req.weights],
                         ["nvidia/Kimodo-SOMA-RP-v1.1", "Aero-Ex/KIMODO-Meta3_llm2vec_NF4"])
        self.assertFalse(any(w.gated for w in req.weights))
        self.assertEqual(kimodo_install.requirements(WINDOWS_3090, "Kimodo-SOMA-RP-v1").weights[0].repo_id,
                         "nvidia/Kimodo-SOMA-RP-v1")
        # No prebuilt post-processing on macOS: installed without it (the check warns)
        mac = kimodo_install.requirements(Machine("macos", "arm64"))
        self.assertEqual(len(mac.packages), 2)
        # Declarations are stable (the installer compares their keys)
        self.assertEqual(step_key(req.packages[2]), step_key(kimodo_install.requirements(WINDOWS_3090).packages[2]))


if __name__ == "__main__":
    unittest.main()
