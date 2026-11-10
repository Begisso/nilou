"""Nilou's main window."""
import collections
import logging
import os
import queue
import shutil
import time
import tkinter as tk
from tkinter import ttk

from . import APP_NAME, VERSION, paths, tray, util, winutil
from .dialogs import AddDialog, BrowserSetupDialog, ConfirmDialog, GrabDialog, MediaDialog, SettingsDialog
from .engine import COMPLETED, DOWNLOADING, ERROR, PAUSED, QUEUED
from .theme import CATEGORY_COLORS, CATEGORY_ICONS, IconButton, Theme

log = logging.getLogger('nilou')

COLUMNS = [  # key, title, width (0 = flexible), anchor
    ('name', 'Name', 0, 'w'),
    ('size', 'Size', 150, 'e'),
    ('progress', 'Progress', 210, 'w'),
    ('speed', 'Speed', 92, 'e'),
    ('eta', 'Time left', 88, 'e'),
    ('added', 'Added', 82, 'e'),
]
FILTERS = [
    ('all', 'All downloads', 'all'),
    ('active', 'Downloading', 'active'),
    ('completed', 'Completed', 'completed'),
    ('unfinished', 'Unfinished', 'unfinished'),
    None,
    ('cat:Video', 'Video', 'video'),
    ('cat:Music', 'Music', 'music'),
    ('cat:Images', 'Images', 'image'),
    ('cat:Documents', 'Documents', 'document'),
    ('cat:Archives', 'Archives', 'archive'),
    ('cat:Programs', 'Programs', 'program'),
    ('cat:Other', 'Other', 'other'),
]
TRAY_OPEN, TRAY_ADD, TRAY_VIDEO, TRAY_PAUSE, TRAY_RESUME, TRAY_EXIT = 1, 2, 3, 4, 5, 9
_VIDEO_URL = ('youtube.com/watch', 'youtu.be/', 'youtube.com/shorts/', '/status/')


