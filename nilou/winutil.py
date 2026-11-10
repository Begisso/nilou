"""Windows integration helpers (all fail soft on other platforms)."""
import ctypes
import os
import subprocess
import sys

IS_WIN = sys.platform == 'win32'
CREATE_NO_WINDOW = 0x08000000

if IS_WIN:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _user32.GetParent.argtypes = [wintypes.HWND]
    _user32.GetParent.restype = wintypes.HWND
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                          wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                          wintypes.LPVOID]
    _kernel32.DeviceIoControl.restype = wintypes.BOOL


def enable_dpi_awareness():
    if not IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_app_id(app_id):
    if IS_WIN:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
        except Exception:
            pass


def downloads_folder():
    if IS_WIN:
        try:
            import uuid
            from ctypes import wintypes as wt

            class GUID(ctypes.Structure):
                _fields_ = [('Data1', wt.DWORD), ('Data2', wt.WORD), ('Data3', wt.WORD), ('Data4', ctypes.c_ubyte * 8)]

            guid = GUID()
            ctypes.memmove(ctypes.byref(guid), uuid.UUID('{374DE290-123F-4565-9164-39C4925E467B}').bytes_le, 16)
            out = ctypes.c_wchar_p()
            fn = ctypes.windll.shell32.SHGetKnownFolderPath
            fn.argtypes = [ctypes.POINTER(GUID), wt.DWORD, wt.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
            if fn(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if path:
                    return path
        except Exception:
            pass
    return os.path.join(os.path.expanduser('~'), 'Downloads')


def system_dark_mode():
    if not IS_WIN:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
    except OSError:
        return False


def hwnd_of(window):
    window.update_idletasks()
    return _user32.GetParent(window.winfo_id()) or window.winfo_id()


def set_titlebar_theme(window, dark):
    """Dark or light native title bar (Windows 10 1809+ / Windows 11)."""
    if not IS_WIN:
        return
    try:
        hwnd = hwnd_of(window)
        value = ctypes.c_int(1 if dark else 0)
        dwm = ctypes.windll.dwmapi
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def force_foreground(window):
    """Bring a window to the front even when another app has focus."""
    if not IS_WIN:
        return
    try:
        hwnd = hwnd_of(window)
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        fg = _user32.GetForegroundWindow()
        fg_thread = _user32.GetWindowThreadProcessId(fg, None)
        me = _kernel32.GetCurrentThreadId()
        if fg_thread and fg_thread != me:
            _user32.AttachThreadInput(fg_thread, me, True)
            _user32.BringWindowToTop(hwnd)
            _user32.SetForegroundWindow(hwnd)
            _user32.AttachThreadInput(fg_thread, me, False)
        else:
            _user32.BringWindowToTop(hwnd)
            _user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


FSCTL_SET_SPARSE = 0x000900C4


def set_sparse(fileobj, sparse=True):
    """Mark a file sparse so writing far into a pre-sized file does not zero-fill the gap."""
    if not IS_WIN:
        return False
    try:
        import msvcrt
        handle = msvcrt.get_osfhandle(fileobj.fileno())
        flag = ctypes.c_ubyte(1 if sparse else 0)
        returned = wintypes.DWORD()
        return bool(_kernel32.DeviceIoControl(handle, FSCTL_SET_SPARSE, ctypes.byref(flag), 1, None, 0,
                                              ctypes.byref(returned), None))
    except Exception:
        return False


def open_file(path):
    try:
        if IS_WIN:
            os.startfile(path)
        else:
            subprocess.Popen(['xdg-open', path])
        return True
    except OSError:
        return False


def show_in_folder(path):
    if IS_WIN and path and os.path.exists(path) and os.path.isfile(path):
        subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
        return
    folder = path if path and os.path.isdir(path) else os.path.dirname(path or '')
    if folder and os.path.isdir(folder):
        open_file(folder)


def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def create_shortcut(lnk_path, target, arguments='', workdir='', icon=''):
    if not IS_WIN:
        return False
    os.makedirs(os.path.dirname(lnk_path), exist_ok=True)
    script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(lnk_path)});"
              f"$s.TargetPath={_ps_quote(target)};$s.Arguments={_ps_quote(arguments)};"
              f"$s.WorkingDirectory={_ps_quote(workdir)};")
    if icon:
        script += f"$s.IconLocation={_ps_quote(icon)};"
    script += "$s.Save()"
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                           creationflags=CREATE_NO_WINDOW, capture_output=True, timeout=30)
        return r.returncode == 0 and os.path.exists(lnk_path)
    except (OSError, subprocess.SubprocessError):
        return False


def startup_shortcut_path(app_name):
    return os.path.join(os.environ.get('APPDATA', ''), r'Microsoft\Windows\Start Menu\Programs\Startup',
                        app_name + '.lnk')


def find_browser(exe):
    """Locate chrome.exe / msedge.exe / brave.exe."""
    if not IS_WIN:
        return None
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}') as key:
                path = winreg.QueryValue(key, None)
                if path and os.path.exists(path.strip('"')):
                    return path.strip('"')
        except OSError:
            pass
    rel = {
        'chrome.exe': r'Google\Chrome\Application\chrome.exe',
        'msedge.exe': r'Microsoft\Edge\Application\msedge.exe',
        'brave.exe': r'BraveSoftware\Brave-Browser\Application\brave.exe',
    }.get(exe)
    if rel:
        for base in (os.environ.get('PROGRAMFILES'), os.environ.get('PROGRAMFILES(X86)'), os.environ.get('LOCALAPPDATA')):
            if base and os.path.exists(os.path.join(base, rel)):
                return os.path.join(base, rel)
    return None
