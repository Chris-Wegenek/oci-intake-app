#!/usr/bin/env python3
"""Build an editable .drawio file (and PNG preview) from a diagram-spec JSON.

Usage: python3 build_diagram.py spec.json output.drawio [output.png]

Diagram-spec schema (all coordinates in px, origin top-left):
{
  "title": "OCI Target Architecture",
  "page": {"width": 2600, "height": 2050},
  "containers": [                      # drawn back-to-front, in order
    {"id": "tenancy", "label": "Customer OCI Tenancy",
     "x": 20, "y": 20, "w": 2400, "h": 1900,
     "style": "tenancy"}               # tenancy|region|compartment|vcn|subnet|plain|note
  ],
  "nodes": [
    {"id": "drg", "shape": "Networking - Dynamic Routing Gateway DRG",
     "label": "Shared DRG\nhub-spoke transit",
     "x": 400, "y": 500, "w": 64, "h": 64},   # w/h optional (library default)
    {"id": "note1", "text": "free text box", "x":.., "y":.., "w":.., "h":..}
  ],
  "edges": [
    {"source": "cpe", "target": "drg", "label": "Private BGP",
     "style": "solid"}                 # solid|dashed|dotted-arrow (backup flows)
  ]
}
Container styles follow OCI diagram conventions (see references/).
"""
import json, sys, os
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(__file__))
from library_tools import Library

CONTAINER_STYLES = {
    'tenancy':     'rounded=0;whiteSpace=wrap;html=1;fillColor=none;'
                   'strokeColor=#9E9892;dashed=1;verticalAlign=top;align=left;'
                   'spacing=8;fontSize=20;fontColor=#312D2A;',
    'region':      'rounded=1;arcSize=4;whiteSpace=wrap;html=1;fillColor=#F5F4F2;'
                   'strokeColor=#C6C1BC;verticalAlign=top;align=center;'
                   'spacing=6;fontSize=19;fontStyle=1;fontColor=#312D2A;',
    'compartment': 'rounded=0;whiteSpace=wrap;html=1;fillColor=none;'
                   'strokeColor=#BB501C;dashed=1;dashPattern=4 3;verticalAlign=top;'
                   'align=left;spacing=6;fontSize=17;fontStyle=1;fontColor=#AE562C;',
    'vcn':         'rounded=0;whiteSpace=wrap;html=1;fillColor=none;'
                   'strokeColor=#AE562C;dashed=1;dashPattern=6 3;verticalAlign=top;'
                   'align=left;spacing=6;fontSize=16;fontStyle=1;fontColor=#AE562C;',
    'subnet':      'rounded=0;whiteSpace=wrap;html=1;fillColor=none;'
                   'strokeColor=#AE562C;dashed=1;dashPattern=2 2;verticalAlign=top;'
                   'align=left;spacing=4;fontSize=15;fontColor=#AE562C;',
    # Availability Domain — Oracle draws these as solid-bordered light containers, distinct
    # from the orange dashed subnets/VCNs.
    'ad':          'rounded=1;arcSize=3;whiteSpace=wrap;html=1;fillColor=#E9F0F0;'
                   'strokeColor=#5E7D82;dashed=0;verticalAlign=top;align=left;'
                   'spacing=6;fontSize=15;fontStyle=1;fontColor=#2D5967;',
    'plain':       'rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor=#FFFFFF;'
                   'strokeColor=#9E9892;verticalAlign=top;align=center;'
                   'spacing=6;fontSize=16;fontColor=#312D2A;',
    'note':        'rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor=#FFFFFF;'
                   'strokeColor=#BB501C;verticalAlign=top;align=left;'
                   'spacing=8;fontSize=15;fontColor=#312D2A;',
    'external':    'rounded=1;arcSize=8;whiteSpace=wrap;html=1;fillColor=#FFFFFF;'
                   'strokeColor=#9E9892;dashed=1;verticalAlign=middle;align=center;'
                   'spacing=6;fontSize=16;fontColor=#312D2A;',
}
EDGE_STYLES = {
    'solid':  'edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#55504B;'
              'strokeWidth=1.5;fontSize=14;fontColor=#312D2A;endArrow=block;endFill=1;',
    'dashed': 'edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#55504B;'
              'strokeWidth=1.2;dashed=1;fontSize=14;fontColor=#312D2A;'
              'endArrow=block;endFill=0;',
    'backup': 'edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#8B857F;'
              'strokeWidth=1.2;dashed=1;dashPattern=2 2;fontSize=14;'
              'fontColor=#6B6560;endArrow=open;endFill=0;',
    'plain':  'edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#55504B;'
              'strokeWidth=1.5;fontSize=14;fontColor=#312D2A;endArrow=none;',
}
LABEL_STYLE = ('text;html=1;align=center;verticalAlign=top;fontSize=15;'
               'fontColor=#312D2A;whiteSpace=wrap;')