def round_rect(c, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1,
           x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


class App:
    version = VERSION

    def __init__(self, manager, server, server_ok=True, start_hidden=False):
        self.m = manager
        self.server = server
        self.server_ok = server_ok
        self.q = queue.Queue()
        self.root = tk.Tk(className=APP_NAME)
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.report_callback_exception = self._report_error
        self._icons = []
        for size in (16, 32, 48, 256):
            path = paths.resource_path('assets', f'nilou-{size}.png')
            if os.path.exists(path):
                self._icons.append(tk.PhotoImage(file=path))
        if self._icons:
            self.root.iconphoto(True, *self._icons)
        self.filter = 'all'
        self.search = ''
        self.sort_key, self.sort_desc = 'added', True
        self.selected = set()
        self.anchor = None
        self.hover = None
        self.side_hover = None
        self.scroll = 0.0
        self.rows = []
        self._fit_cache = {}
        self._last_clip = None
        self._last_done = None
        self._quitting = False
        self.theme = None
        self._build_all()
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.root.bind('<Unmap>', self._on_unmap)
        self.tray = None
        if tray.AVAILABLE:
            ico = paths.resource_path('assets', 'nilou.ico')
            self.tray = tray.TrayIcon(ico if os.path.exists(ico) else None, APP_NAME, self._tray_event,
                                      self._tray_menu)
        self._restore_geometry()
        if not (start_hidden and self.tray and self.tray.ok):
            self.show()
        self.root.after(120, self._poll)
        self.root.after(300, self._tick)
        self.root.after(1500, self._watch_clipboard)

    # ------------------------------------------------------------------ building
    def _build_all(self):
        for child in self.root.winfo_children():
            child.destroy()
        self.theme = Theme(self.root, self.m.settings['theme'])
        self._fit_cache.clear()
        t, p, S = self.theme, self.theme.p, self.theme.S
        self.rh = S(44)
        self.root.configure(bg=p['bg'])
        self.root.minsize(S(940), S(560))
        logo_path = paths.resource_path('assets', 'nilou-32.png' if t.scale < 1.4 else 'nilou-48.png')
        self.logo = tk.PhotoImage(file=logo_path) if os.path.exists(logo_path) else None

        # toolbar
        tb = tk.Frame(self.root, bg=p['bg'])
        tb.pack(fill='x', side='top', padx=(S(208), S(16)), pady=(S(14), S(10)))
        self.btn_add = IconButton(tb, t, 'Add URL', 'add', self.add_url, kind='primary', tooltip='Ctrl+N')
        self.btn_add.pack(side='left')
        IconButton(tb, t, 'Video', 'video', lambda: self.open_media(self._clipboard_url(video=True)),
                   tooltip='YouTube, X (Twitter) and more').pack(side='left', padx=(S(6), 0))
        IconButton(tb, t, 'Grab page', 'grab', lambda: self.open_grab(url=self._clipboard_url()),
                   tooltip='Pick images, videos and files from a web page').pack(side='left', padx=(S(2), 0))
        self._sep(tb)
        self.btn_resume = IconButton(tb, t, 'Resume', 'play', self.resume_selected)
        self.btn_pause = IconButton(tb, t, 'Pause', 'pause', self.pause_selected)
        self.btn_remove = IconButton(tb, t, 'Remove', 'delete', self.remove_selected, tooltip='Delete')
        self.btn_folder = IconButton(tb, t, '', 'folder', self.open_folder_selected, tooltip='Show in folder')
        for b in (self.btn_resume, self.btn_pause, self.btn_remove, self.btn_folder):
            b.pack(side='left', padx=(0, S(2)))
        IconButton(tb, t, '', 'more', self.show_more_menu, tooltip='More').pack(side='right')
        IconButton(tb, t, '', 'settings', self.open_settings, tooltip='Settings').pack(side='right', padx=(0, S(2)))
        self._build_search(tb)

        # status bar
        sb = tk.Frame(self.root, bg=p['bg'])
        sb.pack(fill='x', side='bottom', padx=(S(208), S(16)), pady=(S(6), S(10)))
        self.st_left = tk.Label(sb, bg=p['bg'], fg=p['subtext'], font=t.f_small, anchor='w')
        self.st_left.pack(side='left')
        self.st_browser = tk.Label(sb, bg=p['bg'], fg=p['subtext'], font=t.f_small, cursor='hand2')
        self.st_browser.pack(side='right')
        self.st_browser.bind('<Button-1>', lambda e: self.open_browser_setup())
        self.st_limit = tk.Label(sb, bg=p['bg'], fg=p['subtext'], font=t.f_small, cursor='hand2')
        self.st_limit.pack(side='right', padx=(0, S(18)))
        self.st_limit.bind('<Button-1>', self.show_limit_menu)

        # sidebar (placed so it spans the full height next to toolbar and status bar)
        self.side = tk.Canvas(self.root, width=S(196), bg=p['bg'], highlightthickness=0)
        self.side.place(x=0, y=0, width=S(196), relheight=1.0)
        self.side.bind('<Configure>', lambda e: self.draw_sidebar())
        self.side.bind('<Button-1>', self._side_click)
        self.side.bind('<Motion>', self._side_motion)
        self.side.bind('<Leave>', lambda e: self._side_motion(None))

        # main card
        body = tk.Frame(self.root, bg=p['bg'])
        body.pack(fill='both', expand=True, padx=(S(208), S(16)))
        card = tk.Frame(body, bg=p['surface'], highlightthickness=1, highlightbackground=p['border'])
        card.pack(fill='both', expand=True)
        self.details = tk.Canvas(card, height=S(148), bg=p['surface2'], highlightthickness=0)
        self.details.pack(fill='x', side='bottom')
        tk.Frame(card, height=1, bg=p['border']).pack(fill='x', side='bottom')
        self.header = tk.Canvas(card, height=S(36), bg=p['surface'], highlightthickness=0)
        self.header.pack(fill='x', side='top')
        self.header.bind('<Button-1>', self._header_click)
        wrap = tk.Frame(card, bg=p['surface'])
        wrap.pack(fill='both', expand=True)
        self.vbar = ttk.Scrollbar(wrap, orient='vertical', command=self._on_scrollbar,
                                  style='Slim.Vertical.TScrollbar')
        self.vbar.pack(side='right', fill='y', padx=(0, S(2)))
        self.list = tk.Canvas(wrap, bg=p['surface'], highlightthickness=0, takefocus=1)
        self.list.pack(side='left', fill='both', expand=True)
        self.list.bind('<Configure>', lambda e: self.redraw())
        self.list.bind('<Button-1>', lambda e: self._click(e, 'set'))
        self.list.bind('<Control-Button-1>', lambda e: self._click(e, 'toggle'))
        self.list.bind('<Shift-Button-1>', lambda e: self._click(e, 'range'))
        self.list.bind('<Double-Button-1>', self._double_click)
        self.list.bind('<Button-3>', self._right_click)
        self.list.bind('<Motion>', self._motion)
        self.list.bind('<Leave>', lambda e: self._set_hover(None))
        for w in (self.list, self.header, self.details):
            w.bind('<MouseWheel>', self._wheel)
        self.details.bind('<Configure>', lambda e: self.draw_details())
        self._bind_keys()
        tk.Misc.lift(self.side)
        winutil.set_titlebar_theme(self.root, self.theme.dark)

    def _sep(self, parent):
        S = self.theme.S
        tk.Frame(parent, width=1, height=S(22), bg=self.theme.p['border']).pack(side='left', padx=S(10))

    def _build_search(self, parent):
        t, p, S = self.theme, self.theme.p, self.theme.S
        box = tk.Frame(parent, bg=p['input'], highlightthickness=1, highlightbackground=p['input_border'],
                       highlightcolor=p['accent'])
        box.pack(side='right', padx=(0, S(10)))
        tk.Label(box, text=t.glyph('search'), font=t.f_icon_small, bg=p['input'], fg=p['muted']).pack(
            side='left', padx=(S(8), S(2)))
        self.search_var = tk.StringVar(value=self.search)
        entry = tk.Entry(box, textvariable=self.search_var, bd=0, bg=p['input'], fg=p['text'],
                         insertbackground=p['text'], font=t.f_body, width=22, relief='flat')
        entry.pack(side='left', ipady=S(5), padx=(S(4), S(8)))
        placeholder = tk.Label(box, text='Search downloads', bg=p['input'], fg=p['muted'], font=t.f_body)

        def sync(*_a):
            self.search = self.search_var.get().strip().lower()
            if self.search_var.get() or entry is self.root.focus_get():
                placeholder.place_forget()
            else:
                placeholder.place(in_=entry, x=0, rely=0.5, anchor='w')
            self.scroll = 0
            self.redraw()

        self.search_var.trace_add('write', sync)
        entry.bind('<FocusIn>', lambda e: placeholder.place_forget())
        entry.bind('<FocusOut>', sync)
        entry.bind('<Escape>', lambda e: (self.search_var.set(''), self.list.focus_set()))
        placeholder.bind('<Button-1>', lambda e: entry.focus_set())
        self.search_entry = entry
        self.root.after(50, sync)

    def _bind_keys(self):
        r = self.root

        def guard(fn):
            def handler(event):
                if isinstance(r.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox, ttk.Spinbox)):
                    return None
                fn()
                return 'break'
            return handler

        r.bind('<Control-n>', lambda e: self.add_url())
        r.bind('<Control-f>', lambda e: self.search_entry.focus_set())
        r.bind('<Control-v>', guard(self.paste))
        r.bind('<Delete>', guard(self.remove_selected))
        r.bind('<Return>', guard(self.open_selected))
        r.bind('<Control-a>', guard(self.select_all))
        r.bind('<space>', guard(self.toggle_selected))
        r.bind('<Up>', guard(lambda: self.move_selection(-1)))
        r.bind('<Down>', guard(lambda: self.move_selection(1)))

    def rebuild(self):
        self._build_all()
        self.refresh()

    # ------------------------------------------------------------------ window state
    def _restore_geometry(self):
        S = self.theme.S
        geo = self.m.settings.get('geometry')
        if geo:
            try:
                self.root.geometry(geo)
            except tk.TclError:
                geo = ''
        if not geo:
            w, h = S(1240), S(720)
            x = max(0, (self.root.winfo_screenwidth() - w) // 2)
            y = max(0, (self.root.winfo_screenheight() - h) // 3)
            self.root.geometry(f'{w}x{h}+{x}+{y}')

    def _remember_geometry(self):
        try:
            state = self.root.state()
            if state == 'normal':
                self.m.settings['geometry'] = self.root.geometry()
            self.m.settings['zoomed'] = state == 'zoomed'
        except tk.TclError:
            pass

    def show(self):
        self.root.deiconify()
        if self.m.settings.get('zoomed'):
            self.root.state('zoomed')
        self.root.lift()
        winutil.set_titlebar_theme(self.root, self.theme.dark)
        winutil.force_foreground(self.root)
        self.refresh()

    def hide(self):
        self._remember_geometry()
        self.root.withdraw()
        if not self.m.settings.get('tray_hint_shown'):
            self.m.settings['tray_hint_shown'] = True
            self.m.save_settings()
            self.notify('Nilou is still running', 'It keeps catching downloads from the tray. '
                                                  'Right-click the lotus icon to exit.')

    def on_close(self):
        if self.m.settings['close_to_tray'] and self.tray and self.tray.ok:
            self.hide()
        else:
            self.quit()

    def _on_unmap(self, event):
        if event.widget is not self.root or self._quitting:
            return
        if self.m.settings['minimize_to_tray'] and self.tray and self.tray.ok:
            self.root.after(30, lambda: self.root.state() == 'iconic' and self.hide())

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        if self.root.state() != 'withdrawn':
            self._remember_geometry()
        try:
            self.m.shutdown()
        finally:
            if self.server:
                self.server.stop()
            if self.tray:
                self.tray.stop()
            self.root.destroy()

    def run(self):
        self.root.mainloop()

    def notify(self, title, message):
        if self.tray and self.tray.ok:
            self.tray.notify(title, message)

    def _report_error(self, exc, val, tb):
        log.error('UI error', exc_info=(exc, val, tb))

    # ------------------------------------------------------------------ events from other threads
    def api(self, action, data):
        """Called on the local server thread."""
        if action == 'show':
            self.q.put(('show', None))
            return True, ''
        if action in ('download', 'add', 'media'):
            url = str(data.get('url') or '')
            if not url.lower().startswith(('http://', 'https://')):
                return False, 'only http(s) links are supported'
            self.q.put(('media' if action == 'media' else 'download', data))
            return True, ''
        if action == 'grab':
            items = data.get('items') or []
            if not isinstance(items, list):
                return False, 'bad items'
            clean = [it for it in items[:5000] if isinstance(it, dict)
                     and str(it.get('url', '')).lower().startswith(('http://', 'https://'))]
            self.q.put(('grab', dict(data, items=clean)))
            return True, ''
        return False, 'unknown action'

    def _tray_event(self, event):
        self.q.put(('tray', event))

    def _tray_menu(self):
        st = self.m.stats()
        return [(TRAY_OPEN, 'Open Nilou', True), (TRAY_ADD, 'Add download…', True),
                (TRAY_VIDEO, 'Download video…', True), None,
                (TRAY_PAUSE, 'Pause all', st['active'] + st['queued'] > 0), (TRAY_RESUME, 'Resume all', True), None,
                (TRAY_EXIT, 'Exit Nilou', True)]

    @staticmethod
    def _headers_from(data):
        h = {}
        if data.get('cookies'):
            h['Cookie'] = str(data['cookies'])
        if data.get('referrer'):
            h['Referer'] = str(data['referrer'])
        if data.get('userAgent'):
            h['User-Agent'] = str(data['userAgent'])
        return h

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                try:
                    self._handle(kind, data)
                except Exception:  # noqa: BLE001
                    log.exception('event %s failed', kind)
        except queue.Empty:
            pass
        try:
            while True:
                _ev, d = self.m.events.get_nowait()
                self._finished(d)
        except queue.Empty:
            pass
        if not self._quitting:
            self.root.after(120, self._poll)

    def _handle(self, kind, data):
        if kind == 'show':
            self.show()
        elif kind == 'tray':
            if data == 'activate':
                if self.root.state() in ('withdrawn', 'iconic'):
                    self.show()
                else:
                    winutil.force_foreground(self.root)
            elif data == 'balloon':
                d = self.m.get(self._last_done) if self._last_done else None
                if d and d.status == COMPLETED:
                    winutil.show_in_folder(d.path)
                else:
                    self.show()
            elif isinstance(data, tuple) and data[0] == 'menu':
                cmd = data[1]
                if cmd == TRAY_OPEN:
                    self.show()
                elif cmd == TRAY_ADD:
                    self.add_url()
                elif cmd == TRAY_VIDEO:
                    self.open_media(self._clipboard_url(video=True))
                elif cmd == TRAY_PAUSE:
                    self.m.pause_all()
                elif cmd == TRAY_RESUME:
                    self.m.resume_all()
                elif cmd == TRAY_EXIT:
                    self.quit()
        elif kind == 'download':
            url = str(data['url'])
            headers = self._headers_from(data)
            name = util.sanitize_filename(str(data.get('filename') or ''), '') or ''
            size = data.get('size') if isinstance(data.get('size'), int) else -1
            if self.m.settings['browser_show_dialog'] or data.get('ask'):
                AddDialog(self, url, name, headers, from_browser=True, size=size)
            else:
                d = self.m.add(url, filename=name or None, headers=headers, size=size)
                self.notify('Downloading with Nilou', name or util.filename_from_url(url) or url)
                self.selected = {d.id}
        elif kind == 'media':
            cookies = data.get('cookieList') if isinstance(data.get('cookieList'), list) else None
            headers = {'Referer': str(data['referrer'])} if data.get('referrer') else {}
            self.open_media(str(data['url']), cookies=cookies, headers=headers)
        elif kind == 'grab':
            cookies = data.get('cookies') if isinstance(data.get('cookies'), dict) else {}
            GrabDialog(self, str(data.get('page') or ''), str(data.get('title') or ''), data['items'],
                       {str(k): str(v) for k, v in cookies.items()})

    def _finished(self, d):
        if d.status == COMPLETED:
            self._last_done = d.id
        if not self.m.settings['notify_complete']:
            return
        focused = self.root.state() == 'normal' and self.root.focus_displayof() is not None
        if focused:
            return
        if d.status == COMPLETED:
            self.notify('Download complete', d.display_name)
        elif d.status == ERROR:
            self.notify('Download failed', f'{d.display_name}\n{d.error}')

    def _watch_clipboard(self):
        if self._quitting:
            return
        if self.m.settings['clipboard_monitor']:
            try:
                text = self.root.clipboard_get()
            except tk.TclError:
                text = ''
            if text != self._last_clip:
                first = self._last_clip is None
                self._last_clip = text
                urls = util.extract_urls(text) if not first else []
                if len(urls) == 1 and text.strip() == urls[0]:
                    url = urls[0]
                    name = util.filename_from_url(url)
                    if util.is_media_site(url) and any(k in url for k in _VIDEO_URL):
                        self.open_media(url)
                    elif util.category_of(name) != 'Other' and util.extension(name) not in ('html', 'htm', 'php'):
                        AddDialog(self, url)
        self.root.after(1000, self._watch_clipboard)

    # ------------------------------------------------------------------ actions
    def _clipboard_url(self, video=False):
        try:
            urls = util.extract_urls(self.root.clipboard_get())
        except tk.TclError:
            return ''
        if not urls:
            return ''
        if video and not util.is_media_site(urls[0]):
            return ''
        return urls[0]

    def add_url(self, url=None):
        url = url if url is not None else self._clipboard_url()
        if url and util.is_media_site(url):
            self.open_media(url)
        else:
            AddDialog(self, url)

    def paste(self):
        self.add_url(self._clipboard_url() or '')

    def open_media(self, url='', cookies=None, headers=None):
        MediaDialog(self, url or '', cookies, headers)

    def open_grab(self, url='', headers=None):
        GrabDialog(self, url or '', headers=headers)

    def open_settings(self):
        SettingsDialog(self)

    def open_browser_setup(self):
        BrowserSetupDialog(self)

    def after_add(self):
        newest = max(self.m.downloads, key=lambda d: d.added, default=None)
        if newest:
            self.selected = {newest.id}
            if self.filter not in ('all', 'active'):
                self.filter = 'all'
        self.scroll = 0
        self.refresh()

    def selection(self):
        return [d for d in self.rows if d.id in self.selected]

    def resume_selected(self):
        self.m.resume(self.selection())
        self.refresh()

    def pause_selected(self):
        self.m.pause(self.selection())
        self.refresh()

    def toggle_selected(self):
        items = self.selection()
        if any(d.status in (DOWNLOADING, QUEUED) for d in items):
            self.pause_selected()
        else:
            self.resume_selected()

    def restart_selected(self):
        self.m.restart(self.selection())
        self.refresh()

    def remove_selected(self):
        items = self.selection()
        if not items:
            return
        done = sum(1 for d in items if d.status == COMPLETED)
        what = f'“{items[0].display_name}”' if len(items) == 1 else f'{len(items)} downloads'
        msg = 'Unfinished parts are deleted. ' if done < len(items) else ''
        msg += 'Finished files stay on your disk unless you tick the box below.' if done else ''
        ConfirmDialog(self, f'Remove {what} from the list?', msg.strip() or 'This cannot be undone.', 'Remove',
                      lambda delete: (self.m.remove(items, delete), self.selected.clear(), self.refresh()),
                      checkbox='Also delete the downloaded files' if done else None)

    def open_selected(self):
        items = self.selection()
        if len(items) == 1:
            d = items[0]
            if d.status == COMPLETED and d.path and os.path.exists(d.path):
                winutil.open_file(d.path)
            elif d.status in (PAUSED, ERROR):
                self.m.resume([d])

    def open_folder_selected(self):
        items = self.selection()
        d = items[0] if items else None
        if d is None:
            winutil.open_file(self.m.default_folder())
        elif d.status == COMPLETED and d.path and os.path.exists(d.path):
            winutil.show_in_folder(d.path)
        else:
            winutil.open_file(d.folder if os.path.isdir(d.folder) else self.m.default_folder())

    def copy_url(self):
        items = self.selection()
        if items:
            self.root.clipboard_clear()
            self.root.clipboard_append('\n'.join(d.url for d in items))

    def select_all(self):
        self.selected = {d.id for d in self.rows}
        self.redraw()

    def move_selection(self, delta):
        if not self.rows:
            return
        ids = [d.id for d in self.rows]
        current = [i for i, x in enumerate(ids) if x in self.selected]
        i = (current[-1] if delta > 0 else current[0]) + delta if current else 0
        i = max(0, min(len(ids) - 1, i))
        self.selected = {ids[i]}
        self.anchor = ids[i]
        top = i * self.rh
        height = self.list.winfo_height()
        if top < self.scroll:
            self.scroll = top
        elif top + self.rh > self.scroll + height:
            self.scroll = top + self.rh - height
        self.redraw()

    def extension_dir(self):
        dest = os.path.join(paths.data_dir(), 'browser-extension')
        try:
            shutil.copytree(paths.resource_path('extension'), dest, dirs_exist_ok=True)
        except OSError:
            log.exception('could not unpack the extension')
        return dest

    def extension_connected(self):
        return bool(self.server and time.time() - self.server.extension_seen < 180)

    def apply_startup(self, enabled):
        lnk = winutil.startup_shortcut_path(APP_NAME)
        if enabled:
            exe, args = paths.launch_command()
            icon = exe if paths.FROZEN else paths.resource_path('assets', 'nilou.ico')
            winutil.create_shortcut(lnk, exe, (args + ' --minimized').strip(), paths.app_dir(), icon)
        else:
            try:
                os.remove(lnk)
            except OSError:
                pass

    # ------------------------------------------------------------------ menus
    def _menu(self):
        p = self.theme.p
        return tk.Menu(self.root, tearoff=False, bg=p['surface'], fg=p['text'], activebackground=p['select'],
                       activeforeground=p['text'], font=self.theme.f_body, bd=0)

    def show_more_menu(self):
        m = self._menu()
        m.add_command(label='Open downloads folder', command=lambda: winutil.open_file(self.m.default_folder()))
        m.add_command(label='Connect your browser…', command=self.open_browser_setup)
        m.add_separator()
        m.add_command(label='Resume all', command=self.m.resume_all)
        m.add_command(label='Pause all', command=self.m.pause_all)
        m.add_command(label='Clear completed from list', command=lambda: (self.m.clear_completed(), self.refresh()))
        m.add_separator()
        m.add_command(label='Settings', command=self.open_settings)
        m.add_command(label='Exit Nilou', command=self.quit)
        x, y = self.root.winfo_pointerxy()
        m.tk_popup(x, y)

    def show_limit_menu(self, _event=None):
        m = self._menu()
        current = self.m.settings['speed_limit_kbps']
        var = tk.IntVar(value=current)
        for kbps, label in ((0, 'No limit'), (256, '256 KB/s'), (512, '512 KB/s'), (1024, '1 MB/s'),
                            (2048, '2 MB/s'), (5120, '5 MB/s'), (10240, '10 MB/s')):
            m.add_radiobutton(label=label, variable=var, value=kbps,
                              command=lambda k=kbps: (self.m.set_speed_limit(k), self.refresh()))
        m.add_separator()
        m.add_command(label='Custom… (Settings)', command=self.open_settings)
        m._var = var
        x, y = self.root.winfo_pointerxy()
        m.tk_popup(x, y)

    def _right_click(self, e):
        i = self._row_at(e.y)
        if i is not None and self.rows[i].id not in self.selected:
            self.selected = {self.rows[i].id}
            self.anchor = self.rows[i].id
            self.redraw()
        items = self.selection()
        if not items:
            return
        m = self._menu()
        single = items[0] if len(items) == 1 else None
        if single and single.status == COMPLETED:
            m.add_command(label='Open', command=self.open_selected)
        m.add_command(label='Show in folder', command=self.open_folder_selected)
        m.add_separator()
        if any(d.status in (PAUSED, ERROR) for d in items):
            m.add_command(label='Resume', command=self.resume_selected)
        if any(d.status in (DOWNLOADING, QUEUED) for d in items):
            m.add_command(label='Pause', command=self.pause_selected)
        m.add_command(label='Download again' if single and single.status == COMPLETED else 'Restart from zero',
                      command=self.restart_selected)
        m.add_separator()
        m.add_command(label='Copy link', command=self.copy_url)
        m.add_separator()
        m.add_command(label='Remove…', command=self.remove_selected)
        m.tk_popup(e.x_root, e.y_root)

    # ------------------------------------------------------------------ list interaction
    def _row_at(self, y):
        i = int((y + self.scroll) // self.rh)
        return i if 0 <= i < len(self.rows) else None

    def _click(self, e, mode):
        self.list.focus_set()
        i = self._row_at(e.y)
        if i is None:
            if mode == 'set':
                self.selected.clear()
                self.anchor = None
            self.redraw()
            return
        d = self.rows[i]
        if mode == 'toggle':
            self.selected ^= {d.id}
            self.anchor = d.id
        elif mode == 'range' and self.anchor is not None:
            ids = [x.id for x in self.rows]
            a = ids.index(self.anchor) if self.anchor in ids else i
            lo, hi = sorted((a, i))
            self.selected = set(ids[lo:hi + 1])
        else:
            self.selected = {d.id}
            self.anchor = d.id
        self.redraw()

    def _double_click(self, e):
        i = self._row_at(e.y)
        if i is not None:
            self.selected = {self.rows[i].id}
            self.open_selected()

    def _motion(self, e):
        self._set_hover(self._row_at(e.y))

    def _set_hover(self, i):
        d = self.rows[i].id if i is not None and i < len(self.rows) else None
        if d != self.hover:
            self.hover = d
            self.draw_list()

    def _wheel(self, e):
        self.scroll -= (e.delta / 120.0) * self.rh * 2
        self.draw_list()

    def _on_scrollbar(self, *args):
        total = len(self.rows) * self.rh
        height = self.list.winfo_height()
        if args[0] == 'moveto':
            self.scroll = float(args[1]) * total
        elif args[0] == 'scroll':
            step = self.rh if args[2] == 'units' else height
            self.scroll += int(args[1]) * step
        self.draw_list()

    def _header_click(self, e):
        for key, _title, x0, x1, _a in self._layout(self.list.winfo_width()):
            if x0 - self.theme.S(8) <= e.x <= x1 + self.theme.S(8):
                if self.sort_key == key:
                    self.sort_desc = not self.sort_desc
                else:
                    self.sort_key, self.sort_desc = key, key in ('added', 'size', 'speed', 'progress')
                self.redraw()
                return

    def _side_click(self, e):
        for y0, y1, key in getattr(self, '_side_hits', []):
            if y0 <= e.y < y1:
                self.filter = key
                self.scroll = 0
                self.redraw()
                return

    def _side_motion(self, e):
        key = None
        if e is not None:
            key = next((k for y0, y1, k in getattr(self, '_side_hits', []) if y0 <= e.y < y1), None)
        if key != self.side_hover:
            self.side_hover = key
            self.side.configure(cursor='hand2' if key else '')
            self.draw_sidebar()

    # ------------------------------------------------------------------ drawing
    def _tick(self):
        if self._quitting:
            return
        try:
            self.refresh()
        except Exception:  # noqa: BLE001
            log.exception('refresh failed')
        self.root.after(500, self._tick)

    def refresh(self):
        if self.root.state() == 'withdrawn':
            self._update_tray_tip()
            return
        self.redraw()
        self._update_status()
        self._update_tray_tip()

    def redraw(self):
        self._compute_rows()
        self.draw_header()
        self.draw_list()
        self.draw_sidebar()
        self._update_toolbar()
        self.draw_details()

    def _match(self, d):
        f = self.filter
        if f == 'active' and d.status not in (DOWNLOADING, QUEUED):
            return False
        if f == 'completed' and d.status != COMPLETED:
            return False
        if f == 'unfinished' and d.status not in (PAUSED, ERROR):
            return False
        if f.startswith('cat:') and d.category != f[4:]:
            return False
        if self.search and self.search not in d.display_name.lower() and self.search not in d.url.lower():
            return False
        return True

    def _compute_rows(self):
        with self.m.lock:
            items = [d for d in self.m.downloads if self._match(d)]
        key = self.sort_key
        status_rank = {DOWNLOADING: 0, QUEUED: 1, PAUSED: 2, ERROR: 3, COMPLETED: 4}
        keyfn = {
            'name': lambda d: d.display_name.lower(),
            'size': lambda d: d.size,
            'progress': lambda d: (-status_rank[d.status], d.progress or 0),
            'speed': lambda d: d.speed,
            'eta': lambda d: (d.size - d.downloaded) if d.size > 0 else 0,
            'added': lambda d: d.added,
        }[key]
        items.sort(key=keyfn, reverse=self.sort_desc)
        self.rows = items
        alive = {d.id for d in self.m.downloads}
        self.selected &= alive

    def _layout(self, width):
        S = self.theme.S
        pad, gap = S(18), S(18)
        cols = list(COLUMNS)

        def fixed(cs):
            return sum(S(w) for _k, _t, w, _a in cs if w) + gap * (len(cs) - 1) + 2 * pad

        for drop in ('added', 'eta'):
            if width - fixed(cols) < S(240):
                cols = [c for c in cols if c[0] != drop]
        name_w = max(S(140), width - fixed(cols))
        out, x = [], pad
        for key, title, w, anchor in cols:
            cw = name_w if w == 0 else S(w)
            out.append((key, title, x, x + cw, anchor))
            x += cw + gap
        return out

    def _fit(self, text, font, width):
        key = (text, str(font), int(width))
        hit = self._fit_cache.get(key)
        if hit is not None:
            return hit
        if font.measure(text) <= width:
            result = text
        else:
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if font.measure(text[:mid] + '…') <= width:
                    lo = mid
                else:
                    hi = mid - 1
            result = text[:lo] + '…'
        if len(self._fit_cache) > 4000:
            self._fit_cache.clear()
        self._fit_cache[key] = result
        return result

    def draw_header(self):
        c, t, p, S = self.header, self.theme, self.theme.p, self.theme.S
        c.delete('all')
        width, height = c.winfo_width(), c.winfo_height()
        for key, title, x0, x1, anchor in self._layout(self.list.winfo_width()):
            active = key == self.sort_key
            x = x0 if anchor == 'w' else x1
            item = c.create_text(x, height / 2, text=title, anchor=anchor, font=t.f_small_bold,
                                 fill=p['text'] if active else p['subtext'])
            if active:
                bx0, _y0, bx1, _y1 = c.bbox(item)
                ax = bx1 + S(4) if anchor == 'w' else bx0 - S(4)
                c.create_text(ax, height / 2 + S(1), text=t.glyph('down' if self.sort_desc else 'up'),
                              font=t.f_icon_small, fill=p['accent'], anchor='w' if anchor == 'w' else 'e')
        c.create_line(0, height - 1, width, height - 1, fill=p['divider'])

    def _pill(self, c, x0, x1, cy, h, color):
        if x1 - x0 <= h:
            c.create_oval(x0, cy - h / 2, x0 + h, cy + h / 2, fill=color, outline='')
        else:
            c.create_line(x0 + h / 2, cy, x1 - h / 2, cy, width=h, fill=color, capstyle='round')

    def draw_list(self):
        c = self.list
        c.delete('all')
        width, height = c.winfo_width(), c.winfo_height()
        total = len(self.rows) * self.rh
        self.scroll = max(0.0, min(self.scroll, max(0, total - height)))
        if total <= height:
            self.vbar.set(0, 1)
            if self.vbar.winfo_ismapped():
                self.vbar.pack_forget()
        else:
            self.vbar.set(self.scroll / total, (self.scroll + height) / total)
            if not self.vbar.winfo_ismapped():
                self.vbar.pack(side='right', fill='y', padx=(0, self.theme.S(2)), before=self.list)
        if not self.rows:
            self._draw_empty(c, width, height)
            return
        cols = self._layout(width)
        first = int(self.scroll // self.rh)
        last = min(len(self.rows), int((self.scroll + height) // self.rh) + 1)
        for i in range(first, last):
            self._draw_row(c, self.rows[i], i * self.rh - self.scroll, width, cols)

    def _draw_empty(self, c, width, height):
        t, p, S = self.theme, self.theme.p, self.theme.S
        cy = height / 2 - S(30)
        if self.search:
            title, sub = 'Nothing matches your search', 'Try a different name or link.'
        elif self.filter != 'all':
            title, sub = 'Nothing here yet', 'Downloads in this view will show up here.'
        else:
            title = 'No downloads yet'
            sub = ('Click Add URL or press Ctrl+V to paste a link.\n'
                   'Connect your browser to catch downloads automatically.')
        c.create_text(width / 2, cy, text=t.glyph('download'), font=t.f_icon_big, fill=p['accent'])
        c.create_text(width / 2, cy + S(48), text=title, font=t.f_subtitle, fill=p['text'])
        c.create_text(width / 2, cy + S(80), text=sub, font=t.f_body, fill=p['subtext'], justify='center')

    def _draw_row(self, c, d, y, width, cols):
        t, p, S = self.theme, self.theme.p, self.theme.S
        rh = self.rh
        cy = y + rh / 2
        selected = d.id in self.selected
        if selected or d.id == self.hover:
            round_rect(c, S(6), y + S(2), width - S(4), y + rh - S(2), S(7),
                       fill=p['select'] if selected else p['hover'], outline='')
        if selected:
            c.create_line(S(9), y + S(13), S(9), y + rh - S(13), width=S(3), fill=p['accent'], capstyle='round')
        for key, _title, x0, x1, anchor in cols:
            if key == 'name':
                cat = d.category
                c.create_text(x0 + S(10), cy, text=t.glyph(CATEGORY_ICONS.get(cat, 'other')), font=t.f_icon,
                              fill=CATEGORY_COLORS.get(cat, p['muted']), anchor='center')
                name = self._fit(d.display_name, t.f_body, x1 - x0 - S(30))
                c.create_text(x0 + S(30), cy, text=name, font=t.f_body, fill=p['text'], anchor='w')
            elif key == 'size':
                if d.status != COMPLETED and d.downloaded > 0 and d.size > 0:
                    text = f'{util.fmt_size(d.downloaded)} / {util.fmt_size(d.size)}'
                elif d.size > 0:
                    text = util.fmt_size(d.size)
                elif d.downloaded > 0:
                    text = util.fmt_size(d.downloaded)
                else:
                    text = '—'
                c.create_text(x1, cy, text=self._fit(text, t.f_small, x1 - x0), font=t.f_small, fill=p['subtext'],
                              anchor='e')
            elif key == 'progress':
                self._draw_progress(c, d, x0, x1, cy)
            elif key == 'speed':
                if d.status == DOWNLOADING and d.speed > 0:
                    c.create_text(x1, cy, text=util.fmt_speed(d.speed), font=t.f_small, fill=p['text'], anchor='e')
            elif key == 'eta':
                if d.status == DOWNLOADING and d.speed > 0 and d.size > 0:
                    eta = d.eta if d.eta is not None else (d.size - d.downloaded) / d.speed
                    c.create_text(x1, cy, text=util.fmt_eta(eta), font=t.f_small, fill=p['subtext'], anchor='e')
            elif key == 'added':
                c.create_text(x1, cy, text=util.fmt_date(d.added), font=t.f_small, fill=p['muted'], anchor='e')

    def _draw_progress(self, c, d, x0, x1, cy):
        t, p, S = self.theme, self.theme.p, self.theme.S
        if d.status == COMPLETED:
            c.create_text(x0, cy, text=t.glyph('completed'), font=t.f_icon_small, fill=p['green'], anchor='w')
            c.create_text(x0 + S(20), cy, text='Completed', font=t.f_small, fill=p['green'], anchor='w')
            return
        if d.status == ERROR:
            c.create_text(x0, cy, text=t.glyph('error'), font=t.f_icon_small, fill=p['red'], anchor='w')
            c.create_text(x0 + S(20), cy, text=self._fit('Failed — ' + (d.error or 'error'), t.f_small,
                                                         x1 - x0 - S(20)),
                          font=t.f_small, fill=p['red'], anchor='w')
            return
        frac = d.progress
        h = S(6)
        bx0, bx1 = x0, x1 - S(84)
        color = {DOWNLOADING: p['accent'], PAUSED: p['amber'], QUEUED: p['muted']}.get(d.status, p['muted'])
        self._pill(c, bx0, bx1, cy, h, p['track'])
        if frac is None and d.status == DOWNLOADING:
            phase = (time.monotonic() % 1.6) / 1.6
            seg = (bx1 - bx0) * 0.3
            sx = bx0 + (bx1 - bx0 - seg) * phase
            self._pill(c, sx, sx + seg, cy, h, color)
        elif frac:
            self._pill(c, bx0, bx0 + max(h, (bx1 - bx0) * frac), cy, h, color)
        if d.status == DOWNLOADING:
            msg = d.message
            if msg.startswith('Reconnecting'):
                msg = 'Retrying…'
            elif msg.startswith('Converting'):
                msg = 'Converting…'
            label = msg or (f'{frac * 100:.1f}%' if frac is not None else 'Downloading')
        elif d.status == PAUSED:
            label = f'Paused · {frac * 100:.0f}%' if frac else 'Paused'
        else:
            label = 'Queued'
        c.create_text(bx1 + S(10), cy, text=label, font=t.f_small,
                      fill=p['subtext'] if d.status != PAUSED else p['amber'], anchor='w')

    def draw_sidebar(self):
        c, t, p, S = self.side, self.theme, self.theme.p, self.theme.S
        c.delete('all')
        width = c.winfo_width()
        y = S(16)
        if self.logo:
            c.create_image(S(22), y + S(16), image=self.logo, anchor='w')
            lx = S(22) + self.logo.width() + S(10)
        else:
            lx = S(22)
        c.create_text(lx, y + S(16), text=APP_NAME, font=t.f_hero, fill=p['text'], anchor='w')
        y += S(62)
        counts = collections.Counter()
        with self.m.lock:
            items = list(self.m.downloads)
        for d in items:
            counts['all'] += 1
            if d.status in (DOWNLOADING, QUEUED):
                counts['active'] += 1
            elif d.status == COMPLETED:
                counts['completed'] += 1
            else:
                counts['unfinished'] += 1
            counts['cat:' + d.category] += 1
        hits = []
        for entry in FILTERS:
            if entry is None:
                y += S(10)
                c.create_text(S(24), y + S(8), text='TYPES', font=t.f_small_bold, fill=p['muted'], anchor='w')
                y += S(24)
                continue
            key, label, icon = entry
            h = S(36)
            sel = key == self.filter
            if sel or key == self.side_hover:
                round_rect(c, S(10), y + S(1), width - S(8), y + h - S(1), S(7),
                           fill=p['select'] if sel else p['hover'], outline='')
            if sel:
                c.create_line(S(13), y + S(11), S(13), y + h - S(11), width=S(3), fill=p['accent'],
                              capstyle='round')
            if key.startswith('cat:'):
                icolor = CATEGORY_COLORS.get(key[4:], p['muted'])
            else:
                icolor = p['accent'] if sel else p['subtext']
            c.create_text(S(34), y + h / 2, text=t.glyph(icon), font=t.f_icon_small, fill=icolor, anchor='center')
            c.create_text(S(54), y + h / 2, text=label, font=t.f_bold if sel else t.f_body, fill=p['text'],
                          anchor='w')
            n = counts.get(key, 0)
            if n:
                c.create_text(width - S(20), y + h / 2, text=str(n), font=t.f_small, fill=p['muted'], anchor='e')
            hits.append((y, y + h, key))
            y += h
        self._side_hits = hits

    def draw_details(self):
        c, t, p, S = self.details, self.theme, self.theme.p, self.theme.S
        c.delete('all')
        width = c.winfo_width()
        pad = S(22)
        sel = self.selection()
        if len(sel) == 1:
            self._details_one(c, sel[0], width, pad)
            return
        st = self.m.stats()
        if sel:
            size = sum(d.size for d in sel if d.size > 0)
            done = sum(1 for d in sel if d.status == COMPLETED)
            c.create_text(pad, S(34), text=f'{len(sel)} downloads selected', font=t.f_title, fill=p['text'],
                          anchor='w')
            c.create_text(pad, S(64), text=f'{util.fmt_size(size)} in total · {done} completed',
                          font=t.f_body, fill=p['subtext'], anchor='w')
            return
        speed = util.fmt_speed(st['speed'])
        line = f"{st['total']} downloads · {st['active']} active" + (f' · {speed}' if speed else '')
        c.create_text(pad, S(34), text='Ready when you are', font=t.f_title, fill=p['text'], anchor='w')
        c.create_text(pad, S(62), text=line, font=t.f_body, fill=p['subtext'], anchor='w')
        tips = ['Paste any link with Ctrl+V — video links from YouTube and X open the video downloader.',
                'Right-click a link in your browser and choose “Download with Nilou”.']
        if not self.extension_connected():
            tips.append('Browser not connected yet — click “Connect browser” in the status bar.')
        for i, tip in enumerate(tips):
            c.create_text(pad, S(92) + i * S(20), text='•  ' + tip, font=t.f_small, fill=p['muted'], anchor='w')

    def _details_one(self, c, d, width, pad):
        t, p, S = self.theme, self.theme.p, self.theme.S
        cat = d.category
        c.create_text(pad + S(10), S(28), text=t.glyph(CATEGORY_ICONS.get(cat, 'other')), font=t.f_title,
                      fill=CATEGORY_COLORS.get(cat, p['muted']), anchor='center')
        c.create_text(pad + S(32), S(28), text=self._fit(d.display_name, t.f_subtitle, width - pad * 2 - S(32)),
                      font=t.f_subtitle, fill=p['text'], anchor='w')
        if d.status == ERROR:
            c.create_text(pad + S(32), S(50), text=self._fit(d.error, t.f_small, width - pad * 2 - S(32)),
                          font=t.f_small, fill=p['red'], anchor='w')
        else:
            c.create_text(pad + S(32), S(50), text=self._fit(d.url, t.f_small, width - pad * 2 - S(32)),
                          font=t.f_small, fill=p['muted'], anchor='w')
        # segment map
        x0, x1, y0, h = pad, width - pad, S(70), S(8)
        c.create_rectangle(x0, y0, x1, y0 + h, fill=p['track'], outline='')
        span = x1 - x0
        if d.status == COMPLETED:
            c.create_rectangle(x0, y0, x1, y0 + h, fill=p['green'], outline='')
        elif d.size > 0:
            segs = list(d.segments)
            color = p['amber'] if d.status == PAUSED else p['accent']
            if segs and d.kind == 'http':
                c.create_rectangle(x0, y0, x1, y0 + h, fill=color, outline='')
                for s in segs:
                    if s.end is None:
                        continue
                    sx0 = x0 + span * s.pos / d.size
                    sx1 = x0 + span * (s.end + 1) / d.size
                    c.create_rectangle(sx0, y0, sx1, y0 + h, fill=p['track'], outline='')
                    if s.active:
                        c.create_rectangle(sx0, y0 - S(2), sx0 + S(2), y0 + h + S(2), fill=p['text'], outline='')
            else:
                c.create_rectangle(x0, y0, x0 + span * min(1.0, d.downloaded / d.size), y0 + h, fill=color,
                                   outline='')
        # stats
        if d.kind == 'media':
            from .media import QUALITY_LABELS
            fourth = ('Quality', QUALITY_LABELS.get(d.quality, d.quality))
            fifth = ('Source', util.site_name(d.url))
        else:
            fourth = ('Connections', f'{d.active_connections} of {d.max_connections}' if d.status == DOWNLOADING
                      else str(d.max_connections))
            fifth = ('Resume', {True: 'Supported', False: 'Not supported'}.get(d.resumable, 'Unknown'))
        frac = d.progress
        done = util.fmt_size(d.downloaded) + (f' of {util.fmt_size(d.size)}' if d.size > 0 else '')
        if frac is not None and d.status != COMPLETED:
            done += f' ({frac * 100:.1f}%)'
        speed = util.fmt_speed(d.speed) if d.status == DOWNLOADING else ''
        eta = ''
        if d.status == DOWNLOADING and d.speed > 0 and d.size > 0:
            eta = util.fmt_eta(d.eta if d.eta is not None else (d.size - d.downloaded) / d.speed)
        stats = [('Downloaded', done, 1.7), ('Speed', speed or '—', 1), ('Time left', eta or '—', 1),
                 fourth + (1,), fifth + (1,), ('Saved to', d.folder, 1.8)]
        unit = (width - pad * 2) / sum(weight for _l, _v, weight in stats)
        x = pad
        for label, value, weight in stats:
            w = unit * weight
            c.create_text(x, S(102), text=label.upper(), font=t.f_small_bold, fill=p['muted'], anchor='w')
            c.create_text(x, S(124), text=self._fit(str(value), t.f_body, w - S(14)), font=t.f_body,
                          fill=p['text'], anchor='w')
            x += w

    def _update_toolbar(self):
        items = self.selection()
        self.btn_resume.set_enabled(any(d.status in (PAUSED, ERROR) for d in items))
        self.btn_pause.set_enabled(any(d.status in (DOWNLOADING, QUEUED) for d in items))
        self.btn_remove.set_enabled(bool(items))

    def _update_status(self):
        p = self.theme.p
        st = self.m.stats()
        if st['active']:
            text = f"↓ {util.fmt_speed(st['speed']) or '0 B/s'}  ·  {st['active']} downloading"
            if st['queued']:
                text += f", {st['queued']} queued"
        else:
            text = f"{st['queued']} queued" if st['queued'] else 'Idle'
        self.st_left.configure(text=text)
        limit = self.m.settings['speed_limit_kbps']
        self.st_limit.configure(text='Speed limit: ' + (util.fmt_speed(limit * 1024) if limit else 'off') + '  ▾',
                                fg=p['amber'] if limit else p['subtext'])
        if not self.server_ok:
            self.st_browser.configure(text=f"●  Browser link off (port {self.m.settings['port']} busy)",
                                      fg=p['red'])
        elif self.extension_connected():
            self.st_browser.configure(text='●  Browser connected', fg=p['green'])
        else:
            self.st_browser.configure(text='○  Connect browser', fg=p['accent'])

    def _update_tray_tip(self):
        if not self.tray:
            return
        st = self.m.stats()
        if st['active']:
            tip = f"{APP_NAME} — {st['active']} downloading · {util.fmt_speed(st['speed']) or '0 B/s'}"
        else:
            tip = f'{APP_NAME} — idle'
        self.tray.set_tooltip(tip)
