r"""Environment shim (NOT product code).

This machine turns mkdir(mode=0o700) — which tempfile.mkdtemp uses — into a deny-all
ACL, so every mkdtemp-based tool (pytest tmp_path, pip, tempfile) fails. Injecting
this module via PYTHONPATH patches the mode back to 0o777 at interpreter startup:

    $env:PYTHONPATH = "<repo>\.shim"
    python -m pip install ...
"""
import os
import pathlib

_os_mkdir = os.mkdir


def _mkdir(path, mode=0o777, *args, **kwargs):
    return _os_mkdir(path, 0o777, *args, **kwargs)


os.mkdir = _mkdir

_path_mkdir = pathlib.Path.mkdir


def _pathmkdir(self, mode=0o777, parents=False, exist_ok=False):
    return _path_mkdir(self, 0o777, parents=parents, exist_ok=exist_ok)


pathlib.Path.mkdir = _pathmkdir
