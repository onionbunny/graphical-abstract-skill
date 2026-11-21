#!/usr/bin/env python3
"""Deterministic renderer: figure_spec.json -> layered, editable SVG.
Stdlib only. Same spec -> byte-identical SVG (no timestamps, no randomness).
Every element carries id + data-source provenance + semantic data-* attributes
so svg_to_spec.py can reconstruct the spec exactly (source-preserving editing).
"""
import argparse, json, math, sys
from xml.sax.saxutils import escape

FONT = "DejaVu Sans, Arial, Helvetica, sans-serif"
ROLE_COLORS = {"question": "#0072B2", "methods": "#009E73",
               "results": "#D55E00", "conclusion": "#CC79A7"}
ROLE_NAMES = {"question": "Question", "methods": "Methods",
              "results": "Results", "conclusion": "Conclusion"}
REL_STYLE = {"activates": ("", "arrow", "#333333"),
             "inhibits": ("", "tbar", "#333333"),
             "converts": ("", "arrow", "#333333"),
             "contains": ("1.2,0.8", "diamond", "#666666"),
             "measures": ("1.2,0.8", "arrow", "#666666"),
             "flow": ("", "arrow", "#888888")}
S = {"title": 4.5, "panel": 3.4, "concl": 3.2, "label": 2.8,
     "legend": 2.6, "tick": 2.2, "value": 2.4, "rel": 2.4}


def esc(s):
    return escape(str(s), {'"': "&quot;"})


def fmt(v):
    return f"{v:g}"


def tw(s, size):
    return sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in s) * size


def wrap(s, size, maxw):
    # Greedy word-aware wrap: break at spaces; only split a single word when
    # that word alone is wider than the available width.
    words, lines, cur = s.split(" "), [], ""
    for w in words:
        trial = w if not cur else cur + " " + w
        if tw(trial, size) > maxw and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        if tw(ln, size) <= maxw:
            out.append(ln)
            continue
        sub = ""
        for ch in ln:
            if tw(sub + ch, size) > maxw and sub:
                out.append(sub)
                sub = ch
            else:
                sub += ch
        if sub:
            out.append(sub)
    return out


def src_attr(o):
    s = o.get("source", {})
    return f'{s.get("file", "")}#{s.get("locator", "")}'


class SVG:
    def __init__(self, w, h, root_attrs=""):
        self.w, self.h = w, h
        self.root_attrs = root_attrs
        self.layers = {k: [] for k in
                       ("background", "panels", "charts", "relations",
                        "entities", "labels", "legend")}

    def add(self, layer, s):
        self.layers[layer].append(s)

    def text(self, layer, x, y, s, size, fill="#111111", anchor="start",
             weight="normal", eid=None, src=None):
        a = f' id="{eid}"' if eid else ""
        d = f' data-source="{esc(src)}"' if src else ""
        self.add(layer, f'<text{a}{d} x="{x:.2f}" y="{y:.2f}" '
                 f'font-family="{FONT}" font-size="{size}" fill="{fill}" '
                 f'text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')

    def dump(self, meta):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
                f'width="{self.w}mm" height="{self.h}mm" '
                f'viewBox="0 0 {self.w} {self.h}"{self.root_attrs}>\n')
        md = ('<metadata id="provenance">'
              + esc(json.dumps(meta, ensure_ascii=False, sort_keys=True))
              + '</metadata>\n')
        body = ""
        for name, items in self.layers.items():
            body += (f'<g inkscape:groupmode="layer" inkscape:label="{name}" id="layer-{name}">\n'
                     + "\n".join(items) + "\n</g>\n")
        return head + md + body + "</svg>\n"


def arrowhead(svg, layer, eid, tx, ty, ux, uy, col, kind):
    px_, py_ = -uy, ux
    if kind == "arrow":
        bx, by = tx - ux * 2.2, ty - uy * 2.2
        pts = (f"{tx:.2f},{ty:.2f} {bx + px_ * 1.1:.2f},{by + py_ * 1.1:.2f} "
               f"{bx - px_ * 1.1:.2f},{by - py_ * 1.1:.2f}")
        svg.add(layer, f'<polygon id="{eid}-head" points="{pts}" fill="{col}" stroke="none"/>')
    elif kind == "diamond":
        cx, cy = tx - ux * 1.5, ty - uy * 1.5
        pts = (f"{tx:.2f},{ty:.2f} {cx + px_:.2f},{cy + py_:.2f} "
               f"{cx - ux * 1.5:.2f},{cy - uy * 1.5:.2f} {cx - px_:.2f},{cy - py_:.2f}")
        svg.add(layer, f'<polygon id="{eid}-head" points="{pts}" fill="#FFFFFF" stroke="{col}" stroke-width="0.4"/>')
    elif kind == "tbar":
        svg.add(layer, f'<line id="{eid}-tbar" x1="{tx - px_ * 2:.2f}" y1="{ty - py_ * 2:.2f}" '
                f'x2="{tx + px_ * 2:.2f}" y2="{ty + py_ * 2:.2f}" stroke="{col}" stroke-width="0.8"/>')


