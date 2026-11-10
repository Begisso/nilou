"""Render Nilou's lotus icon: transparent background, 10-color palette, soft gradients.

Run with the build venv (needs Pillow):  .venv\\Scripts\\python tools\\make_icon.py
Writes assets/nilou.ico, assets/nilou-*.png and extension/icons/icon*.png.
"""
import math
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = 1024

# The whole icon uses exactly these 10 colors; petals blend between neighbours.
PALETTE = {
    'indigo': (38, 42, 140),
    'violet': (98, 76, 200),
    'royal': (36, 92, 214),
    'blue': (52, 136, 236),
    'sky': (100, 182, 246),
    'ice': (180, 227, 252),
    'white': (240, 250, 255),
    'orange': (246, 150, 32),
    'yellow': (255, 214, 72),
    'cyan': (34, 200, 226),
}


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def gradient3(c0, c1, c2, t):
    return lerp(c0, c1, t / 0.5) if t < 0.5 else lerp(c1, c2, (t - 0.5) / 0.5)


def bezier(p0, p1, p2, p3, n):
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0]
        y = mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]
        pts.append((x, y))
    return pts


def petal_outline(length, width):
    """Upright petal with its base at (0, 0) and its tip at (0, -length)."""
    left = bezier((0, 0), (-width * 1.18, -length * 0.20), (-width * 0.92, -length * 0.74), (0, -length), 40)
    right = [(-x, y) for x, y in reversed(left)]
    return left + right[1:]


