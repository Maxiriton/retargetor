"""The uv tool (Astral, MIT / Apache-2.0): it installs the Python builds and the packages of the models'
environments. Downloaded once, from its wheel on PyPI (the wheel holds the uv executable), at a pinned version whose
SHA-256 is checked. No bpy.
"""
import hashlib
import os
import stat
import tempfile
import urllib.request
import zipfile

from .spec import LINUX, MACOS, WINDOWS

UV_VERSION = "0.13.5"
_FILES = "https://files.pythonhosted.org/packages/"
# (system, arch): (wheel URL, SHA-256), from https://pypi.org/pypi/uv/0.13.5/json
WHEELS = {
    (WINDOWS, "x86_64"): (_FILES + "32/ea/771744a784b16aa21d195cb5d5d5a2878d72fa00fc26f11ea3f9646994fe/"
                          "uv-0.13.5-py3-none-win_amd64.whl",
                          "1fb29fc46ba12033e2ef95a95ac79d649e71bbb1358419bbbcbd19d86026ef2f"),
    (WINDOWS, "arm64"): (_FILES + "52/67/1f31243f75ece410f2db1afdfc9a9f9722fdee2385e4a347c3ca1dee6d13/"
                         "uv-0.13.5-py3-none-win_arm64.whl",
                         "0548460d46c8667488b1f089e936f29f0edfb1cc753f9152ffbd8bc84a46aa20"),
    (LINUX, "x86_64"): (_FILES + "3a/ad/3c2a81d66d1839063662e5b6c0002ec31f8ee987dbc5295747627ca6160a/"
                        "uv-0.13.5-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
                        "fa8d26e08e34c29c0c4e820cf3181757086d547240b4f4d31ff1d8bd810ca946"),
    (LINUX, "arm64"): (_FILES + "4c/92/d83d019c63c1ccc6ff17df2bfe76270412f9766e7e71aa4d4ccbf018683f/"
                       "uv-0.13.5-py3-none-manylinux_2_28_aarch64.whl",
                       "91e58e304b63b6c91bac5561459ab0c3ea24f17bc01ea9359d69fed72142978f"),
    (MACOS, "x86_64"): (_FILES + "e3/2a/dcae794203261e49564bb9ff7c4b64a093f69ac73476cc8ce54c1deed3a1/"
                        "uv-0.13.5-py3-none-macosx_10_12_x86_64.whl",
                        "337a14829bb499e114989df4f908f134ff37f1fb6c33497541cfb05b28080e39"),
    (MACOS, "arm64"): (_FILES + "d2/26/9ac45211123244ea68be852775093af487a64debc13621a2de239f8ebe73/"
                       "uv-0.13.5-py3-none-macosx_11_0_arm64.whl",
                       "a42c85fa8156e1e5e2cecdbc77bb818ea1dcf5f78b8e2a8f84c7fe4f16f0702e"),
}


class DownloadError(Exception):
    pass


def uv_path(tools_dir, system, version=UV_VERSION):
    return os.path.join(tools_dir, f"uv-{version}", "uv.exe" if system == WINDOWS else "uv")


def download(url, destination, progress=None, cancelled=None, chunk=1 << 20):
    """Download url to destination. progress(done_bytes, total_bytes or None); cancelled() stops it.
    Raises DownloadError."""
    request = urllib.request.Request(url, headers={"User-Agent": "blender-extension-model-setup"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0) or None
            done = 0
            while True:
                if cancelled is not None and cancelled():
                    raise DownloadError("Cancelled.")
                data = response.read(chunk)
                if not data:
                    break
                out.write(data)
                done += len(data)
                if progress is not None:
                    progress(done, total)
    except OSError as e:
        raise DownloadError(f"Unable to download {url}: {e}") from e


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_uv(wheel, destination, system):
    """Take the uv executable out of its wheel (uv-<version>.data/scripts/uv[.exe])"""
    name = "uv.exe" if system == WINDOWS else "uv"
    with zipfile.ZipFile(wheel) as archive:
        members = [m for m in archive.namelist() if m.endswith("/scripts/" + name)]
        if not members:
            raise DownloadError(f"No {name} in the uv wheel.")
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        partial = destination + ".partial"
        with archive.open(members[0]) as source, open(partial, "wb") as out:
            out.write(source.read())
    if system != WINDOWS:
        os.chmod(partial, os.stat(partial).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(partial, destination)


def install(tools_dir, system, arch, progress=None, cancelled=None, wheels=None, fetch=download):
    """uv, downloaded and checked if it isn't there yet. Returns its path. Raises DownloadError."""
    path = uv_path(tools_dir, system)
    if os.path.isfile(path):
        return path
    wheels = WHEELS if wheels is None else wheels
    if (system, arch) not in wheels:
        raise DownloadError(f"No uv build for {system} {arch}.")
    url, expected = wheels[(system, arch)]
    os.makedirs(tools_dir, exist_ok=True)
    handle, wheel = tempfile.mkstemp(suffix=".whl", dir=tools_dir)
    os.close(handle)
    try:
        fetch(url, wheel, progress, cancelled)
        actual = sha256(wheel)
        if actual != expected:
            raise DownloadError(f"The uv download doesn't match its checksum (got {actual}, expected {expected}).")
        extract_uv(wheel, path, system)
    finally:
        try:
            os.remove(wheel)
        except OSError:
            pass
    return path
