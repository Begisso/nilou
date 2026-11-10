"""Nilou's dialogs: add download, download video, grab page media, settings, browser setup."""
import io
import os
import threading
import tkinter as tk
import urllib.parse
from tkinter import filedialog, ttk

from . import grab, media, paths, util, winutil
from .engine import describe_error, open_url, probe
from .theme import CATEGORY_COLORS, IconButton


def run_bg(widget, fn, done, poll_ms=80):
    """Run fn() on a worker thread and call done(result, error) back on the Tk thread."""
    box = {}

    def work():
        try:
            box['result'] = fn()
        except Exception as e:  # noqa: BLE001
            box['error'] = e

    thread = threading.Thread(target=work, daemon=True)
    thread.start()

    def check():
        try:
            if not widget.winfo_exists():
                return
        except tk.TclError:
            return
        if thread.is_alive():
            widget.after(poll_ms, check)
        else:
            done(box.get('result'), box.get('error'))

    widget.after(poll_ms, check)


class Dialog(tk.Toplevel):
    def __init__(self, app, title, modal=False, resizable=False):
        super().__init__(app.root)
        self.app = app
        self.theme = app.theme
        self.p = p = app.theme.p
        self.S = S = app.theme.S
        self.modal = modal
        self.withdraw()
        self.title(title)
        self.configure(bg=p['bg'])
        self.resizable(resizable, resizable)
        if app.root.winfo_viewable():
            self.transient(app.root)
        self.footer = tk.Frame(self, bg=p['footer'])
        self.footer.pack(fill='x', side='bottom')
        self.footer_inner = tk.Frame(self.footer, bg=p['footer'])
        self.footer_inner.pack(fill='x', padx=S(22), pady=S(14))
        self.body = tk.Frame(self, bg=p['bg'])
        self.body.pack(fill='both', expand=True, padx=S(24), pady=(S(20), S(18)))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Escape>', lambda e: self.close())

    # helpers
    def caption(self, parent, text, bg=None):
        return tk.Label(parent, text=text, bg=bg or self.p['bg'], fg=self.p['subtext'], font=self.theme.f_small_bold,
                        anchor='w')

    def text(self, parent, text, bg=None, fg=None, font=None, wrap=0):
        return tk.Label(parent, text=text, bg=bg or self.p['bg'], fg=fg or self.p['text'],
                        font=font or self.theme.f_body, anchor='w', justify='left', wraplength=wrap)

    def heading(self, title, subtitle=None, icon=None):
        row = tk.Frame(self.body, bg=self.p['bg'])
        row.pack(fill='x')
        if icon:
            tk.Label(row, text=self.theme.glyph(icon), font=self.theme.f_title, bg=self.p['bg'],
                     fg=self.p['accent']).pack(side='left', padx=(0, self.S(10)))
        col = tk.Frame(row, bg=self.p['bg'])
        col.pack(side='left', fill='x', expand=True)
        tk.Label(col, text=title, font=self.theme.f_title, bg=self.p['bg'], fg=self.p['text'], anchor='w').pack(fill='x')
        if subtitle:
            tk.Label(col, text=subtitle, font=self.theme.f_small, bg=self.p['bg'], fg=self.p['subtext'],
                     anchor='w').pack(fill='x')
        return row

    def button(self, text, command, kind='secondary', side='right', icon=None):
        b = IconButton(self.footer_inner, self.theme, text, icon=icon, command=command, kind=kind,
                       bg=self.p['footer'])
        b.pack(side=side, padx=(self.S(8), 0) if side == 'right' else (0, self.S(8)))
        return b

    def folder_row(self, parent, var, row, bg=None):
        bg = bg or self.p['bg']
        self.caption(parent, 'Save to', bg).grid(row=row, column=0, columnspan=2, sticky='w')
        ttk.Entry(parent, textvariable=var).grid(row=row + 1, column=0, sticky='ew', pady=(self.S(4), 0))

        def browse():
            folder = filedialog.askdirectory(parent=self, initialdir=var.get() or self.app.m.default_folder(),
                                             title='Choose a folder')
            if folder:
                var.set(os.path.normpath(folder))

        IconButton(parent, self.theme, 'Browse…', kind='secondary', command=browse, bg=bg).grid(
            row=row + 1, column=1, sticky='e', padx=(self.S(8), 0), pady=(self.S(4), 0))

    def present(self, focus=None, size=None):
        self.update_idletasks()
        w, h = size if size else (self.winfo_reqwidth(), self.winfo_reqheight())
        root = self.app.root
        if root.winfo_viewable() and root.state() == 'normal':
            x = root.winfo_rootx() + (root.winfo_width() - w) // 2
            y = root.winfo_rooty() + max(0, (root.winfo_height() - h) // 3)
        else:
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 3
        self.geometry((f'{w}x{h}' if size else '') + f'+{max(0, x)}+{max(0, y)}')
        winutil.set_titlebar_theme(self, self.theme.dark)
        self.deiconify()
        self.lift()
        self.attributes('-topmost', True)
        self.after(400, lambda: self.winfo_exists() and self.attributes('-topmost', False))
        winutil.force_foreground(self)
        if focus is not None:
            focus.focus_force()
        if self.modal:
            self.grab_set()

    def close(self):
        if self.modal:
            try:
                self.grab_release()
            except tk.TclError:
                pass
        self.destroy()


class InfoStrip(tk.Frame):
    """A soft card with an icon, a message and an optional action button."""

    def __init__(self, dialog):
        p, S = dialog.p, dialog.S
        super().__init__(dialog.body, bg=p['surface'], highlightthickness=1, highlightbackground=p['border'])
        self.dialog = dialog
        self.icon = tk.Label(self, font=dialog.theme.f_icon, bg=p['surface'], fg=p['subtext'], width=2)
        self.icon.pack(side='left', padx=(S(12), S(4)), pady=S(10))
        self.label = tk.Label(self, bg=p['surface'], fg=p['subtext'], font=dialog.theme.f_body, anchor='w',
                              justify='left', wraplength=S(430))
        self.label.pack(side='left', fill='x', expand=True, pady=S(10))
        self.action = None

    def set(self, icon, message, tone='subtext', action=None):
        p = self.dialog.p
        color = p.get(tone, p['subtext'])
        self.icon.configure(text=self.dialog.theme.glyph(icon) if icon else '', fg=color)
        self.label.configure(text=message, fg=p['text'] if tone == 'subtext' else color)
        if self.action is not None:
            self.action.destroy()
            self.action = None
        if action:
            text, command = action
            self.action = IconButton(self, self.dialog.theme, text, kind='secondary', command=command,
                                     bg=p['surface'])
            self.action.pack(side='right', padx=self.dialog.S(10))


# --------------------------------------------------------------------------------------------
class AddDialog(Dialog):
    def __init__(self, app, url='', filename='', headers=None, from_browser=False, size=-1):
        super().__init__(app, 'Nilou — New download')
        S, p = self.S, self.p
        self.headers = dict(headers or {})
        self.info = None
        self._token = 0
        self._after = None
        self._setting_name = False
        self.name_edited = bool(filename)
        self.hint_size = size
        self.heading('Download from your browser' if from_browser else 'New download',
                     'Fast, resumable, multi-connection', icon='download')

        form = tk.Frame(self.body, bg=p['bg'])
        form.pack(fill='x', pady=(S(16), 0))
        form.columnconfigure(0, weight=1)
        self.caption(form, 'Address').grid(row=0, column=0, columnspan=2, sticky='w')
        self.url_var = tk.StringVar(value=url)
        self.url_entry = ttk.Entry(form, textvariable=self.url_var, width=72)
        self.url_entry.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(S(4), S(12)))
        self.caption(form, 'File name').grid(row=2, column=0, columnspan=2, sticky='w')
        self.name_var = tk.StringVar(value=filename)
        self.name_entry = ttk.Entry(form, textvariable=self.name_var)
        self.name_entry.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(S(4), S(12)))
        self.folder_var = tk.StringVar(value=app.m.default_folder())
        self.folder_row(form, self.folder_var, 4)

        self.strip = InfoStrip(self)
        self.strip.pack(fill='x', pady=(S(16), 0))
        self.strip.set('link', 'Paste a link to a file.')

        self.button('Cancel', self.close)
        self.button('Download later', lambda: self.ok(False))
        self.btn_ok = self.button('Download', lambda: self.ok(True), kind='primary')

        self.url_var.trace_add('write', lambda *a: self._schedule())
        self.name_var.trace_add('write', self._name_changed)
        self.bind('<Return>', lambda e: self.ok(True))
        if url:
            self._schedule(10)
        self.present(focus=None if url else self.url_entry)

    def _name_changed(self, *_a):
        if not self._setting_name:
            self.name_edited = True

    def _set_name(self, name):
        self._setting_name = True
        self.name_var.set(name)
        self._setting_name = False

    def _schedule(self, delay=450):
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(delay, self._check)

    def _check(self):
        self._after = None
        self._token += 1
        token = self._token
        self.info = None
        urls = util.extract_urls(self.url_var.get())
        self.name_entry.state(['!disabled'])
        if not urls:
            self.strip.set('link', 'Paste a link that starts with http:// or https://')
            return
        if len(urls) > 1:
            self.name_entry.state(['disabled'])
            self.strip.set('all', f'{len(urls)} links found — each file keeps its own name.')
            return
        url = urls[0]
        if util.is_media_site(url):
            self.strip.set('video', f'This is a {util.site_name(url)} link. Download the video itself?', 'violet',
                           action=('Download video', lambda: self._to_media(url)))
            return
        self.strip.set('refresh', 'Checking the link…')

        def done(info, err):
            if token != self._token:
                if info:
                    info.close()
                return
            if err is not None:
                self.strip.set('error', f'Could not check the link ({describe_error(err)}). '
                                        'You can still try to download it.', 'amber')
                return
            info.close()
            self.info = info
            if not self.name_edited:
                self._set_name(info.filename)
            if info.content_type in ('text/html', 'application/xhtml+xml'):
                self.strip.set('globe', 'This link opens a web page, not a file.', 'amber',
                               action=('Grab media from page', lambda: self._to_grab(url)))
                return
            size = util.fmt_size(info.size) if info.size > 0 else 'Unknown size'
            how = 'resumable, multi-connection' if info.resumable else 'single connection, no resume'
            exists = os.path.exists(os.path.join(self.folder_var.get(), self.name_var.get().strip() or info.filename))
            extra = '\nA file with this name already exists — the new one gets a number.' if exists else ''
            self.strip.set('check', f'{size} · {how}{extra}', 'green')

        run_bg(self, lambda: probe(url, self.headers, timeout=15), done)

    def _to_media(self, url):
        self.close()
        self.app.open_media(url, headers=self.headers)

    def _to_grab(self, url):
        self.close()
        self.app.open_grab(url=url, headers=self.headers)

    def ok(self, start):
        urls = util.extract_urls(self.url_var.get())
        if not urls:
            self.strip.set('error', 'Enter a link that starts with http:// or https://', 'red')
            return
        folder = self.folder_var.get().strip() or self.app.m.default_folder()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            self.strip.set('error', f'Cannot use this folder: {e.strerror}', 'red')
            return
        if len(urls) == 1:
            url = urls[0]
            if util.is_media_site(url):
                self._to_media(url)
                return
            name = self.name_var.get().strip() or None
            size = self.info.size if self.info and self.info.url == url else self.hint_size
            self.app.m.add(url, filename=name, folder=folder, headers=self.headers, start=start, size=size)
        else:
            for url in urls:
                self.app.m.add(url, folder=folder, headers=self.headers, start=start)
        self.app.after_add()
        self.close()