def shape(svg, e, cx, cy, r, stroke, fill, fill_op, panel):
    k, eid, src = e["kind"], e["id"], src_attr(e)
    sem = (f'data-kind="{k}" data-panel="{panel}" data-slot="{e["slot"][0]},{e["slot"][1]}" '
           f'data-label="{esc(e["label"])}"')
    if e.get("group"):
        sem += f' data-group="{esc(e["group"])}"'
    common = f'id="{eid}" data-source="{esc(src)}" {sem} fill="{fill}" fill-opacity="{fill_op}" stroke="{stroke}" stroke-width="0.5"'
    if k == "molecule":
        pts = " ".join(f"{cx + r * math.cos(math.pi / 3 * i):.2f},{cy + r * math.sin(math.pi / 3 * i):.2f}" for i in range(6))
        svg.add("entities", f'<polygon {common} points="{pts}"/>')
    elif k in ("cell", "complex"):
        dash = ' stroke-dasharray="1.2,0.8"' if k == "complex" else ""
        svg.add("entities", f'<circle {common}{dash} cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}"/>')
        if k == "cell":
            svg.add("entities", f'<circle id="{eid}-nucleus" cx="{cx:.2f}" cy="{cy:.2f}" r="{r * 0.35:.2f}" fill="{stroke}" fill-opacity="0.35" stroke="none"/>')
    elif k == "sample":
        svg.add("entities", f'<ellipse {common} cx="{cx:.2f}" cy="{cy:.2f}" rx="{r:.2f}" ry="{r * 0.7:.2f}"/>')
    else:
        rx = 3 if k == "process" else 1.2
        w, h = r * 2.2, r * 1.5
        svg.add("entities", f'<rect {common} x="{cx - w / 2:.2f}" y="{cy - h / 2:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{rx}"/>')
        if k == "device":
            for i in (-1, 1):
                svg.add("entities", f'<rect id="{eid}-pin{i}" x="{cx + i * w / 2 - (0.8 if i < 0 else 0):.2f}" y="{cy - 0.5:.2f}" width="0.8" height="1" fill="{stroke}" stroke="none"/>')


