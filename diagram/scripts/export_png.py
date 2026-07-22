#!/usr/bin/env python3
"""Render a PNG preview of a diagram-spec JSON with REAL OCI stencil icons.

Uses pycairo to execute the same vector paths (move/line/curve) that draw.io
renders from the library stencils, so icons in the PNG match the .drawio.
Containers, dashed borders, labels, and orthogonal edges are drawn natively.

Usage: python3 export_png.py spec.json output.png
Requires: pycairo (usually preinstalled; else pip install pycairo --break-system-packages)
"""
import json, sys, os, re, zlib, base64, urllib.parse, math
import xml.etree.ElementTree as ET
import cairo

sys.path.insert(0, os.path.dirname(__file__))
from library_tools import Library

# Palette sampled from the original Oracle BOM diagram:
#   burnt orange #AE562C (VCN/subnet borders, red titles), brighter #BB501C
#   (compartment accents), dark slate-teal #2D5967 (icons), warm light grey
#   #F5F4F2 (region fill), warm near-black #312D2A (text), warm greys
#   #9E9892 / #D0CBC7 (neutral borders).
TEXT = '#312D2A'
SUBTEXT = '#6B6560'
CONTAINER = {   # style: (stroke, fill, dash, fontsize, bold, tint_label)
    'tenancy':     ('#9E9892', None,      (6, 4), 20, False, False),
    'region':      ('#C6C1BC', '#F5F4F2', None,   19, True,  False),
    'compartment': ('#BB501C', None,      (4, 3), 17, True,  True),
    'vcn':         ('#AE562C', None,      (6, 3), 16, True,  True),
    'subnet':      ('#AE562C', None,      (2, 2), 15, False, True),
    'ad':          ('#5E7D82', '#E9F0F0', None,   15, True,  True),
    'plain':       ('#9E9892', '#FFFFFF', None,   16, False, False),
    'note':        ('#B5B0AA', '#FFFFFF', None,   15, False, False),
    'external':    ('#9E9892', '#FFFFFF', (5, 3), 16, False, False),
}
EDGE = {  # style: (color, width, dash, arrow_filled)
    'solid':  ('#55504B', 1.6, None,   True),
    'dashed': ('#55504B', 1.3, (6, 4), False),
    'backup': ('#8B857F', 1.2, (2, 3), False),
    'plain':  ('#55504B', 1.6, None,   None),
}


def hexrgb(s):
    s = s.lstrip('#')
    return int(s[0:2], 16) / 255, int(s[2:4], 16) / 255, int(s[4:6], 16) / 255


def decode_stencil(blob):
    xml = zlib.decompress(base64.b64decode(blob), -15).decode()
    return ET.fromstring(urllib.parse.unquote(xml))


def draw_stencil(ctx, shape_root, x, y, w, h, fill):
    """Execute stencil path ops scaled from 100x100 space into (x,y,w,h)."""
    sw = float(shape_root.get('w', 100)); sh = float(shape_root.get('h', 100))
    sx, sy = w / sw, h / sh
    ctx.save(); ctx.translate(x, y); ctx.scale(sx, sy)
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    for path in shape_root.iter('path'):
        ctx.new_path()
        for op in path:
            if op.tag == 'move':
                ctx.move_to(float(op.get('x')), float(op.get('y')))
            elif op.tag == 'line':
                ctx.line_to(float(op.get('x')), float(op.get('y')))
            elif op.tag == 'curve':
                ctx.curve_to(float(op.get('x1')), float(op.get('y1')),
                             float(op.get('x2')), float(op.get('y2')),
                             float(op.get('x3')), float(op.get('y3')))
            elif op.tag == 'close':
                ctx.close_path()
        ctx.set_source_rgb(*fill)
        ctx.fill()
    ctx.restore()


class IconRenderer:
    """Renders a library shape (group of stencil cells) at any size."""
    def __init__(self, lib):
        self.lib = lib
        self.cache = {}

    def parts(self, title):
        t = self.lib.resolve(title)
        if t in self.cache:
            return self.cache[t]
        xml, w, h = self.lib.shape_xml(t)
        root = ET.fromstring(xml).find('root')
        cells = {c.get('id'): c for c in root.findall('mxCell')}
        out = []

        def abs_geo(cell):
            gx = gy = 0.0
            cur = cell
            while cur is not None:
                g = cur.find('mxGeometry')
                if g is not None:
                    gx += float(g.get('x', 0)); gy += float(g.get('y', 0))
                cur = cells.get(cur.get('parent'))
            g = cell.find('mxGeometry')
            return (gx, gy, float(g.get('width', 0)) if g is not None else 0,
                    float(g.get('height', 0)) if g is not None else 0)

        for c in cells.values():
            style = c.get('style', '')
            m = re.search(r'shape=stencil\(([^)]+)\)', style)
            if not m:
                continue
            fm = re.search(r'fillColor=(#[0-9A-Fa-f]{6})', style)
            if fm:
                fill = hexrgb(fm.group(1))
            elif 'fillColor=none' in style:
                continue    # invisible helper cell (fill and stroke both none)
            else:
                fill = (0.2, 0.2, 0.2)
            gx, gy, gw, gh = abs_geo(c)
            out.append((decode_stencil(m.group(1)), gx, gy, gw, gh, fill))
        self.cache[t] = (out, w, h)
        return self.cache[t]

    def draw(self, ctx, title, x, y, w, h):
        parts, lw, lh = self.parts(title)
        sx, sy = w / lw, h / lh
        for shape_root, gx, gy, gw, gh, fill in parts:
            draw_stencil(ctx, shape_root, x + gx * sx, y + gy * sy,
                         gw * sx, gh * sy, fill)