# --------------------------------------------------------------------------------------------
class MediaDialog(Dialog):
    def __init__(self, app, url='', cookies=None, headers=None):
        super().__init__(app, 'Nilou — Download video')
        S, p = self.S, self.p
        self.cookies = cookies or []
        self.headers = dict(headers or {})
        self.info = None
        self.installer = None
        self._token = 0
        self._after = None
        self._thumb = None
        self.heading('Download video or audio', 'YouTube, X (Twitter), Vimeo, TikTok, Instagram, Reddit and more',
                     icon='video')

        form = tk.Frame(self.body, bg=p['bg'])
        form.pack(fill='x', pady=(S(16), 0))
        form.columnconfigure(0, weight=1)
        self.caption(form, 'Video or page address').grid(row=0, column=0, columnspan=2, sticky='w')
        self.url_var = tk.StringVar(value=url)
        self.url_entry = ttk.Entry(form, textvariable=self.url_var, width=72)
        self.url_entry.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(S(4), S(12)))

        # one-time setup card
        self.setup = tk.Frame(self.body, bg=p['accent_soft'])
        inner = tk.Frame(self.setup, bg=p['accent_soft'])
        inner.pack(fill='x', padx=S(14), pady=S(12))
        inner.columnconfigure(0, weight=1)
        self.text(inner, 'One-time setup', bg=p['accent_soft'], font=self.theme.f_bold).grid(row=0, column=0,
                                                                                             sticky='w')
        self.setup_lbl = self.text(inner, 'Video downloads use yt-dlp, Deno and FFmpeg (about 200 MB). Nilou '
                                          'fetches them once into its own folder.', bg=p['accent_soft'],
                                   fg=p['subtext'], wrap=S(420))
        self.setup_lbl.grid(row=1, column=0, sticky='w', pady=(S(2), S(8)))
        self.setup_bar = ttk.Progressbar(inner, style='Nilou.Horizontal.TProgressbar', maximum=1000)
        self.setup_bar.grid(row=2, column=0, sticky='ew')
        self.setup_btn = IconButton(inner, self.theme, 'Install', icon='download', kind='primary',
                                    command=self._install, bg=p['accent_soft'])
        self.setup_btn.grid(row=0, column=1, rowspan=3, sticky='e', padx=(S(14), 0))

        # info card
        self.card = tk.Frame(self.body, bg=p['surface'], highlightthickness=1, highlightbackground=p['border'])
        self.card_text = tk.Frame(self.card, bg=p['surface'])
        self.title_lbl = tk.Label(self.card_text, bg=p['surface'], fg=p['text'], font=self.theme.f_bold, anchor='w',
                                  justify='left', wraplength=S(330))
        self.meta_lbl = tk.Label(self.card_text, bg=p['surface'], fg=p['subtext'], font=self.theme.f_small,
                                 anchor='w', justify='left', wraplength=S(330))
        self.title_lbl.pack(fill='x')
        self.meta_lbl.pack(fill='x', pady=(S(4), 0))
        self.thumb_box = tk.Frame(self.card, bg=p['surface2'], width=S(160), height=S(90))
        self.thumb_box.pack_propagate(False)
        self.thumb_box.pack(side='left', padx=S(10), pady=S(10))
        self.thumb_lbl = tk.Label(self.thumb_box, bg=p['surface2'], bd=0, text=self.theme.glyph('video'),
                                  font=self.theme.f_icon_big, fg=p['muted'])
        self.thumb_lbl.pack(fill='both', expand=True)
        self.card_text.pack(side='left', fill='both', expand=True, padx=(0, S(12)), pady=S(10))

        opts = tk.Frame(self.body, bg=p['bg'])
        self.opts = opts
        opts.columnconfigure(0, weight=1)
        self.caption(opts, 'Quality').grid(row=0, column=0, columnspan=2, sticky='w')
        self.quality_var = tk.StringVar()
        self.quality_box = ttk.Combobox(opts, textvariable=self.quality_var, state='readonly', width=30)
        self.quality_box.grid(row=1, column=0, columnspan=2, sticky='w', pady=(S(4), S(12)))
        self.folder_var = tk.StringVar(value=app.m.default_folder())
        self.folder_row(opts, self.folder_var, 2)
        self._set_qualities([])

        self.button('Cancel', self.close)
        self.btn_ok = self.button('Download', self.ok, kind='primary')
        self.url_var.trace_add('write', lambda *a: self._schedule())
        self.bind('<Return>', lambda e: self.ok())
        self._layout()
        if url and media.tools_ready():
            self._schedule(10)
        self.present(focus=None if url else self.url_entry)

    def _layout(self):
        S = self.S
        for w in (self.setup, self.card, self.opts):
            w.pack_forget()
        if not media.tools_ready():
            self.setup.pack(fill='x', pady=(S(4), 0))
        self.card.pack(fill='x', pady=(S(12), 0))
        self.opts.pack(fill='x', pady=(S(14), 0))
        self.btn_ok.set_enabled(media.tools_ready() or self.installer is not None)
        if not self.info:
            self.title_lbl.configure(text='Paste a video link above' if not self.url_var.get().strip() else
                                     ('Install the media tools to continue' if not media.tools_ready() else
                                      'Loading video details…'))
            self.meta_lbl.configure(text='')

    def _set_qualities(self, heights):
        options = [('best', 'Best available' + (f' ({heights[0]}p)' if heights else ''))]
        for key, label in media.QUALITIES[1:]:
            if key.isdigit() and heights and int(key) not in heights:
                continue
            options.append((key, label))
        self.quality_keys = [k for k, _ in options]
        self.quality_box.configure(values=[label for _, label in options])
        wanted = self.app.m.settings.get('video_quality', '1080')
        index = self.quality_keys.index(wanted) if wanted in self.quality_keys else 0
        self.quality_box.current(index)

    def _install(self):
        if self.installer is not None:
            return
        self.setup_btn.set_enabled(False)
        self.installer = media.ToolInstaller().start()
        self._poll_install()

    def _poll_install(self):
        if not self.winfo_exists():
            return
        inst = self.installer
        done, total = inst.progress()
        if total:
            self.setup_bar['value'] = int(1000 * done / total)
        self.setup_lbl.configure(text=f'Downloading {util.fmt_size(done)} of {util.fmt_size(total) if total else "…"}'
                                      f'\n{inst.status_text()}')
        if not inst.done:
            self.after(250, self._poll_install)
            return
        if inst.error:
            self.setup_lbl.configure(text=inst.error, fg=self.p['red'])
            self.installer = None
            self.setup_btn.set_enabled(True)
            self.setup_btn.set_text('Try again')
            return
        self.installer = None
        self._layout()
        self._schedule(10)

    def _schedule(self, delay=600):
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(delay, self._fetch)

    def _fetch(self):
        self._after = None
        self._token += 1
        token = self._token
        self.info = None
        urls = util.extract_urls(self.url_var.get())
        if not urls or not media.tools_ready():
            self._layout()
            return
        url = urls[0]
        self.title_lbl.configure(text='Loading video details…')
        self.meta_lbl.configure(text=util.site_name(url))
        cookies = self.cookies if util.site_name(url) != 'YouTube' else None

        def done(info, err):
            if token != self._token:
                return
            if err is not None:
                self.title_lbl.configure(text='Could not read this video')
                self.meta_lbl.configure(text=str(err)[:300], fg=self.p['red'])
                return
            self.info = info
            self.meta_lbl.configure(fg=self.p['subtext'])
            self.title_lbl.configure(text=info['title'])
            bits = [b for b in (info['uploader'], util.fmt_duration(info['duration']), info['extractor']) if b]
            if info['playlist']:
                bits.insert(0, f'Playlist · {len(info["entries"])} videos')
            self.meta_lbl.configure(text=' · '.join(bits))
            self._set_qualities(info['heights'])
            if info['thumbnail']:
                self._load_thumb(info['thumbnail'], token)

        run_bg(self, lambda: media.fetch_info(url, cookies), done)

    def _load_thumb(self, url, token):
        import importlib.util
        if importlib.util.find_spec('PIL') is None:
            return

        def fetch():
            from PIL import Image
            with open_url(url, timeout=15) as r:
                data = r.read(4 * 1024 * 1024)
            im = Image.open(io.BytesIO(data)).convert('RGB')
            w, h = self.S(160), self.S(90)
            scale = max(w / im.width, h / im.height)
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
            left, top = (im.width - w) // 2, (im.height - h) // 2
            return im.crop((left, top, left + w, top + h))

        def done(im, err):
            if err is not None or im is None or token != self._token:
                return
            from PIL import ImageTk
            self._thumb = ImageTk.PhotoImage(im)
            self.thumb_lbl.configure(image=self._thumb, text='')

        run_bg(self, fetch, done)

    def ok(self):
        if not media.tools_ready():
            self._install()
            return
        urls = util.extract_urls(self.url_var.get())
        if not urls:
            self.url_entry.focus_set()
            return
        folder = self.folder_var.get().strip() or self.app.m.default_folder()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            return
        quality = self.quality_keys[max(0, self.quality_box.current())]
        self.app.m.settings['video_quality'] = quality
        cookies = self.cookies if util.site_name(urls[0]) != 'YouTube' else None
        info = self.info
        if info and info['playlist'] and info['entries']:
            for e in info['entries']:
                self.app.m.add_media(e['url'], quality, folder, e['title'], e['id'], cookies, self.headers)
        else:
            for url in urls:
                title = info['title'] if info and len(urls) == 1 else ''
                vid = info['id'] if info and len(urls) == 1 else ''
                self.app.m.add_media(url, quality, folder, title, vid, cookies, self.headers)
        self.app.m.save_settings()
        self.app.after_add()
        self.close()


