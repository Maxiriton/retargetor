"""What a model environment holds, run with its own Python:
    <env python> -I env_check.py '<json>'

<json>: {"imports": [...], "optional_imports": [...], "torch": true, "access": [<gated repo ids>]}
Prints one line starting with "RESULT ": {"python": "3.11.4", "imports": {name: {"ok", "version", "error"}},
"torch": {...}, "signed_in": bool, "access": {repo_id: "ok" | "gated" | "auth" | "error: ..."}}.

"access" checks online whether the user's Hugging Face sign-in may download a gated repository (huggingface_hub reads
the sign-in itself; this script never reads, prints or passes the token). Standard library, torch and huggingface_hub
only.
"""
import importlib
import json
import platform
import sys
import traceback


def check_import(name):
    try:
        module = importlib.import_module(name)
    except BaseException as e:  # noqa: BLE001 - a broken package may raise anything, even SystemExit
        last = traceback.format_exception_only(type(e), e)[-1].strip()
        return {"ok": False, "error": last[:400]}
    version = getattr(module, "__version__", "")
    return {"ok": True, "version": str(version)}


def torch_info():
    try:
        import torch
    except BaseException as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:400]}
    info = {"ok": True, "version": torch.__version__, "cuda": torch.version.cuda, "available": False,
            "devices": [], "arch_list": [], "mps": False}
    try:
        info["available"] = bool(torch.cuda.is_available())
        if info["available"]:
            info["arch_list"] = list(torch.cuda.get_arch_list())
            for index in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(index)
                info["devices"].append({"name": props.name, "memory_mb": int(props.total_memory // (1 << 20)),
                                        "capability": [props.major, props.minor]})
        mps = getattr(torch.backends, "mps", None)
        info["mps"] = bool(mps is not None and mps.is_available())
    except Exception as e:  # noqa: BLE001
        info["error"] = f"{type(e).__name__}: {e}"[:400]
    return info


def signed_in():
    try:
        from huggingface_hub import get_token
        return get_token() is not None
    except Exception:  # noqa: BLE001
        return False


def access(repo_ids):
    found = {}
    if not repo_ids:
        return found
    try:
        from huggingface_hub import auth_check, errors
    except ImportError as e:
        return {repo: f"error: {e}" for repo in repo_ids}
    for repo in repo_ids:
        try:
            auth_check(repo)
            found[repo] = "ok"
        except errors.GatedRepoError:
            found[repo] = "gated"
        except errors.RepositoryNotFoundError:
            found[repo] = "auth"
        except Exception as e:  # noqa: BLE001
            found[repo] = f"error: {type(e).__name__}: {e}"[:300]
    return found


def main():
    spec = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    report = {"python": platform.python_version(), "executable": sys.executable, "imports": {}}
    for name in list(spec.get("imports", [])) + list(spec.get("optional_imports", [])):
        report["imports"][name] = check_import(name)
    if spec.get("torch", True):
        report["torch"] = torch_info()
    report["signed_in"] = signed_in()
    report["access"] = access(spec.get("access", []))
    print("RESULT " + json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