def text(ctx, s, x, y, size=12, color='#333333', bold=False, center=False,
         max_w=None):
    ctx.select_font_face('sans-serif', cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)
    ctx.set_source_rgb(*hexrgb(color))
    for i, line in enumerate(s.split('\n')):
        ext = ctx.text_extents(line)
        tx = x - ext.width / 2 if center else x
        ctx.move_to(tx, y + i * (size + 3))
        ctx.show_text(line)


def rounded_rect(ctx, x, y, w, h, r):
    ctx.new_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def render(spec, node_bounds, out_png, lib_path=None):
    page = spec.get('page', {})
    W, H = int(page.get('width', 2600)), int(page.get('height', 2050))
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    ctx.set_source_rgb(1, 1, 1); ctx.paint()
    icons = IconRenderer(Library(lib_path) if lib_path else Library())

    for con in spec.get('containers', []):
        stroke, fill, dash, fs, bold, tint = CONTAINER.get(
            con.get('style', 'plain'), CONTAINER['plain'])
        x, y, w, h = con['x'], con['y'], con['w'], con['h']
        if fill:
            rounded_rect(ctx, x, y, w, h, 8)
            ctx.set_source_rgb(*hexrgb(fill)); ctx.fill()
        rounded_rect(ctx, x, y, w, h, 8 if fill else 1)
        ctx.set_source_rgb(*hexrgb(stroke))
        ctx.set_line_width(1.4)
        ctx.set_dash(dash or [])
        ctx.stroke(); ctx.set_dash([])
        if con.get('label'):
            lines = con['label'].split('\n')
            text(ctx, lines[0], x + 10, y + fs + 8, fs,
                 stroke if tint else '#333333', bold)
            for k, line in enumerate(lines[1:]):
                text(ctx, line, x + 10, y + fs + 8 + (k + 1) * (fs + 3),
                     fs - 1, '#555555')

    def center(nid):
        b = node_bounds[nid]
        return b[0] + b[2] / 2, b[1] + b[3] / 2

    for e in spec.get('edges', []):
        if e['source'] not in node_bounds or e['target'] not in node_bounds:
            continue
        color, lw, dash, filled = EDGE.get(e.get('style', 'solid'), EDGE['solid'])
        ax, ay = center(e['source']); bx, by = center(e['target'])
        ctx.set_source_rgb(*hexrgb(color)); ctx.set_line_width(lw)
        ctx.set_dash(dash or [])
        ctx.move_to(ax, ay); ctx.line_to(bx, ay); ctx.line_to(bx, by)
        ctx.stroke(); ctx.set_dash([])
        if filled is not None:      # arrowhead at target
            ang = math.pi / 2 if by > ay else -math.pi / 2
            if abs(by - ay) < 2:
                ang = 0 if bx > ax else math.pi
            ctx.save(); ctx.translate(bx, by); ctx.rotate(
                ang if abs(by - ay) >= 2 else (0 if bx > ax else math.pi))
            ctx.move_to(0, 0); ctx.line_to(-9, -4.5); ctx.line_to(-9, 4.5)
            ctx.close_path()
            ctx.set_source_rgb(*hexrgb(color))
            ctx.fill() if filled else ctx.stroke()
            ctx.restore()
        if e.get('label'):
            mx, my = (ax + bx) / 2, ay
            ext_w = 8.4 * len(e['label'])
            ctx.set_source_rgb(1, 1, 1)
            ctx.rectangle(mx - ext_w / 2, my - 17, ext_w, 20); ctx.fill()
            text(ctx, e['label'], mx, my - 3, 14, '#333333', center=True)

    for node in spec.get('nodes', []):
        nid = node.get('id')
        if nid not in node_bounds:
            continue
        x, y, w, h = node_bounds[nid]
        if 'text' in node:
            text(ctx, node['text'], x + 4, y + 16, 15)
            continue
        icons.draw(ctx, node['shape'], x, y, w, h)
        if node.get('label'):
            for k, line in enumerate(node['label'].split('\n')):
                text(ctx, line, x + w / 2, y + h + 22 + k * 20, 15,
                     '#333333', center=True)

    surf.write_to_png(out_png)
    print('wrote', out_png, f'({W}x{H})')


if __name__ == '__main__':
    spec = json.load(open(sys.argv[1]))
    bounds = {}
    for c in spec.get('containers', []):
        bounds[c.get('id', '')] = (c['x'], c['y'], c['w'], c['h'])
    for n in spec.get('nodes', []):
        bounds[n.get('id', '')] = (n['x'], n['y'],
                                   n.get('w', 84), n.get('h', 84))
    render(spec, bounds, sys.argv[2])