# --------------------------------------------------------------------------------------------
TYPE_LABELS = {'image': 'Images', 'video': 'Videos', 'audio': 'Audio', 'file': 'Files'}


class GrabDialog(Dialog):
    def __init__(self, app, url='', title='', items=None, cookies=None, headers=None):
        super().__init__(app, 'Nilou — Grab media from page', resizable=True)
        S, p = self.S, self.p
        self.cookies = cookies or {}          # host -> Cookie header
        self.headers = dict(headers or {})
        self.page = url
        self.items = []
        self._token = 0
        self.heading('Grab media from a page', 'Pick the images, videos, audio and files you want', icon='grab')

        top = tk.Frame(self.body, bg=p['bg'])
        top.pack(fill='x', pady=(S(14), 0))
        top.columnconfigure(0, weight=1)
        self.url_var = tk.StringVar(value=url)
        self.url_entry = ttk.Entry(top, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=0, sticky='ew')
        IconButton(top, self.theme, 'Scan page', icon='search', kind='secondary', command=self.scan).grid(
            row=0, column=1, padx=(S(8), 0))
        self.url_entry.bind('<Return>', lambda e: self.scan())

        filt = tk.Frame(self.body, bg=p['bg'])
        filt.pack(fill='x', pady=(S(12), S(6)))
        self.type_vars = {}
        self.type_checks = {}
        for key in ('image', 'video', 'audio', 'file'):
            var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(filt, text=TYPE_LABELS[key], variable=var, command=self.refresh)
            cb.pack(side='left', padx=(0, S(16)))
            self.type_vars[key] = var
            self.type_checks[key] = cb
        self.small_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(filt, text='Hide small images', variable=self.small_var, command=self.refresh).pack(
            side='left')
        self.count_lbl = tk.Label(filt, bg=p['bg'], fg=p['subtext'], font=self.theme.f_small)
        self.count_lbl.pack(side='right')

        bottom = tk.Frame(self.body, bg=p['bg'])
        bottom.pack(fill='x', side='bottom', pady=(S(12), 0))
        bottom.columnconfigure(0, weight=1)
        self.folder_var = tk.StringVar(value=app.m.default_folder())
        self.folder_row(bottom, self.folder_var, 0)
        self.sub_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bottom, text='Put them in a new folder named after the page', variable=self.sub_var).grid(
            row=2, column=0, columnspan=2, sticky='w', pady=(S(8), 0))

        wrap = tk.Frame(self.body, bg=p['border'], padx=1, pady=1)
        wrap.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(wrap, columns=('type', 'name', 'info', 'host'), show='headings',
                                 selectmode='extended', height=8)
        for col, label, width, stretch in (('type', 'Type', 70, False), ('name', 'Name', 300, True),
                                           ('info', 'Details', 110, False), ('host', 'From', 160, False)):
            self.tree.heading(col, text=label, anchor='w')
            self.tree.column(col, width=S(width), stretch=stretch, anchor='w')
        sb = ttk.Scrollbar(wrap, orient='vertical', command=self.tree.yview, style='Slim.Vertical.TScrollbar')
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self._update_button())

        self.button('Cancel', self.close)
        self.button('Select all', self.select_all, side='left')
        self.btn_ok = self.button('Download', self.ok, kind='primary')
        self.title_text = title
        if items:
            self.set_items(url, title, items)
        elif url:
            self.after(10, self.scan)
        self.present(focus=self.url_entry if not url else None, size=(S(860), S(640)))
        self.minsize(S(640), S(460))

    def scan(self):
        urls = util.extract_urls(self.url_var.get())
        if not urls:
            self.count_lbl.configure(text='Enter a page address', fg=self.p['red'])
            return
        self._token += 1
        token = self._token
        self.count_lbl.configure(text='Scanning page…', fg=self.p['subtext'])
        self.tree.delete(*self.tree.get_children())

        def done(result, err):
            if token != self._token:
                return
            if err is not None:
                self.count_lbl.configure(text=f'Could not read the page: {describe_error(err)}', fg=self.p['red'])
                return
            self.set_items(result['page'], result['title'], result['items'])

        run_bg(self, lambda: grab.grab_page(urls[0], self.headers), done)

    def set_items(self, page, title, items):
        self.page = page
        self.title_text = title or ''
        seen = set()
        self.items = []
        for it in items:
            url = it.get('url')
            if not url or url in seen:
                continue
            seen.add(url)
            kind = it.get('type') if it.get('type') in TYPE_LABELS else (grab.kind_of(url) or 'file')
            self.items.append(dict(it, type=kind))
        for key, cb in self.type_checks.items():
            n = sum(1 for it in self.items if it['type'] == key)
            cb.configure(text=f'{TYPE_LABELS[key]} ({n})')
        self.refresh()
        self.select_all()

    def _visible(self, it):
        if not self.type_vars[it['type']].get():
            return False
        if it['type'] == 'image' and self.small_var.get():
            w, h = it.get('w') or 0, it.get('h') or 0
            if w and h and (w < 100 or h < 100):
                return False
        return True

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for i, it in enumerate(self.items):
            if not self._visible(it):
                continue
            name = it.get('name') or util.filename_from_url(it['url']) or it['url']
            info = f"{it['w']}×{it['h']}" if it.get('w') and it.get('h') else util.extension(name).upper()
            host = urllib.parse.urlsplit(it['url']).hostname or ''
            self.tree.insert('', 'end', iid=str(i), values=(TYPE_LABELS[it['type']].rstrip('s'), name, info, host))
            shown += 1
        self.count_lbl.configure(text=f'{shown} of {len(self.items)} shown', fg=self.p['subtext'])
        self._update_button()

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())
        self._update_button()

    def _update_button(self):
        n = len(self.tree.selection())
        self.btn_ok.set_text(f'Download {n}' if n else 'Download')
        self.btn_ok.set_enabled(n > 0)

    def ok(self):
        picked = [self.items[int(i)] for i in self.tree.selection()]
        if not picked:
            return
        folder = self.folder_var.get().strip() or self.app.m.default_folder()
        if self.sub_var.get():
            name = util.sanitize_filename(self.title_text or urllib.parse.urlsplit(self.page).hostname or 'page')
            folder = os.path.join(folder, name[:80])
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            return
        for it in picked:
            url = it['url']
            headers = {'Referer': self.page} if self.page else {}
            cookie = self.cookies.get(urllib.parse.urlsplit(url).hostname or '')
            if cookie:
                headers['Cookie'] = cookie
            if util.extension(util.filename_from_url(url)) == 'm3u8' and media.tools_ready():
                self.app.m.add_media(url, 'best', folder, headers=headers)
            else:
                self.app.m.add(url, folder=folder, headers=headers)
        self.app.after_add()
        self.close()


