"""Colors, fonts, icon glyphs and a few themed widgets for the Tk UI."""
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from . import winutil

LIGHT = {
    'bg': '#f4f5fb', 'surface': '#ffffff', 'surface2': '#f7f8fd', 'footer': '#eceef7',
    'text': '#1b1d2a', 'subtext': '#5d6175', 'muted': '#8d91a5', 'border': '#e2e4ef', 'divider': '#eef0f6',
    'accent': '#3563e9', 'accent_hover': '#4a74f0', 'accent_text': '#ffffff', 'accent_soft': '#e6ecfd',
    'hover': '#eef0f8', 'select': '#e3e9fc', 'track': '#e3e6f0',
    'button': '#ffffff', 'button_hover': '#f1f3fa', 'input': '#ffffff', 'input_border': '#cfd3e2',
    'green': '#1a7f37', 'amber': '#b36b00', 'red': '#c42b1c', 'danger': '#c42b1c', 'violet': '#6d4fd8', 'scroll': '#c9cddc',
}
DARK = {
    'bg': '#16171f', 'surface': '#1e2029', 'surface2': '#23252f', 'footer': '#1a1b23',
    'text': '#eceef6', 'subtext': '#a9adbf', 'muted': '#767a8e', 'border': '#2e3140', 'divider': '#262935',
    'accent': '#6e95ff', 'accent_hover': '#86a7ff', 'accent_text': '#0d1020', 'accent_soft': '#25305a',
    'hover': '#262935', 'select': '#283463', 'track': '#323647',
    'button': '#262935', 'button_hover': '#2e3241', 'input': '#23252f', 'input_border': '#3a3e50',
    'green': '#5fd47a', 'amber': '#ffbe4d', 'red': '#ff8a80', 'danger': '#d23f35', 'violet': '#a48bff', 'scroll': '#3d4152',
}

CATEGORY_COLORS = {
    'Video': '#8b5cf6', 'Music': '#ec4899', 'Images': '#f59e0b', 'Documents': '#3b82f6',
    'Archives': '#ea580c', 'Programs': '#10b981', 'Other': '#8d91a5',
}

# Segoe Fluent Icons / Segoe MDL2 Assets code points, with plain-text fallbacks.
ICONS = {
    'add': ('', '+'), 'play': ('', '▶'), 'pause': ('', '❚❚'), 'delete': ('', '✕'),
    'settings': ('', '⚙'), 'folder': ('', '▭'), 'download': ('', '↓'), 'more': ('', '⋯'),
    'search': ('', '⌕'), 'check': ('', '✓'), 'error': ('', '!'), 'link': ('', '∞'),
    'video': ('', '▶'), 'music': ('', '♪'), 'document': ('', '▤'), 'archive': ('', '▣'),
    'program': ('', '◆'), 'image': ('', '◩'), 'other': ('', '▢'), 'all': ('', '≡'),
    'completed': ('', '✓'), 'unfinished': ('', '❚❚'), 'active': ('', '↓'),
    'globe': ('', '◎'), 'grab': ('', '⊞'), 'speed': ('', '»'), 'refresh': ('', '↻'),
    'up': ('', '▴'), 'down': ('', '▾'), 'copy': ('', '⧉'), 'cancel': ('', '✕'),
    'info': ('', 'i'), 'browser': ('', '◎'),
}
CATEGORY_ICONS = {'Video': 'video', 'Music': 'music', 'Images': 'image', 'Documents': 'document',
                  'Archives': 'archive', 'Programs': 'program', 'Other': 'other'}