def build(spec_path, out_drawio, out_png=None, lib_path=None):
    spec = json.load(open(spec_path))
    lib = Library(lib_path) if lib_path else Library()

    mxfile = ET.Element('mxfile', host='app.diagrams.net')
    diagram = ET.SubElement(mxfile, 'diagram',
                            name=spec.get('title', 'OCI Architecture'), id='oci-1')
    page = spec.get('page', {})
    model = ET.SubElement(
        diagram, 'mxGraphModel',
        dx='1000', dy='800', grid='0', gridSize='10', guides='1', tooltips='1',
        connect='1', arrows='1', fold='1', page='1', pageScale='1',
        pageWidth=str(page.get('width', 2600)), pageHeight=str(page.get('height', 2050)),
        math='0', shadow='0')
    root = ET.SubElement(model, 'root')
    ET.SubElement(root, 'mxCell', id='0')
    ET.SubElement(root, 'mxCell', id='1', parent='0')

    def add_vertex(cid, value, style, x, y, w, h):
        c = ET.SubElement(root, 'mxCell', id=cid, value=value, style=style,
                          vertex='1', parent='1')
        ET.SubElement(c, 'mxGeometry', x=str(x), y=str(y), width=str(w),
                      height=str(h)).set('as', 'geometry')
        return c

    node_bounds = {}

    for i, con in enumerate(spec.get('containers', [])):
        style = CONTAINER_STYLES.get(con.get('style', 'plain'),
                                     CONTAINER_STYLES['plain'])
        cid = con.get('id', f'container{i}')
        add_vertex(cid, con.get('label', ''), style,
                   con['x'], con['y'], con['w'], con['h'])
        node_bounds[cid] = (con['x'], con['y'], con['w'], con['h'])

    ncounter = [0]
    for node in spec.get('nodes', []):
        nid = node.get('id') or f'n{ncounter[0]}'
        ncounter[0] += 1
        if 'text' in node:  # plain text box
            add_vertex(nid, node['text'], LABEL_STYLE, node['x'], node['y'],
                       node.get('w', 160), node.get('h', 40))
            node_bounds[nid] = (node['x'], node['y'],
                                node.get('w', 160), node.get('h', 40))
            continue
        cells, lw, lh = lib.shape_cells(node['shape'])
        w, h = node.get('w', lw), node.get('h', lh)
        sx, sy = w / lw, h / lh
        # wrap the library group in a positioned group cell
        gid = f'{nid}_g'
        g = ET.SubElement(root, 'mxCell', id=gid, style='group', vertex='1',
                          connectable='0', parent='1')
        ET.SubElement(g, 'mxGeometry', x=str(node['x']), y=str(node['y']),
                      width=str(w), height=str(h)).set('as', 'geometry')
        idmap = {'0': '0', '1': gid}
        for j, cell in enumerate(cells):
            old = cell.get('id')
            idmap[old] = f'{nid}_c{j}'
        for cell in cells:
            nc = ET.SubElement(root, 'mxCell')
            for k, v in cell.attrib.items():
                if k == 'id':
                    nc.set('id', idmap[v])
                elif k == 'parent':
                    nc.set('parent', idmap.get(v, gid))
                else:
                    nc.set(k, v)
            geo = cell.find('mxGeometry')
            if geo is not None:
                ng = ET.SubElement(nc, 'mxGeometry')
                for k, v in geo.attrib.items():
                    if k in ('x', 'y'):
                        ng.set(k, str(float(v) * (sx if k == 'x' else sy)))
                    elif k == 'width':
                        ng.set(k, str(float(v) * sx))
                    elif k == 'height':
                        ng.set(k, str(float(v) * sy))
                    else:
                        ng.set(k, v)
                ng.set('as', 'geometry')
        node_bounds[nid] = (node['x'], node['y'], w, h)
        if node.get('label'):
            add_vertex(f'{nid}_lbl', node['label'], LABEL_STYLE,
                       node['x'] - 30, node['y'] + h + 4, w + 60, 30)

    for i, e in enumerate(spec.get('edges', [])):
        style = EDGE_STYLES.get(e.get('style', 'solid'), EDGE_STYLES['solid'])
        src = e['source'] if e['source'] in node_bounds else e['source']
        c = ET.SubElement(root, 'mxCell', id=f'e{i}', value=e.get('label', ''),
                          style=style, edge='1', parent='1',
                          source=f"{src}_g" if f"{src}_g" in
                          [x.get('id') for x in root] else src,
                          target=f"{e['target']}_g" if f"{e['target']}_g" in
                          [x.get('id') for x in root] else e['target'])
        ET.SubElement(c, 'mxGeometry', relative='1').set('as', 'geometry')

    ET.indent(mxfile)
    ET.ElementTree(mxfile).write(out_drawio, encoding='utf-8',
                                 xml_declaration=True)
    print('wrote', out_drawio)

    if out_png:
        import export_png
        export_png.render(spec, node_bounds, out_png)


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
