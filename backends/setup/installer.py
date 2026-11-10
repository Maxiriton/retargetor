"""A backend's install, step by step, in a thread: uv, Python, the environment, the packages, the weights. No bpy.

Each step done is recorded in the backend's state file (install.json) with the key of its declaration
(spec.step_key): an install stopped halfway (cancelled, failed, Blender closed) resumes where it stopped, and a step
whose declaration changed (a new version pinned) is done again. Repair redoes everything: a new environment, every
package installed again, the weights completed. Every command's output goes to the backend's log (install.log).

The add-on reads the Installer's fields from a timer (state, fraction, message, detail, error, problem); nothing
blocks Blender. wait() blocks, for scripts and tests.
"""
import collections
import datetime
import json
import os
import queue
import subprocess
import sys
import threading
import time

from . import uv, weights as weights_status
from .spec import WINDOWS, step_key

RUNNING = "RUNNING"
DONE = "DONE"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

STATE_FORMAT = 1
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_HERE = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_SCRIPT = os.path.join(_HERE, "env_download.py")


class InstallError(Exception):
    def __init__(self, message, problem=None):
        super().__init__(message)
        self.problem = problem or {}


class Cancelled(Exception):
    pass


def read_state(layout):
    """The backend's recorded install (a dict), or None if it was never installed by the add-on"""
    try:
        with open(layout.state_file, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def write_state(layout, state):
    os.makedirs(layout.backend_dir, exist_ok=True)
    partial = layout.state_file + ".partial"
    with open(partial, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(partial, layout.state_file)


def is_complete(layout):
    state = read_state(layout)
    return bool(state and state.get("complete")) and os.path.isfile(layout.python)


class Step:
    def __init__(self, step_id, label, weight, key, run, done_check=None, skip_when_done=False):
        self.id = step_id
        self.label = label
        self.weight = weight
        self.key = key
        self.run = run
        # Optional: whether what the step makes is really there (a recorded step is redone if not)
        self.done_check = done_check
        # What the step makes may already be there without the installer (weights in the Hugging Face cache, from
        # the user's other tools): skipped then, unless repairing
        self.skip_when_done = skip_when_done
        self.skipped = False


class Installer:
    """Installs one backend's Requirements in its Layout. backend_label: for messages."""

    def __init__(self, backend_id, backend_label, requirements, layout, machine, repair=False, cache_dir=None,
                 environ=None):
        self.backend_id = backend_id
        self.backend_label = backend_label
        self.requirements = requirements
        self.layout = layout
        self.machine = machine
        self.repair = repair
        self.cache_dir = cache_dir
        self.environ = dict(os.environ if environ is None else environ)
        self.state = RUNNING
        self.message = ""
        self.detail = ""
        self.error = ""
        # What went wrong, for the UI's fix: {"kind": "gated" | "auth" | ..., "repo_id": ..., "url": ...}
        self.problem = {}
        self.started = time.perf_counter()
        self.finished = None
        self._steps = self._plan()
        self._index = 0
        self._step_fraction = 0.0
        self._cancel = threading.Event()
        self._process = None
        self._thread = None
        self._log = None
        self.tail = collections.deque(maxlen=200)
        self._uv = uv.uv_path(layout.tools_dir, machine.system)

    # Plan

    def _plan(self):
        req = self.requirements
        layout = self.layout
        env_key = step_key(("environment", req.python, self.machine.system))
        steps = [
            Step("uv", f"Downloading uv {uv.UV_VERSION}", 1, step_key(("uv", uv.UV_VERSION)), self._install_uv,
                 lambda: os.path.isfile(self._uv)),
            Step("python", f"Installing Python {req.python}", 2, step_key(("python", req.python)),
                 self._install_python),
            Step("environment", "Creating the environment", 1, env_key, self._create_env,
                 lambda: os.path.isfile(layout.python)),
        ]
        for index, packages in enumerate(req.packages):
            steps.append(Step(f"packages-{index}", f"Installing {packages.label}", 10,
                              step_key((env_key, packages)), lambda p=packages: self._install_packages(p)))
        for weights in req.weights:
            steps.append(Step(f"weights:{weights.repo_id}", f"Downloading {weights.label} ({weights.size_gb:.1f} GB)",
                              max(1.0, weights.size_gb * 4), step_key(weights),
                              lambda w=weights: self._download(w),
                              lambda w=weights: weights_status.status(w, layout, self.cache_dir).present,
                              skip_when_done=True))
        return steps

    @property
    def steps(self):
        return list(self._steps)

    # Progress, read by the UI

    @property
    def active(self):
        return self.state == RUNNING

    @property
    def fraction(self):
        total = sum(step.weight for step in self._steps) or 1.0
        done = sum(step.weight for step in self._steps[:self._index])
        if self._index < len(self._steps):
            done += self._steps[self._index].weight * min(1.0, max(0.0, self._step_fraction))
        return 1.0 if self.state == DONE else done / total

    @property
    def step_number(self):
        return min(self._index + 1, len(self._steps)), len(self._steps)

    @property
    def duration(self):
        return (self.finished or time.perf_counter()) - self.started

    # Lifecycle

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def cancel(self):
        self._cancel.set()
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def wait(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)
        return self

    def _cancelled(self):
        return self._cancel.is_set()

    def _run(self):
        os.makedirs(self.layout.backend_dir, exist_ok=True)
        self._log = open(self.layout.log_file, "a", encoding="utf-8")
        try:
            self._write_log(f"=== {datetime.datetime.now().isoformat(timespec='seconds')} "
                            f"{'Repair' if self.repair else 'Install'} {self.backend_label} in {self.layout.backend_dir}")
            state = read_state(self.layout) or {}
            if state.get("format") != STATE_FORMAT or state.get("backend") != self.backend_id:
                state = {"format": STATE_FORMAT, "backend": self.backend_id, "steps": {}}
            state["complete"] = False
            state["python"] = self.requirements.python
            write_state(self.layout, state)
            for self._index, step in enumerate(self._steps):
                if self._cancelled():
                    raise Cancelled()
                self._step_fraction = 0.0
                self.message = step.label
                self.detail = ""
                recorded = state["steps"].get(step.id) == step.key
                if self.repair and step.id not in ("uv", "python"):
                    recorded = False
                if recorded and (step.done_check is None or step.done_check()):
                    step.skipped = True
                    self._write_log(f"--- {step.label}: already done")
                    continue
                if step.skip_when_done and not self.repair and step.done_check():
                    step.skipped = True
                    self._write_log(f"--- {step.label}: already there")
                    state["steps"][step.id] = step.key
                    write_state(self.layout, state)
                    continue
                self._write_log(f"--- {step.label}")
                if step.id == "environment":
                    # A new environment: every package goes in again
                    state["steps"] = {k: v for k, v in state["steps"].items() if not k.startswith("packages-")}
                step.run()
                state["steps"][step.id] = step.key
                write_state(self.layout, state)
            self._index = len(self._steps)
            state["complete"] = True
            state["installed"] = datetime.datetime.now().isoformat(timespec="seconds")
            state["uv"] = uv.UV_VERSION
            write_state(self.layout, state)
            self.message = "Installed"
            self.detail = ""
            self._finish(DONE)
        except Cancelled:
            self.message = "Cancelled"
            self.error = "The install was cancelled; it resumes where it stopped."
            self._write_log("--- Cancelled")
            self._finish(CANCELLED)
        except (InstallError, uv.DownloadError, OSError) as e:
            self.error = str(e)
            self.problem = getattr(e, "problem", {}) or {}
            self._write_log(f"--- FAILED: {e}")
            self._finish(FAILED)
        except Exception as e:  # noqa: BLE001 - reported to the UI, never raised into Blender
            import traceback
            self.error = f"{type(e).__name__}: {e}"
            self._write_log(traceback.format_exc())
            self._finish(FAILED)
        finally:
            if self._log is not None:
                self._log.close()
                self._log = None

    def _finish(self, state):
        self.finished = time.perf_counter()
        self.state = state

    # Output

    def _write_log(self, line):
        self.tail.append(line)
        if self._log is not None:
            self._log.write(line + "\n")
            self._log.flush()

    def _command_env(self, extra=()):
        env = dict(self.environ)
        env.update({
            "UV_CACHE_DIR": self.layout.uv_cache_dir,
            "UV_PYTHON_INSTALL_DIR": self.layout.python_dir,
            "UV_PYTHON_PREFERENCE": "only-managed",
            "UV_NO_CONFIG": "1",
            "UV_NO_PROGRESS": "1",
            # Python builds stay in the models' folder (see _install_python), even when uv venv fetches one
            "UV_PYTHON_INSTALL_BIN": "0",
            "UV_PYTHON_INSTALL_REGISTRY": "0",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            # Windows without Developer Mode has no symlinks: the cache copies files, which is fine
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
        })
        # The environment's own variables, never the ones of Blender's Python
        for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            env.pop(name, None)
        env.update(dict(extra))
        return env

    def run_command(self, argv, extra_env=(), poll=None):
        """Run a command, its output to the log; poll() is called about twice a second while it runs.
        Returns the output's lines. Raises InstallError if it fails, Cancelled if cancelled."""
        self._write_log("$ " + " ".join(f'"{a}"' if " " in a else a for a in argv))
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, env=self._command_env(extra_env),
                                       creationflags=_NO_WINDOW)
        except OSError as e:
            raise InstallError(f"Unable to run {os.path.basename(argv[0])}: {e}") from e
        self._process = process
        lines = queue.Queue()

        def read():
            for raw in process.stdout:
                lines.put(raw.decode("utf-8", errors="replace").rstrip())
            lines.put(None)

        threading.Thread(target=read, daemon=True).start()
        output = []
        last_poll = 0.0
        while True:
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                line = ""
            if line is None:
                break
            if line:
                output.append(line)
                self._write_log(line)
                if not line.startswith("RESULT "):
                    self.detail = line[:200]
            now = time.perf_counter()
            if poll is not None and now - last_poll > 0.5:
                last_poll = now
                poll()
        code = process.wait()
        process.stdout.close()
        self._process = None
        if self._cancelled():
            raise Cancelled()
        if code != 0:
            tail = "\n".join(line for line in output[-6:] if not line.startswith("RESULT "))
            error = InstallError(f"{os.path.basename(argv[0])} failed (exit code {code}).\n{tail}".strip())
            error.output = output
            raise error
        return output

    # Steps

    def _install_uv(self):
        def progress(done, total):
            self._step_fraction = done / total if total else 0.0
            self.detail = f"{done / 1e6:.1f} MB"
        uv.install(self.layout.tools_dir, self.machine.system, self.machine.arch, progress, self._cancelled)

    def _install_python(self):
        # Only into the models' folder: no python3.x executable in the user's ~/.local/bin, no Windows registry entry
        # (uv's defaults), which would change what `python3.11` means on the machine
        argv = [self._uv, "python", "install", "--no-bin", self.requirements.python]
        if self.machine.system == WINDOWS:
            argv.insert(4, "--no-registry")
        self.run_command(argv)

    def _create_env(self):
        self.run_command([self._uv, "venv", "--clear", "--python", self.requirements.python, self.layout.env_dir])
        if not os.path.isfile(self.layout.python):
            raise InstallError(f"The environment was created without its Python ({self.layout.python}).")

    def _install_packages(self, packages):
        argv = [self._uv, "pip", "install", "--python", self.layout.python]
        if packages.index_url:
            argv += ["--index-url", packages.index_url]
        for url in packages.extra_index_urls:
            argv += ["--extra-index-url", url]
        if packages.index_url or packages.extra_index_urls:
            # PyTorch's index holds other packages too (numpy...): take the best version from every index
            argv += ["--index-strategy", "unsafe-best-match"]
        if packages.no_deps:
            argv.append("--no-deps")
        # No --reinstall when repairing: the environment is new, and a reinstall would take PyTorch again from the
        # step's own index (PyPI's build has no CUDA on Windows)
        argv += list(packages.requirements)
        self.run_command(argv, extra_env=packages.env)

    def _download(self, weights):
        expected = weights.size_gb * 1e9
        start = weights_status.repo_size_on_disk(weights, self.layout, self.cache_dir)

        def poll():
            size = weights_status.repo_size_on_disk(weights, self.layout, self.cache_dir)
            # What was there before (another download, a partial one) counts as done
            remaining = max(expected - start, 1.0)
            self._step_fraction = min(0.99, max(0.0, (size - start) / remaining))
            self.detail = f"{size / 1e9:.2f} of {weights.size_gb:.2f} GB"

        spec = {"repo_id": weights.repo_id, "revision": weights.revision,
                "allow_patterns": list(weights.allow_patterns) if weights.allow_patterns else None,
                "ignore_patterns": list(weights.ignore_patterns) if weights.ignore_patterns else None,
                "local_dir": self.layout.weights_dir(weights), "gated": weights.gated}
        try:
            output = self.run_command([self.layout.python, "-I", DOWNLOAD_SCRIPT, json.dumps(spec)], poll=poll)
        except InstallError as e:
            output = getattr(e, "output", [])
            if not self._result(output):
                raise
        result = self._result(output)
        if not result.get("ok"):
            raise InstallError(self._download_message(weights, result), self._download_problem(weights, result))
        status = weights_status.status(weights, self.layout, self.cache_dir)
        if not status.present:
            if weights.gated and sign_in_expired(output):
                # huggingface_hub falls back to the files already in its cache when the user's sign-in has expired
                raise InstallError(f"Your Hugging Face sign-in has expired, so {weights.label} can't be downloaded: "
                                   f"sign in again (Sign In button), then resume the install.",
                                   self._download_problem(weights, {"kind": "auth", "signed_in": False}))
            raise InstallError(f"{weights.label} was downloaded but files are missing: {', '.join(status.missing)}.")

    @staticmethod
    def _result(lines):
        for line in reversed(lines):
            if line.startswith("RESULT "):
                try:
                    return json.loads(line[len("RESULT "):])
                except ValueError:
                    break
        return {}

    @staticmethod
    def _download_problem(weights, result):
        return {"kind": result.get("kind", "error"), "repo_id": weights.repo_id, "url": weights.page_url,
                "gated": weights.gated, "signed_in": bool(result.get("signed_in"))}

    @staticmethod
    def _download_message(weights, result):
        kind = result.get("kind", "error")
        if weights.gated and kind in ("gated", "auth", "not_found"):
            if not result.get("signed_in"):
                return (f"{weights.label} needs your Hugging Face access: request it on {weights.page_url}, "
                        f"then sign in to Hugging Face (Sign In button) and install again.")
            return (f"Your Hugging Face account has no access to {weights.repo_id} yet: request it on "
                    f"{weights.page_url} (it may take a while to be granted), then install again.")
        if kind == "network":
            return f"Unable to reach Hugging Face to download {weights.label}: check the connection. ({result.get('message', '')})"
        return f"Downloading {weights.label} failed: {result.get('message') or 'unknown error'}"


def sign_in_expired(lines):
    """huggingface_hub said the user's sign-in has expired (in a download's output)"""
    return any("expired" in line.lower() and "auth login" in line for line in lines)


def remove(layout):
    """Delete the backend's folder (environment, its own weights, log, state). Only a folder the installer made
    (holding its state file) is deleted. Raises OSError / ValueError."""
    import shutil
    folder = os.path.abspath(layout.backend_dir)
    models = os.path.abspath(os.path.join(layout.root, "models"))
    if os.path.dirname(folder) != models:
        raise ValueError(f"Refusing to delete {folder}: not a model folder of {models}.")
    if not os.path.isdir(folder):
        return
    if not layout.is_own_folder():
        raise ValueError(f"Refusing to delete {folder}: it wasn't made by the add-on (no {os.path.basename(layout.state_file)}).")

    def on_error(function, path, _info):
        # Read-only files (git objects, some wheels) on Windows
        try:
            os.chmod(path, 0o700)
            function(path)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(folder, onexc=lambda f, p, e: on_error(f, p, e))
    else:
        shutil.rmtree(folder, onerror=on_error)
    if os.path.exists(folder):
        raise OSError(f"Some files in {folder} couldn't be deleted (in use?).")


__all__ = ["CANCELLED", "DONE", "FAILED", "RUNNING", "InstallError", "Installer", "is_complete", "read_state",
           "remove", "write_state", "WINDOWS"]