class Theme:
    def __init__(self, root, mode='system'):
        self.root = root
        self.dark = winutil.system_dark_mode() if mode == 'system' else mode == 'dark'
        self.p = dict(DARK if self.dark else LIGHT)
        self.scale = root.winfo_fpixels('1i') / 96.0
        families = set(tkfont.families(root))
        base = 'Segoe UI' if 'Segoe UI' in families else 'TkDefaultFont'
        semibold = 'Segoe UI Semibold' if 'Segoe UI Semibold' in families else base
        icon_family = next((f for f in ('Segoe Fluent Icons', 'Segoe MDL2 Assets') if f in families), None)
        self.has_icons = icon_family is not None
        self.f_body = tkfont.Font(root, family=base, size=10)
        self.f_bold = tkfont.Font(root, family=semibold, size=10)
        self.f_small = tkfont.Font(root, family=base, size=9)
        self.f_small_bold = tkfont.Font(root, family=semibold, size=9)
        self.f_title = tkfont.Font(root, family=semibold, size=14)
        self.f_subtitle = tkfont.Font(root, family=semibold, size=11)
        self.f_hero = tkfont.Font(root, family=semibold, size=18)
        self.f_icon = tkfont.Font(root, family=icon_family or base, size=11)
        self.f_icon_small = tkfont.Font(root, family=icon_family or base, size=9)
        self.f_icon_big = tkfont.Font(root, family=icon_family or base, size=28)
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
            try:
                tkfont.nametofont(name).configure(family=base, size=10)
            except tk.TclError:
                pass
        self.apply_ttk()

    def S(self, value):
        return int(round(value * self.scale))

    def glyph(self, name):
        code, fallback = ICONS.get(name, ('', '?'))
        return code if self.has_icons else fallback

    def apply_ttk(self):
        p, S = self.p, self.S
        st = ttk.Style(self.root)
        st.theme_use('clam')
        st.configure('.', background=p['bg'], foreground=p['text'], bordercolor=p['border'],
                     lightcolor=p['bg'], darkcolor=p['bg'], troughcolor=p['track'], focuscolor=p['accent'],
                     selectbackground=p['accent'], selectforeground=p['accent_text'], insertcolor=p['text'],
                     fieldbackground=p['input'], font=self.f_body)
        for name in ('TEntry', 'TSpinbox', 'TCombobox'):
            st.configure(name, fieldbackground=p['input'], foreground=p['text'], bordercolor=p['input_border'],
                         lightcolor=p['input'], darkcolor=p['input'], insertcolor=p['text'], arrowcolor=p['subtext'],
                         background=p['input'], padding=(S(8), S(5)), selectbackground=p['accent'],
                         selectforeground=p['accent_text'], arrowsize=S(12))
            st.map(name, bordercolor=[('focus', p['accent'])], lightcolor=[('focus', p['input'])],
                   fieldbackground=[('readonly', p['input']), ('disabled', p['surface2'])],
                   foreground=[('disabled', p['muted'])], background=[('active', p['input'])],
                   arrowcolor=[('disabled', p['muted'])])
        st.map('TCombobox', selectbackground=[('readonly', p['input'])], selectforeground=[('readonly', p['text'])])
        self.root.option_add('*TCombobox*Listbox.background', p['surface'])
        self.root.option_add('*TCombobox*Listbox.foreground', p['text'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', p['accent'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', p['accent_text'])
        self.root.option_add('*TCombobox*Listbox.font', self.f_body)
        self.root.option_add('*TCombobox*Listbox.borderWidth', 0)
        st.configure('TCheckbutton', background=p['bg'], foreground=p['text'], indicatorbackground=p['input'],
                     indicatorforeground=p['accent_text'], upperbordercolor=p['input_border'],
                     lowerbordercolor=p['input_border'], indicatormargin=(0, 0, S(8), 0), padding=(0, S(3)))
        st.map('TCheckbutton', background=[('active', p['bg'])],
               indicatorbackground=[('selected', p['accent']), ('active', p['button_hover'])],
               upperbordercolor=[('selected', p['accent'])], lowerbordercolor=[('selected', p['accent'])])
        self._checkbox_images(st)
        st.configure('Card.TCheckbutton', background=p['surface'])
        st.map('Card.TCheckbutton', background=[('active', p['surface'])])
        st.configure('TRadiobutton', background=p['bg'], foreground=p['text'], indicatorbackground=p['input'],
                     indicatorforeground=p['accent'], upperbordercolor=p['input_border'],
                     lowerbordercolor=p['input_border'], padding=(0, S(2)))
        st.map('TRadiobutton', background=[('active', p['bg'])],
               indicatorbackground=[('selected', p['input'])])
        st.layout('Slim.Vertical.TScrollbar', [('Vertical.Scrollbar.trough', {'sticky': 'ns', 'children': [
            ('Vertical.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})]})])
        st.configure('Slim.Vertical.TScrollbar', troughcolor=p['surface'], background=p['scroll'],
                     bordercolor=p['surface'], lightcolor=p['scroll'], darkcolor=p['scroll'], gripcount=0,
                     arrowsize=S(9))
        st.map('Slim.Vertical.TScrollbar', background=[('active', p['muted'])])
        st.configure('Treeview', background=p['surface'], fieldbackground=p['surface'], foreground=p['text'],
                     bordercolor=p['border'], lightcolor=p['surface'], darkcolor=p['surface'],
                     rowheight=S(28), font=self.f_body)
        st.map('Treeview', background=[('selected', p['select'])], foreground=[('selected', p['text'])])
        st.configure('Treeview.Heading', background=p['surface2'], foreground=p['subtext'], font=self.f_small_bold,
                     bordercolor=p['border'], lightcolor=p['surface2'], darkcolor=p['surface2'], relief='flat',
                     padding=(S(6), S(5)))
        st.map('Treeview.Heading', background=[('active', p['hover'])])
        st.configure('Nilou.Horizontal.TProgressbar', troughcolor=p['track'], background=p['accent'],
                     bordercolor=p['track'], lightcolor=p['accent'], darkcolor=p['accent'], thickness=S(6))


    def _checkbox_images(self, st):
        """Swap ttk's dated ✕ checkbox for anti-aliased images rendered by tools/make_icon.py."""
        from .paths import resource_path
        variant = 'dark' if self.dark else 'light'
        size = min((16, 20, 24, 32), key=lambda s: abs(s - self.S(17)))
        element = f'Nilou{variant}{size}.indicator'
        if element not in _CHECK_IMAGES:
            files = {s: resource_path('assets', 'ui', f'check-{s}-{variant}-{size}.png') for s in ('on', 'off')}
            if not all(os.path.exists(f) for f in files.values()):
                return
            on = tk.PhotoImage(master=self.root, file=files['on'])
            off = tk.PhotoImage(master=self.root, file=files['off'])
            _CHECK_IMAGES[element] = (on, off)
            try:
                st.element_create(element, 'image', off, ('selected', on), width=on.width() + self.S(8), sticky='w')
            except tk.TclError:
                pass
        st.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
            (element, {'side': 'left', 'sticky': ''}),
            ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [
                ('Checkbutton.label', {'sticky': 'nswe'})]})]})])


