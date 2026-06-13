import os
import sys


SHORTCUT_NAME = "Ring Spectrum.lnk"


def get_startup_dir():
    return os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
    )


def get_startup_shortcut_path():
    return os.path.join(get_startup_dir(), SHORTCUT_NAME)


def get_launch_target(application_path):
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    script = os.path.join(application_path, "main.py")
    return sys.executable, f'"{script}"'


def is_startup_enabled():
    return os.path.exists(get_startup_shortcut_path())


def enable_startup(application_path):
    import win32com.client

    startup_dir = get_startup_dir()
    if not startup_dir or not os.path.isdir(startup_dir):
        raise OSError("Windows startup folder was not found")

    target_path, arguments = get_launch_target(application_path)
    shortcut_path = get_startup_shortcut_path()
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.TargetPath = target_path
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = application_path
    shortcut.IconLocation = target_path
    shortcut.Description = "Start Ring Spectrum when Windows starts"
    shortcut.save()
    return True


def disable_startup():
    shortcut_path = get_startup_shortcut_path()
    if os.path.exists(shortcut_path):
        os.remove(shortcut_path)
    return True


def sync_startup_shortcut(enabled, application_path):
    if enabled:
        return enable_startup(application_path)
    return disable_startup()