def draw_petal(canvas, base, angle, length, width, colors, outline):
    radius = int(length + 16)
    size = radius * 2
    c0, c1, c2 = (PALETTE[c] for c in colors)
    grad = Image.new('RGBA', (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = min(1.0, max(0.0, (radius - y) / length))
        gd.line([(0, y), (size, y)], fill=gradient3(c0, c1, c2, t) + (255,))
    pts = [(radius + x, radius + y) for x, y in petal_outline(length, width)]
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    petal = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    petal.paste(grad, mask=mask)
    d = ImageDraw.Draw(petal)
    # a soft centre vein in the petal's own tip colour
    vein = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(vein).line([(radius, radius - length * 0.10), (radius, radius - length * 0.78)],
                              fill=c2 + (110,), width=max(2, int(width * 0.06)))
    petal = Image.alpha_composite(petal, Image.composite(vein, Image.new('RGBA', (size, size)), mask))
    d = ImageDraw.Draw(petal)
    d.line(pts + [pts[0]], fill=PALETTE[outline] + (255,), width=max(3, int(width * 0.075)), joint='curve')
    petal = petal.rotate(-angle, resample=Image.BICUBIC, center=(radius, radius))
    layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    layer.paste(petal, (int(base[0] - radius), int(base[1] - radius)), petal)
    return Image.alpha_composite(canvas, layer)


def draw_center(canvas, cx, cy):
    layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rx, ry = 70, 30
    for deg in range(-80, 81, 8):
        a = math.radians(deg)
        sx, sy = cx + rx * 0.85 * math.sin(a), cy - ry * 0.6 * math.cos(a)
        length = 84 - abs(deg) * 0.25
        ex, ey = sx + length * math.sin(a), sy - length * math.cos(a)
        d.line([(sx, sy), (ex, ey)], fill=PALETTE['orange'] + (255,), width=9)
        d.ellipse([ex - 9, ey - 9, ex + 9, ey + 9], fill=PALETTE['yellow'] + (255,))
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=PALETTE['cyan'] + (255,),
              outline=PALETTE['royal'] + (255,), width=6)
    d.ellipse([cx - rx * 0.62, cy - ry * 0.68, cx + rx * 0.62, cy + ry * 0.2], fill=PALETTE['ice'] + (150,))
    for ox, oy in ((-34, -4), (-12, -10), (12, -10), (34, -4), (-22, 9), (0, 4), (22, 9)):
        d.ellipse([cx + ox - 6, cy + oy - 5, cx + ox + 6, cy + oy + 5], fill=PALETTE['royal'] + (255,))
    return Image.alpha_composite(canvas, layer)


def render_master():
    work = 1400
    img = Image.new('RGBA', (work, work), (0, 0, 0, 0))
    cx = work // 2
    # 1. outer, nearly horizontal petals (darkest)
    for angle in (-80, 80, -63, 63):
        img = draw_petal(img, (cx, 760), angle, 410, 98, ('indigo', 'violet', 'sky'), 'indigo')
    # 2. tall back petals
    for angle in (0, -20, 20, -40, 40):
        length = 450 if angle == 0 else 425
        img = draw_petal(img, (cx, 760), angle, length, 92, ('royal', 'blue', 'ice'), 'indigo')
    # 3. middle ring
    for angle in (-54, 54, -29, 29):
        img = draw_petal(img, (cx, 770), angle, 335, 94, ('royal', 'sky', 'white'), 'royal')
    # 4. stamens and seed pod
    img = draw_center(img, cx, 572)
    # 5. petals curling down at the bottom
    for angle in (-122, 122, -152, 152, 180):
        img = draw_petal(img, (cx, 805), angle, 215, 82, ('blue', 'royal', 'violet'), 'indigo')
    # 6. front cup
    for angle in (-25, 25, 0):
        img = draw_petal(img, (cx, 850), angle, 280 if angle == 0 else 262, 92, ('blue', 'sky', 'white'), 'royal')
    # trim and centre on a square canvas
    bbox = img.getbbox()
    img = img.crop(bbox)
    margin = int(MASTER * 0.03)
    scale = (MASTER - 2 * margin) / max(img.width, img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    out = Image.new('RGBA', (MASTER, MASTER), (0, 0, 0, 0))
    out.paste(img, ((MASTER - img.width) // 2, (MASTER - img.height) // 2), img)
    return out


def main():
    master = render_master()
    assets = os.path.join(ROOT, 'assets')
    icons = os.path.join(ROOT, 'extension', 'icons')
    os.makedirs(assets, exist_ok=True)
    os.makedirs(icons, exist_ok=True)
    sizes = {}
    for s in (16, 20, 24, 32, 40, 48, 64, 128, 256, 512):
        sizes[s] = master.resize((s, s), Image.LANCZOS)
    for s in (16, 32, 48, 256, 512):
        sizes[s].save(os.path.join(assets, f'nilou-{s}.png'))
    for s in (16, 32, 48, 128):
        sizes[s].save(os.path.join(icons, f'icon{s}.png'))
    ico_sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    sizes[256].save(os.path.join(assets, 'nilou.ico'), format='ICO', sizes=[(s, s) for s in ico_sizes],
                    append_images=[sizes[s] for s in ico_sizes if s != 256], bitmap_format='bmp')
    render_checkboxes(os.path.join(assets, 'ui'))
    print('icon written to', assets)


CHECKBOX_THEMES = {
    'light': {'fill': '#ffffff', 'border': '#9ea3b8', 'accent': '#3563e9', 'mark': '#ffffff'},
    'dark': {'fill': '#23252f', 'border': '#5f6479', 'accent': '#6e95ff', 'mark': '#0d1020'},
}


def render_checkboxes(folder):
    """Anti-aliased checkbox indicators for the Tk UI (ttk's own look is dated)."""
    os.makedirs(folder, exist_ok=True)
    k = 8
    for theme, c in CHECKBOX_THEMES.items():
        for size in (16, 20, 24, 32):
            big = size * k
            inset = big * 0.06
            for state in ('off', 'on'):
                img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                box = [inset, inset, big - inset, big - inset]
                if state == 'on':
                    d.rounded_rectangle(box, radius=big * 0.22, fill=c['accent'])
                    pts = [(big * 0.27, big * 0.52), (big * 0.44, big * 0.68), (big * 0.74, big * 0.35)]
                    w = int(big * 0.11)
                    d.line(pts, fill=c['mark'], width=w, joint='curve')
                    for x, y in (pts[0], pts[-1]):
                        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=c['mark'])
                else:
                    d.rounded_rectangle(box, radius=big * 0.22, fill=c['fill'], outline=c['border'],
                                        width=max(k, int(big * 0.07)))
                img.resize((size, size), Image.LANCZOS).save(os.path.join(folder, f'check-{state}-{theme}-{size}.png'))


if __name__ == '__main__':
    main()
