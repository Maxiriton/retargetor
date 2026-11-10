"""The backends the add-on knows, and their workers (one per backend, kept running between generations).

Adding a backend: a folder next to kimodo/ and interpolate/, and one line in BACKENDS. Never reorder the list:
the position of a backend is its number in the preferences file.
"""
from . import process
from .interpolate.backend import InterpolateBackend
from .kimodo.backend import KimodoBackend

BACKENDS = [
    KimodoBackend(),
    InterpolateBackend(),
]

# {backend id: (Worker, (command, env)) }
_workers = {}


def get(backend_id):
    """The Backend with this id. Raises KeyError with an explicit message."""
    for backend in BACKENDS:
        if backend.id == backend_id:
            return backend
    raise KeyError(f"Unknown backend '{backend_id}'.")


def visible(developer=False):
    """Backends to list in the UI."""
    return [b for b in BACKENDS if developer or not b.developer_only]


def worker_for(backend, python, settings, layout):
    """The backend's worker, created if needed (not started: requests start it). A worker started with other
    settings is stopped and replaced. python, layout: its environment (Backend.worker_command).
    Raises ValueError if the settings don't allow starting it."""
    command, env = backend.worker_command(python, settings, layout)
    key = (tuple(command), tuple(sorted(env.items())))
    current = _workers.get(backend.id)
    if current is not None and current[1] != key:
        current[0].stop()
        current = None
    if current is None:
        current = (process.Worker(command, env, hello_timeout=backend.load_timeout), key)
        _workers[backend.id] = current
    return current[0]


def existing_worker(backend_id):
    """The backend's worker if one was created, else None."""
    current = _workers.get(backend_id)
    return current[0] if current is not None else None


def stop(backend_id):
    current = _workers.pop(backend_id, None)
    if current is not None:
        current[0].stop()


def stop_all():
    for backend_id in list(_workers):
        stop(backend_id)


def pump_all():
    """Handle the messages of every worker. Returns True if something changed."""
    changed = False
    for worker, _key in list(_workers.values()):
        changed = worker.pump() or changed
    return changed


def any_busy():
    return any(worker.busy or worker.state == process.STARTING for worker, _key in _workers.values())
