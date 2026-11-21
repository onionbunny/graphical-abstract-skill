#!/usr/bin/env python3
"""Validate figure_spec.json (pre-render) and rendered SVG (post-render).
Post-render adds deterministic geometry defect detection: text collisions,
text-over-entity overlap, relation lines piercing unrelated entities.
Outputs validation_report.json. Exit 0 = pass (warnings allowed), 1 = errors.
"""
import argparse, json, re, sys
import xml.etree.ElementTree as ET

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
KINDS = {"molecule", "cell", "material", "device", "sample", "process", "complex"}
RTYPES = {"activates", "inhibits", "converts", "contains", "measures", "flow"}
ROLES = {"question", "methods", "results", "conclusion"}
MIN_FONT = 2.2


def lum(hexc):
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def fmt(v):
    return f"{v:g}"


def tw(s, size):
    return sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in s) * size


def check_spec(spec, errors, warnings, checks):
    for k in ("spec_version", "case_id", "title", "panels", "entities", "relations", "conclusion", "uncertainties"):
        if k not in spec:
            errors.append(f"missing required field: {k}")
    if errors:
        return
    roles = {p["role"] for p in spec["panels"]}
    checks["four_elements_covered"] = {"question", "methods", "results"}.issubset(roles) and (
        "conclusion" in roles or bool(spec.get("conclusion", {}).get("text")))
    if not {"question", "methods", "results"}.issubset(roles):
        errors.append(f"panels must cover question/methods/results roles, got {sorted(roles)}")
    ids, slots = set(), set()
    for p in spec["panels"]:
        if p["id"] in ids:
            errors.append(f"duplicate id {p['id']}")
        ids.add(p["id"])
    pids = {p["id"] for p in spec["panels"]}
    groups = spec.get("groups", {})
    for gk, g in groups.items():
        if not HEX.match(g.get("color", "")):
            errors.append(f"group {gk}: invalid color {g.get('color')}")
    gkeys = sorted(groups)
    for i in range(len(gkeys)):
        for j in range(i + 1, len(gkeys)):
            dl = abs(lum(groups[gkeys[i]]["color"]) - lum(groups[gkeys[j]]["color"]))
            if dl < 0.15:
                warnings.append(f"grayscale risk: {gkeys[i]} vs {gkeys[j]} luminance diff {dl:.2f} < 0.15")
    checks["grayscale_pairs_checked"] = len(gkeys) * (len(gkeys) - 1) // 2
    n_src = 0
    def need_src(o, tag):
        nonlocal n_src
        s = o.get("source", {})
        if not (s.get("file") and s.get("locator") and s.get("quote")):
            errors.append(f"{tag} {o.get('id')}: incomplete source (file/locator/quote required)")
        else:
            n_src += 1
    for e in spec["entities"]:
        if e["id"] in ids:
            errors.append(f"duplicate id {e['id']}")
        ids.add(e["id"])
        if e["panel"] not in pids:
            errors.append(f"entity {e['id']}: unknown panel {e['panel']}")
        if e["kind"] not in KINDS:
            errors.append(f"entity {e['id']}: unknown kind {e['kind']}")
        sl = (e["panel"], e["slot"][0], e["slot"][1])
        if sl in slots:
            errors.append(f"entity {e['id']}: slot collision {sl}")
        slots.add(sl)
        if e.get("group") and e["group"] not in groups:
            errors.append(f"entity {e['id']}: unknown group {e['group']}")
        need_src(e, "entity")
    eids = {e["id"] for e in spec["entities"]}
    for r in spec["relations"]:
        if r["id"] in ids:
            errors.append(f"duplicate id {r['id']}")
        ids.add(r["id"])
        if r["type"] not in RTYPES:
            errors.append(f"relation {r['id']}: unknown type {r['type']}")
        if r["from"] not in eids or r["to"] not in eids:
            errors.append(f"relation {r['id']}: endpoint not an entity")
        if r["from"] == r["to"]:
            errors.append(f"relation {r['id']}: self-loop")
        need_src(r, "relation")
    for c in spec.get("charts", []):
        if c["id"] in ids:
            errors.append(f"duplicate id {c['id']}")
        ids.add(c["id"])
        if c["panel"] not in pids:
            errors.append(f"chart {c['id']}: unknown panel")
        lo, hi = c["scale"]["min"], c["scale"]["max"]
        if hi <= lo:
            errors.append(f"chart {c['id']}: scale max<=min")
        if lo != 0:
            warnings.append(f"chart {c['id']}: bar scale does not start at 0")
        if not c.get("unit"):
            errors.append(f"chart {c['id']}: missing unit")
        sids = set()
        for s in c["series"]:
            if s["id"] in sids:
                errors.append(f"chart {c['id']}: duplicate series id {s['id']}")
            sids.add(s["id"])
            if not isinstance(s["value"], (int, float)):
                errors.append(f"chart {c['id']} series {s['id']}: value not numeric")
            elif not (lo <= s["value"] <= hi):
                errors.append(f"chart {c['id']} series {s['id']}: value {s['value']} outside scale [{lo},{hi}]")
            if s.get("group") not in groups:
                errors.append(f"chart {c['id']} series {s['id']}: missing/unknown group")
            if s.get("error") is not None:
                if s["error"] < 0:
                    errors.append(f"chart {c['id']} series {s['id']}: negative error")
                elif s["value"] + s["error"] > hi:
                    warnings.append(f"chart {c['id']} series {s['id']}: value+error exceeds scale max (whisker clipped)")
        need_src(c, "chart")
    need_src(dict(spec["conclusion"], id="conclusion"), "conclusion")
    checks["elements_with_full_source"] = n_src
    checks["cjk_in_figure_text"] = any(
        ord(ch) > 0x2E80 for ch in spec["title"] + spec["conclusion"]["text"]
        + "".join(e["label"] for e in spec["entities"]))
    if checks["cjk_in_figure_text"]:
        warnings.append("CJK text on figure: ensure a CJK font is installed for export, or use English labels")