# --------------------------------------------------------------------------------------------
class ConfirmDialog(Dialog):
    def __init__(self, app, title, message, confirm_text, on_confirm, checkbox=None, danger=True):
        super().__init__(app, 'Nilou', modal=True)
        S, p = self.S, self.p
        self.on_confirm = on_confirm
        tk.Label(self.body, text=title, font=self.theme.f_subtitle, bg=p['bg'], fg=p['text'], anchor='w').pack(
            fill='x')
        self.text(self.body, message, fg=p['subtext'], wrap=S(380)).pack(fill='x', pady=(S(6), 0))
        self.check_var = tk.BooleanVar(value=False)
        if checkbox:
            ttk.Checkbutton(self.body, text=checkbox, variable=self.check_var).pack(fill='x', pady=(S(12), 0))
        self.button('Cancel', self.close)
        self.button(confirm_text, self._ok, kind='danger' if danger else 'primary')
        self.bind('<Return>', lambda e: self._ok())
        self.present()

    def _ok(self):
        checked = self.check_var.get()
        self.close()
        self.on_confirm(checked)


# --------------------------------------------------------------------------------------------
class SettingsDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, 'Nilou — Settings', modal=True)
        S, p = self.S, self.p
        s = app.m.settings
        self.heading('Settings', icon='settings')
        cols = tk.Frame(self.body, bg=p['bg'])
        cols.pack(fill='both', expand=True, pady=(S(10), 0))
        left = tk.Frame(cols, bg=p['bg'])
        right = tk.Frame(cols, bg=p['bg'])
        left.pack(side='left', fill='both', expand=True, padx=(0, S(16)))
        right.pack(side='left', fill='both', expand=True, padx=(S(16), 0))
        left.columnconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        def section(parent, row, title):
            tk.Label(parent, text=title, font=self.theme.f_subtitle, bg=p['bg'], fg=p['text'], anchor='w').grid(
                row=row, column=0, columnspan=2, sticky='w', pady=(S(12), S(6)))

        def check(parent, row, text, key):
            var = tk.BooleanVar(value=bool(s[key]))
            ttk.Checkbutton(parent, text=text, variable=var).grid(row=row, column=0, columnspan=2, sticky='w')
            self.vars[key] = var

        def number(parent, row, text, key, lo, hi, width=6):
            frame = tk.Frame(parent, bg=p['bg'])
            frame.grid(row=row, column=0, columnspan=2, sticky='w', pady=S(3))
            var = tk.StringVar(value=str(s[key]))
            ttk.Spinbox(frame, from_=lo, to=hi, textvariable=var, width=width).pack(side='left')
            tk.Label(frame, text=text, bg=p['bg'], fg=p['text'], font=self.theme.f_body).pack(side='left',
                                                                                                padx=(S(10), 0))
            self.vars[key] = var

        self.vars = {}
        section(left, 0, 'Downloads')
        self.folder_var = tk.StringVar(value=s['download_dir'])
        self.folder_row(left, self.folder_var, 1)
        check(left, 3, 'Sort into folders by type (Video, Music, …)', 'category_subfolders')
        number(left, 4, 'downloads at the same time', 'max_active', 1, 10)
        number(left, 5, 'connections per file', 'connections', 1, 32)
        number(left, 6, 'KB/s speed limit (0 = unlimited)', 'speed_limit_kbps', 0, 1000000, width=8)
        check(left, 7, 'Save WebP images as PNG', 'webp_to_png')
        section(left, 8, 'Browser & clipboard')
        check(left, 9, 'Ask before starting downloads from the browser', 'browser_show_dialog')
        check(left, 10, 'Watch the clipboard for download links', 'clipboard_monitor')
        number(left, 11, 'local port for the extension (restart Nilou)', 'port', 1024, 65535, width=7)

        section(right, 0, 'Window')
        frame = tk.Frame(right, bg=p['bg'])
        frame.grid(row=1, column=0, sticky='w', pady=S(3))
        tk.Label(frame, text='Theme', bg=p['bg'], fg=p['text'], font=self.theme.f_body).pack(side='left')
        self.theme_box = ttk.Combobox(frame, state='readonly', values=['System', 'Light', 'Dark'], width=10)
        self.theme_box.current(['system', 'light', 'dark'].index(s['theme']) if s['theme'] in (
            'system', 'light', 'dark') else 0)
        self.theme_box.pack(side='left', padx=(S(10), 0))
        check(right, 2, 'Closing the window keeps Nilou in the tray', 'close_to_tray')
        check(right, 3, 'Minimizing hides Nilou to the tray', 'minimize_to_tray')
        check(right, 4, 'Notify me when downloads finish', 'notify_complete')
        check(right, 5, 'Start Nilou when I sign in (in the tray)', 'start_with_windows')
        section(right, 6, 'Video tools')
        ready = media.tools_ready()
        self.tools_lbl = self.text(right, 'Checking…' if ready else
                                   'Not installed yet — Nilou sets them up the first time you download a video.',
                                   fg=p['subtext'], wrap=S(300))
        self.tools_lbl.grid(row=7, column=0, columnspan=2, sticky='w')
        if ready:
            IconButton(right, self.theme, 'Update yt-dlp', icon='refresh', kind='secondary',
                       command=self._update_tools).grid(row=8, column=0, sticky='w', pady=(S(8), 0))
            run_bg(self, media.ytdlp_version,
                   lambda v, e: self.tools_lbl.configure(text=f'yt-dlp {v or "?"} · Deno · FFmpeg installed in\n'
                                                              f'{paths.tools_dir()}'))
        section(right, 9, 'About')
        self.text(right, f'Nilou {app.version} · portable\nData folder: {paths.data_dir()}', fg=p['subtext'],
                  wrap=S(300)).grid(row=10, column=0, sticky='w')

        self.button('Cancel', self.close)
        self.button('Save', self.save, kind='primary')
        self.present()

    def _update_tools(self):
        self.tools_lbl.configure(text='Updating yt-dlp…')
        run_bg(self, media.update_ytdlp,
               lambda out, err: self.tools_lbl.configure(text=(str(err) if err else out.splitlines()[-1] if out
                                                               else 'Done')[:200]))

    def save(self):
        s = self.app.m.settings
        old_theme, old_port = s['theme'], s['port']
        folder = self.folder_var.get().strip()
        if folder:
            s['download_dir'] = os.path.normpath(folder)
        for key, var in self.vars.items():
            if isinstance(var, tk.BooleanVar):
                s[key] = bool(var.get())
            else:
                try:
                    s[key] = int(float(var.get()))
                except ValueError:
                    pass
        s['max_active'] = min(10, max(1, s['max_active']))
        s['connections'] = min(32, max(1, s['connections']))
        s['port'] = min(65535, max(1024, s['port']))
        s['theme'] = ['system', 'light', 'dark'][max(0, self.theme_box.current())]
        self.app.m.set_speed_limit(s['speed_limit_kbps'])
        self.app.apply_startup(s['start_with_windows'])
        self.app.m.save_settings()
        self.close()
        if s['theme'] != old_theme:
            self.app.rebuild()
        if s['port'] != old_port:
            self.app.notify('Restart Nilou', 'The new extension port is used after Nilou restarts.')