_CHECK_IMAGES = {}   # kept alive for the whole session: ttk elements cannot be deleted


class IconButton(tk.Frame):
    """Flat button with an optional Fluent icon. kind: primary | secondary | ghost | danger."""

    def __init__(self, master, theme, text='', icon=None, command=None, kind='ghost', bg=None, padx=11, pady=6,
                 tooltip=None):
        self.theme = theme
        self.kind = kind
        self.command = command
        self.base_bg = bg or theme.p['bg']
        self._enabled = True
        self._hover = False
        super().__init__(master, bd=0, highlightthickness=1 if kind == 'secondary' else 0, cursor='hand2')
        S = theme.S
        self.labels = []
        if icon:
            li = tk.Label(self, text=theme.glyph(icon), font=theme.f_icon, bd=0)
            li.pack(side='left', padx=(S(padx), S(6) if text else S(padx)), pady=S(pady))
            self.labels.append(li)
        if text:
            lt = tk.Label(self, text=text, font=theme.f_bold if kind in ('primary', 'danger') else theme.f_body, bd=0)
            lt.pack(side='left', padx=(0 if icon else S(padx + 3), S(padx + 3) if not icon else S(padx)), pady=S(pady))
            self.labels.append(lt)
        for w in [self] + self.labels:
            w.bind('<Enter>', self._enter)
            w.bind('<Leave>', self._leave)
            w.bind('<ButtonRelease-1>', self._click)
        self.tooltip = Tooltip(self, theme, tooltip) if tooltip else None
        self._paint()

    def _colors(self):
        p = self.theme.p
        if self.kind == 'primary':
            bg = p['accent_hover'] if self._hover and self._enabled else p['accent']
            fg = p['accent_text']
            if not self._enabled:
                bg, fg = p['track'], p['muted']
        elif self.kind == 'danger':
            bg = p['danger']
            fg = '#ffffff'
        elif self.kind == 'secondary':
            bg = p['button_hover'] if self._hover and self._enabled else p['button']
            fg = p['text'] if self._enabled else p['muted']
        else:
            bg = p['hover'] if self._hover and self._enabled else self.base_bg
            fg = p['text'] if self._enabled else p['muted']
        return bg, fg

    def _paint(self):
        bg, fg = self._colors()
        self.configure(bg=bg, highlightbackground=self.theme.p['input_border'], highlightcolor=self.theme.p['accent'])
        for lbl in self.labels:
            lbl.configure(bg=bg, fg=fg)

    def _enter(self, _e):
        self._hover = True
        self._paint()

    def _leave(self, _e):
        self._hover = False
        self._paint()

    def _click(self, e):
        if not self._enabled or not self.command:
            return
        x, y = e.x_root - self.winfo_rootx(), e.y_root - self.winfo_rooty()
        if 0 <= x < self.winfo_width() and 0 <= y < self.winfo_height():
            self.command()

    def set_enabled(self, enabled):
        if enabled != self._enabled:
            self._enabled = enabled
            self.configure(cursor='hand2' if enabled else 'arrow')
            self._paint()

    def set_text(self, text):
        if self.labels:
            self.labels[-1].configure(text=text)


class Tooltip:
    def __init__(self, widget, theme, text):
        self.widget, self.theme, self.text = widget, theme, text
        self.tip = None
        self._after = None
        widget.bind('<Enter>', self._schedule, add='+')
        widget.bind('<Leave>', self._hide, add='+')
        widget.bind('<ButtonPress>', self._hide, add='+')
        for child in widget.winfo_children():
            child.bind('<Enter>', self._schedule, add='+')
            child.bind('<Leave>', self._hide, add='+')

    def _schedule(self, _e=None):
        self._cancel()
        self._after = self.widget.after(600, self._show)

    def _cancel(self):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self):
        if self.tip or not self.text:
            return
        p = self.theme.p
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + self.theme.S(4)
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.attributes('-topmost', True)
        tk.Label(self.tip, text=self.text, bg=p['surface'], fg=p['text'], font=self.theme.f_small,
                 padx=self.theme.S(8), pady=self.theme.S(4), highlightthickness=1,
                 highlightbackground=p['border']).pack()
        self.tip.wm_geometry(f'+{x}+{y}')

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None