def bbox_of(el):
    tag = el.tag.split("}")[-1]
    f = lambda k, d=0.0: float(el.get(k, d))
    if tag == "rect":
        return (f("x"), f("y"), f("x") + f("width"), f("y") + f("height"))
    if tag == "circle":
        return (f("cx") - f("r"), f("cy") - f("r"), f("cx") + f("r"), f("cy") + f("r"))
    if tag == "ellipse":
        return (f("cx") - f("rx"), f("cy") - f("ry"), f("cx") + f("rx"), f("cy") + f("ry"))
    if tag == "polygon":
        pts = [tuple(map(float, p.split(","))) for p in el.get("points").split()]
        xs, ys = zip(*pts)
        return (min(xs), min(ys), max(xs), max(ys))
    if tag == "text":
        s, size = el.text or "", f("font-size", 3)
        w = tw(s, size)
        anchor = el.get("text-anchor", "start")
        x0 = f("x") - w * {"start": 0, "middle": 0.5, "end": 1}[anchor]
        return (x0, f("y") - size * 0.85, x0 + w, f("y") + size * 0.15)
    return None


def overlap(a, b):
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return dx * dy if dx > 0 and dy > 0 else 0.0


def seg_hits_bbox(x1, y1, x2, y2, bb, n=24):
    for i in range(1, n):
        t = i / n
        x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        if bb[0] < x < bb[2] and bb[1] < y < bb[3]:
            return True
    return False


