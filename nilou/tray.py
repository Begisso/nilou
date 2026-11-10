"""Windows notification-area (tray) icon with a menu and balloon/toast notifications.

Pure ctypes: a hidden window on its own thread receives the tray callbacks and
forwards them to the UI through a callback that must be thread-safe (the UI
uses a queue).
"""
import ctypes
import sys
import threading

AVAILABLE = sys.platform == 'win32'

if AVAILABLE:
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    LRESULT = wintypes.LPARAM
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                    ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
                    ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                    ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD),
                    ('Data4', ctypes.c_ubyte * 8)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND), ('uID', wintypes.UINT),
                    ('uFlags', wintypes.UINT), ('uCallbackMessage', wintypes.UINT), ('hIcon', wintypes.HICON),
                    ('szTip', ctypes.c_wchar * 128), ('dwState', wintypes.DWORD), ('dwStateMask', wintypes.DWORD),
                    ('szInfo', ctypes.c_wchar * 256), ('uVersion', wintypes.UINT),
                    ('szInfoTitle', ctypes.c_wchar * 64), ('dwInfoFlags', wintypes.DWORD), ('guidItem', GUID),
                    ('hBalloonIcon', wintypes.HICON)]

    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wintypes.UINT
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadIconW.restype = wintypes.HICON
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      wintypes.HWND, ctypes.c_void_p]
    user32.TrackPopupMenu.restype = ctypes.c_int
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_USER, NIIF_LARGE_ICON = 0x4, 0x20
WM_APP = 0x8000
WM_TRAY = WM_APP + 21
WM_CLOSE, WM_DESTROY, WM_NULL = 0x0010, 0x0002, 0x0000
WM_LBUTTONUP, WM_RBUTTONUP, WM_LBUTTONDBLCLK = 0x0202, 0x0205, 0x0203
NIN_BALLOONUSERCLICK = 0x0405
MF_STRING, MF_SEPARATOR, MF_GRAYED = 0x0, 0x800, 0x1
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x100
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10


class TrayIcon:
    def __init__(self, icon_path, tooltip, on_event, menu_items):
        """on_event(name) is called from the tray thread with 'activate', 'balloon' or ('menu', id).
        menu_items() returns [(id, text, enabled) | None] and is called from the tray thread."""
        self.icon_path = icon_path
        self.tooltip = tooltip
        self.on_event = on_event
        self.menu_items = menu_items
        self.hwnd = None
        self.ok = False
        self._ready = threading.Event()
        self._icon = None
        self._big_icon = None
        if AVAILABLE:
            self._thread = threading.Thread(target=self._run, name='nilou-tray', daemon=True)
            self._thread.start()
            self._ready.wait(5)

    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def _load_icon(self, size):
        h = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE) if self.icon_path else None
        return h or user32.LoadIconW(None, ctypes.c_void_p(32512))

    def _add(self):
        nid = self._nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._icon
        nid.szTip = self.tooltip[:127]
        return bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))

    def _run(self):
        try:
            hinst = kernel32.GetModuleHandleW(None)
            self._proc_ref = WNDPROC(self._wndproc)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._proc_ref
            wc.hInstance = hinst
            wc.lpszClassName = 'NilouTrayWindow'
            user32.RegisterClassW(ctypes.byref(wc))
            self.hwnd = user32.CreateWindowExW(0, 'NilouTrayWindow', 'Nilou', 0, 0, 0, 0, 0, None, None, hinst, None)
            self._taskbar_created = user32.RegisterWindowMessageW('TaskbarCreated')
            self._icon = self._load_icon(user32.GetSystemMetrics(49) or 16)        # SM_CXSMICON
            self._big_icon = self._load_icon(user32.GetSystemMetrics(11) or 32)    # SM_CXICON
            self.ok = self._add()
        finally:
            self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.on_event('activate')
                elif event == WM_RBUTTONUP:
                    self._show_menu()
                elif event == NIN_BALLOONUSERCLICK:
                    self.on_event('balloon')
                return 0
            if msg == self._taskbar_created:      # Explorer restarted
                self._add()
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                nid = self._nid()
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        items = self.menu_items()
        menu = user32.CreatePopupMenu()
        first = None
        for item in items:
            if item is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                continue
            cmd, text, enabled = item
            user32.AppendMenuW(menu, MF_STRING | (0 if enabled else MF_GRAYED), cmd, text)
            if first is None:
                first = cmd
        if first is not None:
            user32.SetMenuDefaultItem(menu, first, 0)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd:
            self.on_event(('menu', cmd))

    # --- called from the UI thread ---
    def set_tooltip(self, text):
        if not self.ok or text == self.tooltip:
            return
        self.tooltip = text
        nid = self._nid()
        nid.uFlags = NIF_TIP
        nid.szTip = text[:127]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def notify(self, title, message):
        if not self.ok:
            return
        nid = self._nid()
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = message[:255] or ' '
        nid.dwInfoFlags = NIIF_USER | NIIF_LARGE_ICON
        nid.hBalloonIcon = self._big_icon
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def stop(self):
        if AVAILABLE and self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self._thread.join(2)