# --------------------------------------------------------------------------------------------
class BrowserSetupDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, 'Nilou — Connect your browser')
        S, p = self.S, self.p
        self.folder = app.extension_dir()
        self.heading('Connect your browser', 'Chrome, Edge, Brave, Opera and other Chromium browsers', icon='browser')
        self.text(self.body, 'The Nilou extension sends your browser downloads to Nilou, adds “Download with Nilou” '
                             'and “Grab media” to the right-click menu, and a video button for YouTube and X.',
                  fg=p['subtext'], wrap=S(520)).pack(fill='x', pady=(S(12), S(6)))

        def step(number, title, body=None):
            row = tk.Frame(self.body, bg=p['bg'])
            row.pack(fill='x', pady=(S(10), 0))
            tk.Label(row, text=str(number), bg=p['accent'], fg=p['accent_text'], font=self.theme.f_bold,
                     width=2).pack(side='left', anchor='n')
            col = tk.Frame(row, bg=p['bg'])
            col.pack(side='left', fill='x', expand=True, padx=(S(12), 0))
            self.text(col, title, font=self.theme.f_bold).pack(fill='x')
            if body:
                self.text(col, body, fg=p['subtext'], wrap=S(480)).pack(fill='x')
            return col

        col = step(1, 'Open the extensions page and switch on “Developer mode”',
                   'Or type edge://extensions or chrome://extensions in the address bar.')
        buttons = tk.Frame(col, bg=p['bg'])
        buttons.pack(fill='x', pady=(S(6), 0))
        found = False
        for exe, label, url in (('msedge.exe', 'Open Edge', 'edge://extensions/'),
                                ('chrome.exe', 'Open Chrome', 'chrome://extensions/'),
                                ('brave.exe', 'Open Brave', 'brave://extensions/')):
            path = winutil.find_browser(exe)
            if path:
                found = True
                IconButton(buttons, self.theme, label, icon='globe', kind='secondary',
                           command=lambda pth=path, u=url: self._launch(pth, u)).pack(side='left', padx=(0, S(8)))
        if not found:
            self.text(buttons, 'No Chromium browser found automatically.', fg=p['muted']).pack(side='left')

        col = step(2, 'Click “Load unpacked” and pick this folder:')
        row = tk.Frame(col, bg=p['bg'])
        row.pack(fill='x', pady=(S(6), 0))
        var = tk.StringVar(value=self.folder)
        entry = ttk.Entry(row, textvariable=var, state='readonly', width=46)
        entry.pack(side='left', fill='x', expand=True)
        IconButton(row, self.theme, 'Copy', icon='copy', kind='secondary', command=self._copy).pack(
            side='left', padx=(S(8), 0))
        IconButton(row, self.theme, 'Open', icon='folder', kind='secondary',
                   command=lambda: winutil.open_file(self.folder)).pack(side='left', padx=(S(8), 0))

        step(3, 'Pin Nilou in the toolbar (puzzle-piece menu)',
             'Firefox is not supported yet — it only allows signed extensions.')
        self.status = tk.Label(self.body, bg=p['bg'], font=self.theme.f_bold, anchor='w')
        self.status.pack(fill='x', pady=(S(18), 0))
        self.button('Done', self.close, kind='primary')
        self._tick()
        self.present()

    def _launch(self, path, url):
        import subprocess
        try:
            subprocess.Popen([path, url])
        except OSError:
            pass
        self.clipboard_clear()
        self.clipboard_append(url)

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.folder)

    def _tick(self):
        if not self.winfo_exists():
            return
        if self.app.extension_connected():
            self.status.configure(text='●  Connected — Nilou is catching your browser downloads.',
                                  fg=self.p['green'])
        else:
            self.status.configure(text='○  Waiting for the extension…', fg=self.p['muted'])
        self.after(1000, self._tick)


__all__ = ['AddDialog', 'MediaDialog', 'GrabDialog', 'ConfirmDialog', 'SettingsDialog', 'BrowserSetupDialog',
           'run_bg', 'CATEGORY_COLORS']