def check_svg(spec, svg_path, errors, warnings, checks, defects):
    root = ET.parse(svg_path).getroot()
    vb = [float(v) for v in root.get("viewBox").split()]
    W, H = vb[2], vb[3]
    all_ids = {el.get("id") for el in root.iter() if el.get("id")}
    required = [e["id"] for e in spec["entities"]] + [r["id"] for r in spec.get("relations", [])]
    for c in spec.get("charts", []):
        required.append(c["id"])
        required += [f"{c['id']}-{s['id']}" for s in c["series"]]
    missing = [i for i in required if i not in all_ids]
    if missing:
        errors.append(f"SVG missing elements: {missing}")
    checks["svg_required_elements"] = len(required)
    checks["svg_missing_elements"] = len(missing)
    overflow, small = 0, 0
    texts, ents, rels = [], [], []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        f = lambda k, d=0.0: float(el.get(k, d))
        if tag == "rect":
            if f("x") < -0.1 or f("y") < -0.1 or f("x") + f("width") > W + 0.1 or f("y") + f("height") > H + 0.1:
                overflow += 1
        elif tag == "circle":
            if f("cx") - f("r") < -0.1 or f("cx") + f("r") > W + 0.1 or f("cy") - f("r") < -0.1 or f("cy") + f("r") > H + 0.1:
                overflow += 1
        elif tag == "text":
            if not (0 <= f("x") <= W and 0 <= f("y") <= H):
                overflow += 1
            if f("font-size", 99) < MIN_FONT:
                small += 1
            if (el.text or "").strip():
                texts.append((el.get("id") or f"text@{f('x'):.0f},{f('y'):.0f}", bbox_of(el)))
        elif tag == "line":
            for k in ("x1", "x2"):
                if not (0 <= f(k) <= W):
                    overflow += 1
            for k in ("y1", "y2"):
                if not (0 <= f(k) <= H):
                    overflow += 1
            if el.get("data-type"):
                rels.append(("line", el))
        elif tag == "polyline":
            pts = [tuple(map(float, p.split(","))) for p in el.get("points").split()]
            if any(not (0 <= px <= W and 0 <= py <= H) for px, py in pts):
                overflow += 1
            if el.get("data-type"):
                rels.append(("polyline", el))
        if el.get("data-kind") and not el.get("data-unit") and el.get("id"):
            ents.append((el.get("id"), bbox_of(el)))
    if overflow:
        errors.append(f"{overflow} element(s) outside canvas")
    if small:
        errors.append(f"{small} text element(s) below min font {MIN_FONT}mm")
    checks["canvas_overflow"] = overflow
    checks["min_font_mm"] = MIN_FONT
    # legend <-> groups (by key, with data-color)
    legend_ok = True
    for gk, g in spec.get("groups", {}).items():
        el = root.find(f".//*[@id='legend-{gk}']")
        if el is None or el.get("fill") != g["color"] or el.get("data-color") != g["color"]:
            legend_ok = False
            errors.append(f"legend swatch missing/mismatched for group {gk} ({g['color']})")
    checks["legend_matches_groups"] = legend_ok
    # exact value labels
    tset = {el.text for el in root.iter() if el.tag.split("}")[-1] == "text"}
    bad_vals = [f"{c['id']}-{s['id']}={s['value']}" for c in spec.get("charts", [])
                for s in c["series"] if fmt(s["value"]) not in tset]
    if bad_vals:
        errors.append(f"value labels missing/inexact: {bad_vals}")
    checks["value_labels_exact"] = not bad_vals
    # provenance attrs
    no_src = [i for i in required if i in all_ids
              and root.find(f".//*[@id='{i}']") is not None
              and not root.find(f".//*[@id='{i}']").get("data-source")]
    if no_src:
        warnings.append(f"elements without data-source attr: {no_src}")
    checks["elements_with_data_source"] = len(required) - len(no_src)
    # --- geometry defect detection ---
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            ov = overlap(a[1], b[1])
            if ov > 0.3:
                defects.append({"type": "text_collision", "elements": [a[0], b[0]],
                                "overlap_mm2": round(ov, 2),
                                "suggestion": "shorten one label in the spec, or move an entity slot / panel grid position"})
    for tid, tb in texts:
        for eid, eb in ents:
            if tid.startswith(eid):
                continue
            ov = overlap(tb, eb)
            if ov > 0.5:
                defects.append({"type": "text_over_entity", "elements": [tid, eid],
                                "overlap_mm2": round(ov, 2),
                                "suggestion": f"shorten '{tid}' text or relocate entity '{eid}' slot"})
    for kind, rel in rels:
        if kind == "line":
            f = lambda k: float(rel.get(k))
            segs = [(f("x1"), f("y1"), f("x2"), f("y2"))]
        else:
            pts = [tuple(map(float, p.split(","))) for p in rel.get("points").split()]
            segs = [(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:])]
        for eid, eb in ents:
            if eid in (rel.get("data-from"), rel.get("data-to")):
                continue
            if any(seg_hits_bbox(*sg, eb) for sg in segs):
                defects.append({"type": "line_pierces_entity", "elements": [rel.get("id"), eid],
                                "suggestion": f"reorder slots so '{eid}' is not on the route of '{rel.get('id')}'"})
    hard = [d for d in defects if d["type"] in ("text_collision", "text_over_entity")]
    for d in hard:
        errors.append(f"{d['type']}: {d['elements']}")
    for d in defects:
        if d["type"] == "line_pierces_entity":
            warnings.append(f"line_pierces_entity: {d['elements']}")
    checks["geometry_defects"] = len(defects)
    checks["editable_layers"] = [g.get("id") for g in root.findall("{http://www.w3.org/2000/svg}g")]
    checks["text_elements_editable"] = sum(1 for el in root.iter() if el.tag.split("}")[-1] == "text")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--svg")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    errors, warnings, checks, defects = [], [], {}, []
    check_spec(spec, errors, warnings, checks)
    if a.svg and not errors:
        check_svg(spec, a.svg, errors, warnings, checks, defects)
    report = {"passed": not errors, "stage": "post-render" if a.svg else "pre-render",
              "errors": errors, "warnings": warnings, "checks": checks, "defects": defects}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()