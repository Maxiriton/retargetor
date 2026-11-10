"""Download one Hugging Face repository, run with the model environment's own Python:
    <env python> -I env_download.py '<json>'

<json>: {"repo_id": ..., "revision": ..., "allow_patterns": [...], "ignore_patterns": [...], "local_dir": ...,
         "gated": false}
Prints one line starting with "RESULT " at the end: {"ok": true, "path": ...} or
{"ok": false, "kind": "gated" | "auth" | "not_found" | "network" | "error", "message": ..., "signed_in": bool}.

The Hugging Face token: for a public repository none is sent (token=False). For a gated one, huggingface_hub uses
the user's own sign-in, which it reads itself; this script never reads, prints or passes the token ("signed_in" only
says whether one exists). Uses only the standard library and huggingface_hub (a dependency of the models).
"""
import json
import sys


def result(**fields):
    print("RESULT " + json.dumps(fields), flush=True)


def signed_in():
    try:
        from huggingface_hub import get_token
        return get_token() is not None
    except Exception:  # noqa: BLE001
        return False


def main():
    spec = json.loads(sys.argv[1])
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub import errors
    except ImportError as e:
        result(ok=False, kind="error", message=f"huggingface_hub is missing from the environment ({e}).")
        return 1
    kwargs = {"repo_id": spec["repo_id"], "revision": spec.get("revision") or None,
              "allow_patterns": spec.get("allow_patterns"), "ignore_patterns": spec.get("ignore_patterns"),
              "token": None if spec.get("gated") else False}
    if spec.get("local_dir"):
        kwargs["local_dir"] = spec["local_dir"]
    try:
        path = snapshot_download(**kwargs)
    except errors.GatedRepoError as e:
        result(ok=False, kind="gated", message=str(e).splitlines()[0], signed_in=signed_in())
        return 1
    except errors.RepositoryNotFoundError as e:
        result(ok=False, kind="not_found", message=str(e).splitlines()[0], signed_in=signed_in())
        return 1
    except errors.HfHubHTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        kind = "auth" if status in (401, 403) else "error"
        result(ok=False, kind=kind, message=str(e).splitlines()[0], signed_in=signed_in())
        return 1
    except (errors.LocalEntryNotFoundError, OSError) as e:
        result(ok=False, kind="network", message=str(e).splitlines()[0] if str(e) else type(e).__name__)
        return 1
    except Exception as e:  # noqa: BLE001
        result(ok=False, kind="error", message=f"{type(e).__name__}: {e}")
        return 1
    result(ok=True, path=str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
