#!/usr/bin/env python3
"""Deterministic renderer: figure_spec.json -> layered, editable SVG.
Stdlib only. Same spec -> byte-identical SVG (no timestamps, no randomness).
Every element carries id + data-source provenance + semantic data-* attributes
so svg_to_spec.py can reconstruct the spec exactly (source-preserving editing).

Layout is fully adaptive: long titles/entity labels wrap or shrink to fit, mixed
panels (entities + chart) share the vertical space with a feasibility guard, and
cross-panel relations route through the top corridor using clear vertical lanes
so they never pierce unrelated entities.
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
MIN_FONT = 2.2


class RenderError(Exception):
    """Friendly, deterministic failure (no raw traceback to the harness)."""


def esc(s):
    return escape(str(s), {'"': "&quot;"})


def fmt(v):
    return f"{v:g}"


def tw(s, size):
    return sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in s) * size


def wrap(s, size, maxw):
    # Greedy word-aware wrap: break at spaces; only split a single word when
    # that word alone is wider than the available width.
    words, lines, cur = str(s).split(" "), [], ""
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


def fit_lines(text, size0, maxw, floor=MIN_FONT, max_lines=None):
    """Shrink font then wrap so every line fits maxw. Returns (size, lines)."""
    size = size0
    while size >= floor:
        lines = wrap(text, size, maxw)
        if max_lines is None or len(lines) <= max_lines:
            if all(tw(ln, size) <= maxw for ln in lines):
                return size, lines
        size -= 0.2
    return floor, wrap(text, floor, maxw)


def src_attr(o):
    s = o.get("source", {})
    return f'{s.get("file", "")}#{s.get("locator", "")}'


def overlap_box(a, b):
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return dx > 0 and dy > 0


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


def shape_bbox(kind, cx, cy, r):
    """True geometry bbox of a shape drawn with radius r (matches the validator)."""
    if kind in ("molecule", "cell", "complex"):
        return (cx - r, cy - r, cx + r, cy + r)
    if kind == "sample":
        return (cx - r, cy - 0.7 * r, cx + r, cy + 0.7 * r)
    # material / device / process: rect w=2.2r, h=1.5r
    return (cx - 1.1 * r, cy - 0.75 * r, cx + 1.1 * r, cy + 0.75 * r)


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
    lo, hi = c["scale"]["min"], c["scale"]["max"]
    if hi <= lo:
        raise RenderError(f"chart {c['id']}: scale max ({hi}) must be > min ({lo})")
    kind = c.get("kind", "bar")
    src = src_attr(c)
    # chart title: wrap to fit the chart width; it reserves its own vertical
    # block so tall bars never run into it.
    tsize, tlines = fit_lines(f'{c.get("title", "")} ({c["unit"]})', S["value"],
                              w - 1.0, floor=MIN_FONT, max_lines=2)
    title_block = 2.6 * len(tlines)
    # --- adaptive padding based on the actual available rect ---
    tick_vals = [lo + (hi - lo) * i / 4 for i in range(5)]
    ylab_w = max(tw(fmt(v), S["tick"]) for v in tick_vals)
    pad_l = min(max(ylab_w + 2.2, 4.5), 10.0)
    pad_b = max(3.0, min(6.5, h * 0.24))
    # reserve title + gap + room for the value labels that sit above full-height
    # points/bars (line error labels can reach ~3.5 above the plot top).
    pad_t = title_block + 3.4
    if h < pad_t + pad_b + 2.5:  # compact mode for short charts
        pad_t, pad_b = title_block + 1.5, 2.8
    px, py = x + pad_l, y + pad_t
    pw, ph = w - pad_l - 1.2, h - pad_t - pad_b
    if ph < 2.2 or pw < 6.0:
        raise RenderError(
            f"chart {c['id']}: chart area {w:.1f}x{h:.1f}mm too small to render; "
            "move the chart to its own panel or reduce entities in the panel")
    cats = list(dict.fromkeys(s.get("category", "") for s in c["series"]))
    grouped = any(cats)
    sem = (f'data-panel="{c["panel"]}" data-kind="{kind}" '
           f'data-unit="{esc(c["unit"])}" data-title="{esc(c.get("title", ""))}" '
           f'data-scale-min="{lo}" data-scale-max="{hi}"')
    svg.add("charts", f'<g id="{c["id"]}" data-source="{esc(src)}" {sem}>')
    svg.add("charts", f'<line id="{c["id"]}-yaxis" x1="{px:.2f}" y1="{py:.2f}" x2="{px:.2f}" y2="{py + ph:.2f}" stroke="#333333" stroke-width="0.4"/>')
    svg.add("charts", f'<line id="{c["id"]}-xaxis" x1="{px:.2f}" y1="{py + ph:.2f}" x2="{px + pw:.2f}" y2="{py + ph:.2f}" stroke="#333333" stroke-width="0.4"/>')
    # adaptive number of y ticks so labels never overlap in a short plot
    if ph >= 13.0:
        fracs = [0.0, 0.25, 0.5, 0.75, 1.0]
    elif ph >= 4.4:
        fracs = [0.0, 0.5, 1.0]
    else:
        fracs = [0.0, 1.0]
    for fr in fracs:
        v = lo + (hi - lo) * fr
        ty = py + ph - ph * fr
        svg.add("charts", f'<line x1="{px - 0.8:.2f}" y1="{ty:.2f}" x2="{px:.2f}" y2="{ty:.2f}" stroke="#333333" stroke-width="0.3"/>')
        svg.text("charts", px - 1.3, ty + 0.8, fmt(v), S["tick"], anchor="end")
    for j, ln in enumerate(tlines):
        svg.text("charts", x + 0.4, y + 2.2 + j * 2.6, ln, tsize,
                 weight="bold", eid=f'{c["id"]}-title' if j == 0 else None, src=src)
    if kind == "line":
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


def _vline_clear(x, ya, yb, blocker_boxes):
    """True if a vertical segment at x does not intersect any blocker bbox.
    Endpoint order (which y is larger) is irrelevant."""
    ymin, ymax = min(ya, yb), max(ya, yb)
    for (x0, y0, x1, y1) in blocker_boxes:
        if x0 < x < x1 and ymin < y1 and ymax > y0:
            return False
    return True


def _choose_lane(preferred_x, x_lo, x_hi, ya, yb, blocker_boxes, step=1.4, margin=0.0):
    """Nearest clear vertical lane to preferred_x inside [x_lo, x_hi].
    margin expands every blocker horizontally so a label centered on the lane
    also stays clear."""
    expanded = [(x0 - margin, y0, x1 + margin, y1) for (x0, y0, x1, y1) in blocker_boxes]
    if _vline_clear(preferred_x, ya, yb, expanded):
        return preferred_x
    k = 1
    while True:
        for cand in (preferred_x - k * step, preferred_x + k * step):
            if x_lo <= cand <= x_hi and _vline_clear(cand, ya, yb, expanded):
                return cand
        if preferred_x - k * step < x_lo and preferred_x + k * step > x_hi:
            return max(x_lo, min(x_hi, preferred_x))  # fallback: clamp
        k += 1


def render(spec):
    # --- preflight: fail fast with friendly messages instead of tracebacks ---
    for k in ("spec_version", "case_id", "title", "panels", "entities",
              "relations", "conclusion", "uncertainties"):
        if k not in spec:
            raise RenderError(f"spec missing required field: {k}")
    groups = spec.get("groups", {})
    eids = {e["id"] for e in spec["entities"]}
    for r in spec["relations"]:
        if r["type"] not in REL_STYLE:
            raise RenderError(f"relation {r.get('id')}: unknown type {r['type']} (run validate_figure.py)")
        if r["from"] not in eids or r["to"] not in eids:
            raise RenderError(f"relation {r.get('id')}: endpoints must be existing entities")
    for c in spec.get("charts", []):
        if c.get("unit") is None:
            raise RenderError(f"chart {c.get('id')}: unit is required")
        for s in c["series"]:
            if not isinstance(s.get("value"), (int, float)):
                raise RenderError(f"chart {c['id']} series {s.get('id')}: value must be numeric")
            if s.get("group") not in groups:
                raise RenderError(f"chart {c['id']} series {s.get('id')}: unknown group {s.get('group')}")

    W = spec.get("canvas", {}).get("width_mm", 180)
    H = spec.get("canvas", {}).get("height_mm", 120)
    dpi = spec.get("canvas", {}).get("dpi", 300)
    root_attrs = (f' data-case-id="{esc(spec.get("case_id", ""))}" data-dpi="{dpi}"'
                  f' data-spec-version="{esc(spec.get("spec_version", "1.0"))}"')
    svg = SVG(W, H, root_attrs)
    m, legend_h, gap = 6.0, 14.0, 4.0

    # --- title auto-fit (shrink/wrap to the canvas width) ---
    tsize, tlines = fit_lines(spec["title"], S["title"], W - 2 * m,
                              floor=3.0, max_lines=2)
    title_h = 3.0 + len(tlines) * 4.6
    svg.add("background", f'<rect id="canvas-bg" x="0" y="0" width="{W}" height="{H}" fill="#FFFFFF"/>')
    for j, ln in enumerate(tlines):
        svg.text("labels", m, m + 3.2 + j * 4.6, ln, tsize,
                 weight="bold", eid="fig-title" if j == 0 else None)

    panels = sorted(spec["panels"], key=lambda p: (p["grid"][0], p["grid"][1]))
    rows = max(p["grid"][0] for p in panels) + 1
    cols = max(p["grid"][1] for p in panels) + 1
    aw, ah = W - 2 * m, H - 2 * m - title_h - legend_h
    pw, ph = (aw - (cols - 1) * gap) / cols, (ah - (rows - 1) * gap) / cols
    centers, radii, panel_of, etop = {}, {}, {}, {}
    box_of = {}
    ent_bottom = {}
    label_text_boxes = []
    charts_by_panel, ents_by_panel = {}, {}
    for c in spec.get("charts", []):
        charts_by_panel.setdefault(c["panel"], []).append(c)
    for e in spec["entities"]:
        ents_by_panel.setdefault(e["panel"], []).append(e)
    for num, p in enumerate(panels, 1):
        r, c = p["grid"]
        x, y = m + c * (pw + gap), m + title_h + r * (ph + gap)
        rc = ROLE_COLORS[p["role"]]
        # strip a leading role word to avoid "Question: Question: ..."
        ptitle = p["title"].strip()
        rname = ROLE_NAMES[p["role"]]
        if ptitle.lower().startswith(rname.lower() + ":"):
            ptitle = ptitle[len(rname) + 1:].strip()
        tlines2 = wrap(f'{rname}: {ptitle}', S["panel"], pw - 9)[:2]
        hh = 7.0 if len(tlines2) == 1 else 10.6
        svg.add("panels", f'<rect id="{p["id"]}" data-role="{p["role"]}" data-grid="{r},{c}" data-title="{esc(p["title"])}" x="{x:.2f}" y="{y:.2f}" width="{pw:.2f}" height="{ph:.2f}" rx="2" fill="#FFFFFF" stroke="{rc}" stroke-width="0.5"/>')
        svg.add("panels", f'<rect id="{p["id"]}-header" x="{x:.2f}" y="{y:.2f}" width="{pw:.2f}" height="{hh}" rx="2" fill="{rc}" fill-opacity="0.15" stroke="none"/>')
        svg.add("panels", f'<circle id="{p["id"]}-badge" cx="{x + 3.5:.2f}" cy="{y + 3.5:.2f}" r="2.4" fill="{rc}"/>')
        svg.text("panels", x + 3.5, y + 4.5, str(num), 3.0, fill="#FFFFFF", anchor="middle", weight="bold")
        for j, ln in enumerate(tlines2):
            svg.text("panels", x + 7.5, y + 4.6 + j * 3.8, ln, S["panel"], weight="bold", eid=f'{p["id"]}-title{j}')
        cx0, cy0, cw, ch = x + 2, y + hh + 1.5, pw - 4, ph - hh - 3.5
        has_chart = p["id"] in charts_by_panel
        has_ents = p["id"] in ents_by_panel
        # vertical allocation: ent_h is set inside the entity block (mixed recomputes it)
        ent_h = ch
        if has_ents:
            ents = ents_by_panel[p["id"]]
            mixed = has_chart and has_ents
            if mixed:
                # compact vertical list: shape on the left, label beside it (vertical-efficient)
                ent_h = min(ch * 0.42, max(9.5, ch * 0.38))
                order = sorted(ents, key=lambda x: (x["slot"][0], x["slot"][1]))
                row_h = ent_h / max(1, len(order))
                for k, e in enumerate(order):
                    ex, ey = cx0 + min(row_h * 0.3, 2.2) + 1.5, cy0 + k * row_h + row_h / 2
                    rad = min(row_h * 0.3, 2.2)
                    fill, fop = ("#FFFFFF", "1")
                    if e.get("group") in groups:
                        fill, fop = groups[e["group"]]["color"], "0.25"
                    shape(svg, e, ex, ey, rad, rc, fill, fop, p["id"])
                    centers[e["id"]] = (ex, ey)
                    radii[e["id"]] = rad * (1.15 if e["kind"] in ("material", "device", "process") else 1.0)
                    panel_of[e["id"]] = p["id"]
                    etop[e["id"]] = cy0
                    box_of[e["id"]] = shape_bbox(e["kind"], ex, ey, rad)
                    lx = ex + rad + 2
                    lw = (cx0 + cw) - lx - 1
                    lsize, llines = fit_lines(e["label"], MIN_FONT, lw,
                                              floor=MIN_FONT, max_lines=3)
                    gap = lsize * 1.2
                    lbase = ey - (len(llines) - 1) * gap / 2 + 0.8
                    for j, ln in enumerate(llines):
                        bly = lbase + j * gap
                        svg.text("labels", lx, bly, ln, lsize,
                                 anchor="start", eid=f'{e["id"]}-label{j}', src=src_attr(e))
                        label_text_boxes.append(
                            (lx - 0.3, bly - lsize * 0.85, lx + tw(ln, lsize) + 0.3, bly + lsize * 0.35))
                    ent_bottom[p["id"]] = max(
                        ent_bottom.get(p["id"], cy0),
                        ey + rad, lbase + (len(llines) - 1) * gap + lsize * 0.35)
            else:
                ec = max(3, max(e["slot"][1] for e in ents) + 1)
                er = max(e["slot"][0] for e in ents) + 1
                cellw, cellh = cw / ec, ent_h / er
                for e in ents:
                    sr, sc = e["slot"]
                    ex, ey = cx0 + (sc + 0.5) * cellw, cy0 + (sr + 0.42) * cellh
                    rad = min(cellw * 0.30, cellh * 0.26, 7.0)
                    fill, fop = ("#FFFFFF", "1")
                    if e.get("group") in groups:
                        fill, fop = groups[e["group"]]["color"], "0.25"
                    shape(svg, e, ex, ey, rad, rc, fill, fop, p["id"])
                    centers[e["id"]] = (ex, ey)
                    radii[e["id"]] = rad * (1.15 if e["kind"] in ("material", "device", "process") else 1.0)
                    panel_of[e["id"]] = p["id"]
                    etop[e["id"]] = cy0
                    box_of[e["id"]] = shape_bbox(e["kind"], ex, ey, rad)
                    lsize, llines = fit_lines(e["label"], S["label"], cellw - 0.8,
                                              floor=MIN_FONT, max_lines=3)
                    for j, ln in enumerate(llines):
                        bly = ey + rad + 2.8 + j * 3.0
                        svg.text("labels", ex, bly, ln, lsize,
                                 anchor="middle", eid=f'{e["id"]}-label{j}', src=src_attr(e))
                        label_text_boxes.append(
                            (ex - tw(ln, lsize) / 2 - 0.3, bly - lsize * 0.85,
                             ex + tw(ln, lsize) / 2 + 0.3, bly + lsize * 0.35))
                    ent_bottom[p["id"]] = max(
                        ent_bottom.get(p["id"], cy0),
                        ey + rad, ey + rad + 2.8 + (len(llines) - 1) * 3.0 + lsize * 0.35)
        if p["role"] == "conclusion" and spec.get("conclusion"):
            # conclusion fits inside the remaining panel region below the entities
            cstart = ent_bottom.get(p["id"], cy0) + 1.5 if has_ents else cy0 + 3.0
            cavail = (y + ph - 2) - cstart
            csize = S["concl"]
            chosen = None
            while csize >= MIN_FONT:
                clines = wrap(spec["conclusion"]["text"], csize, cw - 2)
                linegap = csize * 1.28
                if len(clines) * linegap <= max(cavail, 0.5):
                    chosen = (csize, clines, linegap); break
                csize -= 0.2
            if chosen is None:
                clines = wrap(spec["conclusion"]["text"], MIN_FONT, cw - 2)
                chosen = (MIN_FONT, clines, MIN_FONT * 1.28)
            csize, clines, linegap = chosen
            for j, ln in enumerate(clines):
                svg.text("labels", cx0 + 1, cstart + linegap * (j + 0.8), ln, csize,
                         eid=f'conclusion-line{j}', src=src_attr(spec["conclusion"]))
        if has_chart:
            cy = cy0 + ent_h + 2 if has_ents else cy0
            chh = ch - ent_h - 2 if has_ents else ch
            for c in charts_by_panel[p["id"]]:
                draw_chart(svg, c, (cx0, cy, cw, chh), groups)

    # --- relations ---
    panel_bounds = {}
    for p in panels:
        r, c = p["grid"]
        x, y = m + c * (pw + gap), m + title_h + r * (ph + gap)
        panel_bounds[p["id"]] = (x + 2, x + pw - 2)
    cross_label_used = {}
    placed_label_boxes = []
    for ri, rel in enumerate(spec.get("relations", [])):
        if rel["from"] not in centers or rel["to"] not in centers:
            continue
        (x1, y1), (x2, y2) = centers[rel["from"]], centers[rel["to"]]
        dash, marker, col = REL_STYLE[rel["type"]]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        sem = (f'id="{rel["id"]}" data-source="{esc(src_attr(rel))}" data-type="{rel["type"]}" '
               f'data-from="{rel["from"]}" data-to="{rel["to"]}"')
        shorten = {"arrow": 2.0, "diamond": 2.8, "tbar": 0.0}[marker]
        relsize, lh = S["rel"], 3.2
        if panel_of[rel["from"]] != panel_of[rel["to"]]:
            # cross-panel: top corridor + clear vertical lanes (no entity piercing)
            corr = min(etop[rel["from"]], etop[rel["to"]]) - 0.4
            rf, rt = radii[rel["from"]], radii[rel["to"]]
            tipx, tipy = x2, y2 - rt - 0.5
            up_block = [box_of[e] for e in eids
                        if panel_of[e] == panel_of[rel["from"]] and e != rel["from"]]
            up_block += [b for b in label_text_boxes]
            down_block = [box_of[e] for e in eids if e != rel["to"]]
            down_block += [b for b in label_text_boxes]
            sx_lo, sx_hi = panel_bounds[panel_of[rel["from"]]]
            tx_lo, tx_hi = panel_bounds[panel_of[rel["to"]]]
            lab_w = tw(rel.get("label", ""), S["rel"]) + 1.5
            margin = lab_w / 2 + 0.6 if rel.get("label") else 0.0
            lane_s = _choose_lane(x1, sx_lo, sx_hi, y1 - rf, corr, up_block, margin=margin)
            lane_t = _choose_lane(tipx, tx_lo, tx_hi, corr, tipy, down_block)
            pts = [(lane_s, y1 - rf), (lane_s, corr), (lane_t, corr),
                   (lane_t, tipy), (tipx, tipy)]
            pstr = " ".join(f"{px:.2f},{py:.2f}" for px, py in pts)
            svg.add("relations", f'<polyline {sem} points="{pstr}" fill="none" stroke="{col}" stroke-width="0.5"{da}/>')
            arrowhead(svg, "relations", rel["id"], tipx, tipy, 0, 1, col, marker)
            # label on the source up-leg: pick a fraction whose box is clear
            leg_bot, leg_top = y1 - rf, corr
            mx, my = lane_s, (leg_bot + leg_top) / 2
            if rel.get("label"):
                for f in (0.5, 0.32, 0.68, 0.22, 0.78):
                    cyc = leg_bot + (leg_top - leg_bot) * f
                    cbox = (lane_s - lab_w / 2, cyc - 1.6, lane_s + lab_w / 2, cyc + 1.6)
                    if not any(overlap_box(cbox, b) for b in placed_label_boxes):
                        mx, my = lane_s, cyc; break
                placed_label_boxes.append(
                    (mx - lab_w / 2, my - 1.6, mx + lab_w / 2, my + 1.6))
        else:
            dx, dy = x2 - x1, y2 - y1
            d = math.hypot(dx, dy) or 1
            ux, uy = dx / d, dy / d
            sx, sy = x1 + ux * radii[rel["from"]], y1 + uy * radii[rel["from"]]
            ex, ey = x2 - ux * (radii[rel["to"]] + 1.5), y2 - uy * (radii[rel["to"]] + 1.5)
            lx2, ly2 = ex - ux * shorten, ey - uy * shorten
            svg.add("relations", f'<line {sem} x1="{sx:.2f}" y1="{sy:.2f}" x2="{lx2:.2f}" y2="{ly2:.2f}" stroke="{col}" stroke-width="0.5"{da}/>')
            arrowhead(svg, "relations", rel["id"], ex, ey, ux, uy, col, marker)
            # mixed-panel vertical relations are crowded: use the minimum font and
            # place the label in the clear inter-row gap; otherwise search offsets.
            panel_has_chart = panel_of[rel["from"]] in charts_by_panel
            relsize = MIN_FONT if (panel_has_chart and abs(dy) >= abs(dx)) else S["rel"]
            lh = relsize * (1.05 if relsize == MIN_FONT else 1.3)
            # place the label avoiding ALL panel entities (incl. endpoints)
            # and every already-placed label; vary perpendicular offset and
            # along-segment fraction to find a clear spot.
            allblock = [box_of[e["id"]]
                        for e in ents_by_panel.get(panel_of[rel["from"]], [])]
            allblock += label_text_boxes
            pxp, pyp = -uy, ux
            mx, my = (sx + lx2) / 2, (sy + ly2) / 2
            found = False
            # first candidate: clear inter-row gap. Search gy (the exact midpoint
            # may be too high); use the same text bbox model as the validator.
            gx = (x1 + x2) / 2
            gwlab = tw(rel.get("label", ""), relsize)
            gx0 = gx - gwlab / 2
            gy0 = (y1 + y2) / 2
            for dgy in [x * 0.2 for x in range(-10, 11)]:
                gy = gy0 + dgy
                gbox = (gx0, gy - relsize * 0.85, gx0 + gwlab, gy + relsize * 0.15)
                if not any(overlap_box(gbox, b) for b in allblock) and \
                   not any(overlap_box(gbox, b) for b in placed_label_boxes):
                    mx, my, found = gx, gy, True
                    break
            if not found:
                pxlo, pxhi = panel_bounds[panel_of[rel["from"]]]
                for off in (0, 2.6, -2.6, 4.2, -4.2, 5.6, -5.6, 7.2, -7.2, 9.0, -9.0):
                    for along in (0.5, 0.35, 0.65, 0.25, 0.75, 0.15, 0.85):
                        bx_ = sx + (lx2 - sx) * along
                        by_ = sy + (ly2 - sy) * along
                        cx_, cy_ = bx_ + pxp * off, by_ + pyp * off
                        lw_ = tw(rel.get("label", ""), relsize) + 1.0
                        lbox = (cx_ - lw_ / 2, cy_ - lh / 2,
                                cx_ + lw_ / 2, cy_ + lh / 2)
                        if lbox[0] >= pxlo and lbox[2] <= pxhi and \
                           not any(overlap_box(lbox, b) for b in allblock) and \
                           not any(overlap_box(lbox, b) for b in placed_label_boxes):
                            mx, my, found = cx_, cy_, True; break
                    if found:
                        break
            if rel.get("label"):
                wb = tw(rel["label"], relsize)
                placed_label_boxes.append(
                    (mx - wb / 2, my - relsize * 0.85, mx + wb / 2, my + relsize * 0.15))
        if rel.get("label"):
            wb = tw(rel["label"], relsize)
            svg.add("labels", f'<rect id="{rel["id"]}-labelbg" x="{mx - wb / 2 - 0.5:.2f}" y="{my - relsize * 0.85 - 0.3:.2f}" width="{wb + 1.0:.2f}" height="{relsize + 0.6:.2f}" fill="#FFFFFF" fill-opacity="0.92" stroke="none"/>')
            svg.text("labels", mx, my, rel["label"], relsize, anchor="middle", fill="#333333", eid=f'{rel["id"]}-label')

    # --- legend ---
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
    meta = {"generator": "ga-render/1.2", "spec_version": spec.get("spec_version", "1.0"),
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
    try:
        with open(a.spec, encoding="utf-8") as f:
            spec = json.load(f)
        out = render(spec)
    except FileNotFoundError:
        print(f"ERROR: spec file not found: {a.spec}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in {a.spec}: {e}", file=sys.stderr)
        sys.exit(2)
    except RenderError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(f"OK rendered {a.out} ({len(out)} bytes)")


if __name__ == "__main__":
    main()