def draw_chart(svg, c, rect, groups):
    x, y, w, h = rect
    pad_l, pad_b, pad_t = 9.0, 7.0, 6.5
    px, py, pw, ph = x + pad_l, y + pad_t, w - pad_l - 2, h - pad_t - pad_b
    lo, hi = c["scale"]["min"], c["scale"]["max"]
    src = src_attr(c)
    cats = list(dict.fromkeys(s.get("category", "") for s in c["series"]))
    grouped = any(cats)
    sem = (f'data-panel="{c["panel"]}" data-kind="{c.get("kind", "bar")}" '
           f'data-unit="{esc(c["unit"])}" data-title="{esc(c.get("title", ""))}" '
           f'data-scale-min="{lo}" data-scale-max="{hi}"')
    svg.add("charts", f'<g id="{c["id"]}" data-source="{esc(src)}" {sem}>')
    svg.add("charts", f'<line id="{c["id"]}-yaxis" x1="{px:.2f}" y1="{py:.2f}" x2="{px:.2f}" y2="{py + ph:.2f}" stroke="#333333" stroke-width="0.4"/>')
    svg.add("charts", f'<line id="{c["id"]}-xaxis" x1="{px:.2f}" y1="{py + ph:.2f}" x2="{px + pw:.2f}" y2="{py + ph:.2f}" stroke="#333333" stroke-width="0.4"/>')
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        ty = py + ph - ph * i / 4
        svg.add("charts", f'<line x1="{px - 0.8:.2f}" y1="{ty:.2f}" x2="{px:.2f}" y2="{ty:.2f}" stroke="#333333" stroke-width="0.3"/>')
        svg.text("charts", px - 1.4, ty + 0.8, fmt(v), S["tick"], anchor="end")
    svg.text("charts", x + 0.5, y + 2.6, f'{c.get("title", "")} ({c["unit"]})', S["value"], weight="bold", eid=f'{c["id"]}-title', src=src)
    if c.get("kind", "bar") == "line":
        _line_chart(svg, c, (px, py, pw, ph), lo, hi, groups, src)
    elif grouped:
        ncat = len(cats)
        slot = pw / ncat
        for ci, cat in enumerate(cats):
            members = [s for s in c["series"] if s.get("category", "") == cat]
            bw = min(slot / (len(members) + 1), 10.0)
            gx = px + slot * ci + (slot - bw * len(members)) / 2
            for k, s in enumerate(members):
                _bar(svg, c, s, gx + bw * (k + 0.5), bw * 0.85, py, ph, lo, hi, groups, src, show_label=False)
            for j, ln in enumerate(wrap(cat, S["tick"], slot - 1)[:2]):
                svg.text("labels", px + slot * (ci + 0.5), py + ph + 2.6 + j * 2.6, ln, S["tick"], anchor="middle", eid=f'{c["id"]}-cat{ci}-label{j}')
    else:
        n = len(c["series"])
        slot = pw / n
        bw = min(slot * 0.6, 12.0)
        for i, s in enumerate(c["series"]):
            _bar(svg, c, s, px + slot * (i + 0.5), bw, py, ph, lo, hi, groups, src, show_label=True)
    svg.add("charts", "</g>")


def _y_of(v, lo, hi, py, ph):
    frac = max(0.0, min(1.0, (v - lo) / (hi - lo)))
    return py + ph - ph * frac


def _line_chart(svg, c, plot, lo, hi, groups, src):
    px, py, pw, ph = plot
    xlabels = list(dict.fromkeys(s["label"] for s in c["series"]))
    n = len(xlabels)
    slot = pw / n
    xpos = {lab: px + slot * (i + 0.5) for i, lab in enumerate(xlabels)}
    by_group = {}
    for s in c["series"]:
        by_group.setdefault(s["group"], []).append(s)
    for gk in sorted(by_group):
        col = groups[gk]["color"]
        pts = sorted(by_group[gk], key=lambda s: xlabels.index(s["label"]))
        coords = [(xpos[s["label"]], _y_of(s["value"], lo, hi, py, ph)) for s in pts]
        pstr = " ".join(f"{cx:.2f},{cy:.2f}" for cx, cy in coords)
        svg.add("charts", f'<polyline id="{c["id"]}-{gk}-line" data-source="{esc(src)}" '
                f'data-group="{esc(gk)}" data-chart-kind="line" points="{pstr}" fill="none" '
                f'stroke="{col}" stroke-width="0.6"/>')
        for s, (cx, cy) in zip(pts, coords):
            sem = (f'data-group="{esc(s["group"])}" data-label="{esc(s["label"])}" '
                   f'data-value="{s["value"]}"')
            if s.get("error") is not None:
                sem += f' data-error="{s["error"]}"'
            svg.add("charts", f'<circle id="{c["id"]}-{s["id"]}" data-source="{esc(src)}" '
                    f'{sem} cx="{cx:.2f}" cy="{cy:.2f}" r="1.1" fill="{col}" '
                    f'stroke="#333333" stroke-width="0.2"/>')
            if s.get("error"):
                eh = ph * min(1.0, s["error"] / (hi - lo))
                for dy in (-eh, eh):
                    svg.add("charts", f'<line x1="{cx - 1:.2f}" y1="{cy + dy:.2f}" '
                            f'x2="{cx + 1:.2f}" y2="{cy + dy:.2f}" stroke="#333333" stroke-width="0.4"/>')
                vy = cy - eh - 1.0
            else:
                vy = cy - 1.6
            svg.text("labels", cx, vy, fmt(s["value"]), S["value"], anchor="middle",
                     eid=f'{c["id"]}-{s["id"]}-value')
    for i, lab in enumerate(xlabels):
        cx = px + slot * (i + 0.5)
        for j, ln in enumerate(wrap(lab, S["tick"], slot - 0.5)[:2]):
            svg.text("labels", cx, py + ph + 2.6 + j * 2.6, ln, S["tick"],
                     anchor="middle", eid=f'{c["id"]}-xtick{i}-{j}')


