"""Whether a model's weights are on disk, read from the Hugging Face cache's layout or the weights' own folder,
without huggingface_hub (so the add-on can tell before the environment exists). No bpy.

Cache layout: <cache>/models--<org>--<name>/refs/<branch> holds a commit; snapshots/<commit>/ holds the files
(links to blobs/). A download stopped halfway leaves blobs/*.incomplete and no snapshot file for them.
"""
import json
import os
import re

from . import paths

_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class WeightsStatus:
    def __init__(self, present, folder="", missing=(), revision=""):
        self.present = present
        self.folder = folder          # the snapshot or the weights' folder ("" when not found)
        self.missing = list(missing)  # required files not there
        self.revision = revision

    def __repr__(self):
        return f"WeightsStatus(present={self.present}, folder={self.folder!r}, missing={self.missing})"


def snapshot_folder(repo_id, revision, cache_dir):
    """(snapshot folder, commit) of a repository in the Hugging Face cache, or ("", "")"""
    repo = paths.hf_repo_dir(repo_id, cache_dir)
    revision = revision or "main"
    commit = revision if _COMMIT.match(revision) else ""
    if not commit:
        ref = os.path.join(repo, "refs", revision)
        try:
            with open(ref, encoding="utf-8") as f:
                commit = f.read().strip()
        except OSError:
            return "", ""
    folder = os.path.join(repo, "snapshots", commit)
    return (folder, commit) if os.path.isdir(folder) else ("", "")


def missing_files(folder, required):
    """Required files not in folder, the shards of an index (*.index.json) included"""
    missing = [name for name in required if not os.path.isfile(os.path.join(folder, name))]
    for name in required:
        if name.endswith(".index.json") and name not in missing:
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    shards = sorted(set(json.load(f).get("weight_map", {}).values()))
            except (OSError, ValueError):
                missing.append(name)
                continue
            missing.extend(shard for shard in shards if not os.path.isfile(os.path.join(folder, shard)))
    return missing


def status(weights, layout, cache_dir=None):
    """WeightsStatus of a spec.Weights for a backend's paths.Layout"""
    folder = layout.weights_dir(weights)
    revision = ""
    if folder is None:
        folder, revision = snapshot_folder(weights.repo_id, weights.revision, cache_dir or paths.hf_cache_dir())
        if not folder:
            return WeightsStatus(False, missing=list(weights.required_files))
    elif not os.path.isdir(folder):
        return WeightsStatus(False, missing=list(weights.required_files))
    missing = missing_files(folder, weights.required_files)
    if not weights.required_files and not any(os.scandir(folder)):
        missing = ["(empty folder)"]
    return WeightsStatus(not missing, folder, missing, revision)


def repo_size_on_disk(weights, layout, cache_dir=None):
    """Bytes the weights take so far (partial downloads included), for the download's progress"""
    folder = layout.weights_dir(weights)
    if folder is None:
        folder = paths.hf_repo_dir(weights.repo_id, cache_dir or paths.hf_cache_dir())
    return paths.folder_size(folder) if os.path.isdir(folder) else 0
