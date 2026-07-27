#!/usr/bin/env python3
"""Tools for the bundled OCI draw.io shape library (mxlibrary format).

The library is a JSON array wrapped in <mxlibrary> tags. Each entry:
  {"xml": <deflate-compressed base64 mxGraphModel>, "w": int, "h": int,
   "aspect": "fixed", "title": "Compute - Virtual Machine VM"}
The decompressed xml is a group of mxCells whose styles carry
shape=stencil(...) vector data - cloning those cells into a diagram
reproduces the icon exactly as draw.io renders it.

Usage:
  python3 library_tools.py list [filter]           # list shape titles
  python3 library_tools.py show "<title>"          # print decompressed xml
As a module:
  lib = Library(path)
  cells, w, h = lib.shape_cells("Compute - Virtual Machine VM")
"""
import json, zlib, base64, urllib.parse, sys, re, os
import xml.etree.ElementTree as ET

DEFAULT_LIB = os.path.join(os.path.dirname(__file__), '..', 'assets',
                           'OCI Library.xml')


class Library:
    def __init__(self, path=DEFAULT_LIB):
        with open(path, encoding='utf-8') as library_file:
            raw = library_file.read()
        body = raw[raw.index('>') + 1: raw.rfind('</mxlibrary>')]
        self.entries = {e['title']: e for e in json.loads(body) if e.get('title')}

    def titles(self, flt=None):
        t = sorted(self.entries)
        if flt:
            t = [x for x in t if flt.lower() in x.lower()]
        return t

    def resolve(self, title):
        """Exact match, else case-insensitive substring match."""
        if title in self.entries:
            return title
        low = title.lower()
        cands = [t for t in self.entries if low in t.lower()]
        if not cands:
            raise KeyError(f'No library shape matching {title!r}. '
                           f'Run "library_tools.py list" to see titles.')
        # prefer shortest (most specific) match
        return min(cands, key=len)

    def shape_xml(self, title):
        e = self.entries[self.resolve(title)]
        xml = zlib.decompress(base64.b64decode(e['xml']), -15).decode()
        return urllib.parse.unquote(xml), e.get('w', 84), e.get('h', 84)

    def shape_cells(self, title):
        """Return list of mxCell Elements (ids/parents intact), plus w, h."""
        xml, w, h = self.shape_xml(title)
        root = ET.fromstring(xml).find('root')
        cells = [c for c in root.findall('mxCell') if c.get('id') not in ('0', '1')]
        return cells, w, h


if __name__ == '__main__':
    lib = Library()
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'list'
    if cmd == 'list':
        for t in lib.titles(sys.argv[2] if len(sys.argv) > 2 else None):
            print(t)
    elif cmd == 'show':
        xml, w, h = lib.shape_xml(sys.argv[2])
        print(f'<!-- w={w} h={h} -->')
        print(xml)
