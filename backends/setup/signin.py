"""Signing in to Hugging Face, for gated weights. No bpy.

The add-on never asks for, reads, stores or sends the user's token: it opens a terminal window running
huggingface_hub's own sign-in (`hf auth login`, from the model's environment), where the user signs in from the
browser or pastes a token. huggingface_hub stores it in its usual place; the downloads then use it by themselves.
"""
import shutil
import subprocess

from .spec import MACOS, WINDOWS


def login_argv(python):
    """huggingface_hub's sign-in, run with the model environment's Python (works in a moved environment too, where
    the hf launcher may point to the old place)"""
    return [python, "-m", "huggingface_hub.cli.hf", "auth", "login"]


def command_line(python):
    """The sign-in command, to show the user when no terminal can be opened"""
    return " ".join(f'"{part}"' if " " in part else part for part in login_argv(python))


def _quote_applescript(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def terminal_argv(python, system, which=shutil.which):
    """(argv, popen keyword arguments) opening a terminal window running the sign-in, or None if no terminal is
    found (Linux without a known terminal emulator)"""
    login = login_argv(python)
    if system == WINDOWS:
        # cmd /k keeps the window open on the result
        return ["cmd.exe", "/k"] + login, {"creationflags": getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)}
    if system == MACOS:
        script = f'tell application "Terminal" to do script "{_quote_applescript(command_line(python))}"'
        return ["osascript", "-e", script, "-e", 'tell application "Terminal" to activate'], {}
    for terminal, flag in (("x-terminal-emulator", "-e"), ("gnome-terminal", "--"), ("konsole", "-e"),
                           ("xfce4-terminal", "-x"), ("kitty", ""), ("alacritty", "-e"), ("xterm", "-e")):
        path = which(terminal)
        if path:
            return [path] + ([flag] if flag else []) + login, {}
    return None


def open_terminal(python, system):
    """Open the sign-in in a terminal window. Returns False if no terminal could be opened (show command_line())."""
    found = terminal_argv(python, system)
    if found is None:
        return False
    argv, kwargs = found
    try:
        subprocess.Popen(argv, **kwargs)
    except OSError:
        return False
    return True