def _bar(svg, c, s, cx, bw, py, ph, lo, hi, groups, src, show_label):
    frac = max(0.0, min(1.0, (s["value"] - lo) / (hi - lo)))
    bh = ph * frac
    col = groups[s["group"]]["color"]
    top = py + ph - bh
    sem = (f'data-group="{esc(s["group"])}" data-label="{esc(s["label"])}" '
           f'data-value="{s["value"]}"')
    if s.get("category"):
        sem += f' data-category="{esc(s["category"])}"'
    if s.get("error") is not None:
        sem += f' data-error="{s["error"]}"'
    svg.add("charts", f'<rect id="{c["id"]}-{s["id"]}" data-source="{esc(src)}" {sem} x="{cx - bw / 2:.2f}" y="{top:.2f}" width="{bw:.2f}" height="{bh:.2f}" fill="{col}" stroke="#333333" stroke-width="0.2"/>')
    if s.get("error"):
        eh = ph * min(1.0, s["error"] / (hi - lo))
        svg.add("charts", f'<line id="{c["id"]}-{s["id"]}-error" x1="{cx:.2f}" y1="{top - eh:.2f}" x2="{cx:.2f}" y2="{top + eh:.2f}" stroke="#333333" stroke-width="0.4"/>')
        for dy in (-eh, eh):
            svg.add("charts", f'<line x1="{cx - 1:.2f}" y1="{top + dy:.2f}" x2="{cx + 1:.2f}" y2="{top + dy:.2f}" stroke="#333333" stroke-width="0.4"/>')
        vy = top - eh - 1.0
    else:
        vy = top - 1.0
    svg.text("labels", cx, vy, fmt(s["value"]), S["value"], anchor="middle", eid=f'{c["id"]}-{s["id"]}-value')
    if show_label:
        for j, ln in enumerate(wrap(s["label"], S["tick"], bw * 1.8)[:2]):
            svg.text("labels", cx, py + ph + 2.6 + j * 2.6, ln, S["tick"], anchor="middle", eid=f'{c["id"]}-{s["id"]}-label{j}')


