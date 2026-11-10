"""Where Nilou keeps its files.

Nilou is portable: settings, the download list and helper tools live in a
"Nilou Data" folder next to Nilou.exe. If that folder is not writable (for
example when the exe sits in Program Files) it falls back to %APPDATA%\\Nilou.
"""
import os
import sys

from . import APP_NAME

FROZEN = bool(getattr(sys, 'frozen', False))


def resource_path(*parts):
    """Path to a bundled read-only resource (assets, browser extension)."""
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def app_dir():
    if FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _writable(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, '.write-test')
        with open(probe, 'w'):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


_data_dir = None


def data_dir():
    global _data_dir
    if _data_dir is None:
        portable = os.path.join(app_dir(), APP_NAME + ' Data')
        if _writable(portable):
            _data_dir = portable
        else:
            _data_dir = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), APP_NAME)
            os.makedirs(_data_dir, exist_ok=True)
    return _data_dir


def sub_dir(name):
    folder = os.path.join(data_dir(), name)
    os.makedirs(folder, exist_ok=True)
    return folder


def tools_dir():
    return sub_dir('tools')


def launch_command():
    """(executable, arguments) that start this copy of Nilou."""
    if FROZEN:
        return sys.executable, ''
    exe_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(exe_dir, 'pythonw.exe')
    script = os.path.join(app_dir(), 'Nilou.pyw')
    return (pythonw if os.path.exists(pythonw) else sys.executable), f'"{script}"'
