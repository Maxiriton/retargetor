"""Motion model backends. Each model runs in its own worker process and talks to the add-on over JSON
(protocol.py). Everything specific to a model stays in its own folder (kimodo/, interpolate/...).

- base.py: what a backend declares (capabilities, worker command, role -> joint map, settings)
- protocol.py: the JSON lines protocol, shared with the workers (no bpy)
- process.py: a worker process seen from the add-on (no bpy)
- registry.py: the list of backends, the running workers

Workers import protocol.py and core.* only: this package must not import bpy at load time.
"""