def render(spec):
    W = spec.get("canvas", {}).get("width_mm", 180)
    H = spec.get("canvas", {}).get("height_mm", 120)
    dpi = spec.get("canvas", {}).get("dpi", 300)
    root_attrs = (f' data-case-id="{esc(spec.get("case_id", ""))}" data-dpi="{dpi}"'
                  f' data-spec-version="{esc(spec.get("spec_version", "1.0"))}"')
    svg = SVG(W, H, root_attrs)
    groups = spec.get("groups", {})
    m, title_h, legend_h, gap = 6.0, 9.0, 14.0, 4.0
    svg.add("background", f'<rect id="canvas-bg" x="0" y="0" width="{W}" height="{H}" fill="#FFFFFF"/>')
    svg.text("labels", m, m + 3.5, spec["title"], S["title"], weight="bold", eid="fig-title")
    panels = sorted(spec["panels"], key=lambda p: (p["grid"][0], p["grid"][1]))
    rows = max(p["grid"][0] for p in panels) + 1
    cols = max(p["grid"][1] for p in panels) + 1
    aw, ah = W - 2 * m, H - 2 * m - title_h - legend_h
    pw, ph = (aw - (cols - 1) * gap) / cols, (ah - (rows - 1) * gap) / rows
    centers, radii, panel_of, etop = {}, {}, {}, {}
    charts_by_panel, ents_by_panel = {}, {}
    for c in spec.get("charts", []):
        charts_by_panel.setdefault(c["panel"], []).append(c)
    for e in spec["entities"]:
        ents_by_panel.setdefault(e["panel"], []).append(e)
    for num, p in enumerate(panels, 1):
        r, c = p["grid"]
        x, y = m + c * (pw + gap), m + title_h + r * (ph + gap)
        rc = ROLE_COLORS[p["role"]]
        tlines = wrap(f'{ROLE_NAMES[p["role"]]}: {p["title"]}', S["panel"], pw - 9)[:2]
        hh = 7.0 if len(tlines) == 1 else 10.6
        svg.add("panels", f'<rect id="{p["id"]}" data-role="{p["role"]}" data-grid="{r},{c}" data-title="{esc(p["title"])}" x="{x:.2f}" y="{y:.2f}" width="{pw:.2f}" height="{ph:.2f}" rx="2" fill="#FFFFFF" stroke="{rc}" stroke-width="0.5"/>')
        svg.add("panels", f'<rect id="{p["id"]}-header" x="{x:.2f}" y="{y:.2f}" width="{pw:.2f}" height="{hh}" rx="2" fill="{rc}" fill-opacity="0.15" stroke="none"/>')
        svg.add("panels", f'<circle id="{p["id"]}-badge" cx="{x + 3.5:.2f}" cy="{y + 3.5:.2f}" r="2.4" fill="{rc}"/>')
        svg.text("panels", x + 3.5, y + 4.5, str(num), 3.0, fill="#FFFFFF", anchor="middle", weight="bold")
        for j, ln in enumerate(tlines):
            svg.text("panels", x + 7.5, y + 4.6 + j * 3.8, ln, S["panel"], weight="bold", eid=f'{p["id"]}-title{j}')
        cx0, cy0, cw, ch = x + 2, y + hh + 1.5, pw - 4, ph - hh - 3.5
        has_chart = p["id"] in charts_by_panel
        has_ents = p["id"] in ents_by_panel
        ent_h = ch * (0.52 if has_chart and has_ents else 1.0)
        if has_ents:
            ents = ents_by_panel[p["id"]]
            ec = max(3, max(e["slot"][1] for e in ents) + 1)
            er = max(e["slot"][0] for e in ents) + 1
            cellw, cellh = cw / ec, ent_h / er
            for e in ents:
                sr, sc = e["slot"]
                ex, ey = cx0 + (sc + 0.5) * cellw, cy0 + (sr + 0.42) * cellh
                rad = min(cellw * 0.30, cellh * 0.26, 8.0)
                fill, fop = ("#FFFFFF", "1")
                if e.get("group") in groups:
                    fill, fop = groups[e["group"]]["color"], "0.25"
                shape(svg, e, ex, ey, rad, rc, fill, fop, p["id"])
                centers[e["id"]] = (ex, ey)
                radii[e["id"]] = rad * (1.15 if e["kind"] in ("material", "device", "process") else 1.0)
                panel_of[e["id"]] = p["id"]
                etop[e["id"]] = cy0
                for j, ln in enumerate(wrap(e["label"], S["label"], cellw - 1)[:3]):
                    svg.text("labels", ex, ey + rad + 3.0 + j * 3.2, ln, S["label"], anchor="middle", eid=f'{e["id"]}-label{j}', src=src_attr(e))
        if p["role"] == "conclusion" and spec.get("conclusion"):
            ty = cy0 + (ent_h + 3 if has_ents else 4)
            for j, ln in enumerate(wrap(spec["conclusion"]["text"], S["concl"], cw - 2)[:8]):
                svg.text("labels", cx0 + 1, ty + j * 4.2, ln, S["concl"], eid=f'conclusion-line{j}', src=src_attr(spec["conclusion"]))
        if has_chart:
            cy = cy0 + ent_h + 1 if has_ents else cy0
            chh = ch - ent_h - 1 if has_ents else ch
            for c in charts_by_panel[p["id"]]:
                draw_chart(svg, c, (cx0, cy, cw, chh), groups)
    for ri, rel in enumerate(spec.get("relations", [])):
        if rel["from"] not in centers or rel["to"] not in centers:
            continue
        (x1, y1), (x2, y2) = centers[rel["from"]], centers[rel["to"]]
        dash, marker, col = REL_STYLE[rel["type"]]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        sem = (f'id="{rel["id"]}" data-source="{esc(src_attr(rel))}" data-type="{rel["type"]}" '
               f'data-from="{rel["from"]}" data-to="{rel["to"]}"')
        shorten = {"arrow": 2.0, "diamond": 2.8, "tbar": 0.0}[marker]
        if panel_of[rel["from"]] != panel_of[rel["to"]]:
            # cross-panel: orthogonal route via corridor above entities (no piercing)
            corr = min(etop[rel["from"]], etop[rel["to"]]) + 0.6
            rf, rt = radii[rel["from"]], radii[rel["to"]]
            tipx, tipy = x2, y2 - rt - 0.5
            pts = [(x1, y1 - rf), (x1, corr), (x2, corr), (tipx, tipy - shorten)]
            pstr = " ".join(f"{px:.2f},{py:.2f}" for px, py in pts)
            svg.add("relations", f'<polyline {sem} points="{pstr}" fill="none" stroke="{col}" stroke-width="0.5"{da}/>')
            arrowhead(svg, "relations", rel["id"], tipx, tipy, 0, 1, col, marker)
            mx, my = x1, (y1 - rf + corr) / 2 + 1.0
        else:
            dx, dy = x2 - x1, y2 - y1
            d = math.hypot(dx, dy) or 1
            ux, uy = dx / d, dy / d
            sx, sy = x1 + ux * radii[rel["from"]], y1 + uy * radii[rel["from"]]
            ex, ey = x2 - ux * (radii[rel["to"]] + 1.5), y2 - uy * (radii[rel["to"]] + 1.5)
            lx2, ly2 = ex - ux * shorten, ey - uy * shorten
            svg.add("relations", f'<line {sem} x1="{sx:.2f}" y1="{sy:.2f}" x2="{lx2:.2f}" y2="{ly2:.2f}" stroke="{col}" stroke-width="0.5"{da}/>')
            arrowhead(svg, "relations", rel["id"], ex, ey, ux, uy, col, marker)
            t = 0.4 + 0.2 * (ri % 2)
            perp = 2.5 if ri % 2 else -2.5
            mx, my = sx + (ex - sx) * t - uy * perp, sy + (ey - sy) * t + ux * perp
        if rel.get("label"):
            lw = tw(rel["label"], S["rel"]) + 1.5
            svg.add("labels", f'<rect id="{rel["id"]}-labelbg" x="{mx - lw / 2:.2f}" y="{my - 2.4:.2f}" width="{lw:.2f}" height="3.2" fill="#FFFFFF" fill-opacity="0.9" stroke="none"/>')
            svg.text("labels", mx, my, rel["label"], S["rel"], anchor="middle", fill="#333333", eid=f'{rel["id"]}-label')
    lx, ly = m, H - m - legend_h + 4
    items = [("swatch", gk, groups[gk]) for gk in sorted(groups)]
    items += [("rel", rt, rt) for rt in dict.fromkeys(r["type"] for r in spec.get("relations", []))]
    for kind, key, val in items:
        label = val["label"] if kind == "swatch" else val
        iw = 6 + tw(label, S["legend"]) + 5
        if lx + iw > W - m:
            lx = m; ly += 5
        if kind == "swatch":
            svg.add("legend", f'<rect id="legend-{key}" data-color="{val["color"]}" data-label="{esc(label)}" x="{lx:.2f}" y="{ly - 3:.2f}" width="4" height="4" fill="{val["color"]}" stroke="#333333" stroke-width="0.2"/>')
            svg.text("legend", lx + 6, ly, label, S["legend"], eid=f'legend-{key}-text')
        else:
            dash, marker, col = REL_STYLE[key]
            da = f' stroke-dasharray="{dash}"' if dash else ""
            shorten = {"arrow": 2.0, "diamond": 2.8, "tbar": 0.0}[marker]
            svg.add("legend", f'<line id="legend-rel-{key}" x1="{lx:.2f}" y1="{ly - 1.5:.2f}" x2="{lx + 5 - shorten:.2f}" y2="{ly - 1.5:.2f}" stroke="{col}" stroke-width="0.5"{da}/>')
            arrowhead(svg, "legend", f'legend-rel-{key}', lx + 5, ly - 1.5, 1, 0, col, marker)
            svg.text("legend", lx + 7, ly, label, S["legend"], eid=f'legend-rel-{key}-text')
        lx += iw
    prov = {}
    for o in spec["entities"] + spec.get("relations", []) + spec.get("charts", []):
        prov[o["id"]] = o.get("source", {})
    if spec.get("conclusion"):
        prov["conclusion"] = spec["conclusion"].get("source", {})
    meta = {"generator": "ga-render/1.1", "spec_version": spec.get("spec_version", "1.0"),
            "case_id": spec.get("case_id", ""), "provenance": prov,
            "uncertainties": spec.get("uncertainties", []),
            "off_figure_notes": spec.get("off_figure_notes", []),
            "conclusion_text": spec.get("conclusion", {}).get("text", "")}
    return svg.dump(meta)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    out = render(spec)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(f"OK rendered {a.out} ({len(out)} bytes)")


if __name__ == "__main__":
    main()