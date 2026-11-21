#!/usr/bin/env python3
"""Reconstruct figure_spec.json from a rendered (or hand-edited) SVG.
Reads semantic data-* attributes for structure and DOM text for labels, so
manual text edits in Inkscape are captured. Round-trip guarantee:
render(spec) -> svg_to_spec -> render  is byte-identical for untouched SVGs.
"""
import argparse, json, re
import xml.etree.ElementTree as ET


def norm(s):
    return re.sub(r"\s+", "", s or "")


def num(x):
    f = float(x)
    return int(f) if f == int(f) else f


def texts(root, prefix):
    out = []
    for el in root.iter():
        eid = el.get("id", "")
        if el.tag.split("}")[-1] == "text" and re.fullmatch(re.escape(prefix) + r"\d+", eid):
            out.append((int(eid[len(prefix):]), el.text or ""))
    return " ".join(t.strip() for _, t in sorted(out))


def text_of(root, eid):
    el = root.find(f".//*[@id='{eid}']")
    return (el.text or "") if el is not None else ""


def label_of(root, el, prefix):
    """Prefer DOM text (captures hand edits); fall back to data-label for exact
    whitespace/CJK reconstruction when content is unchanged."""
    dom = texts(root, prefix)
    dl = el.get("data-label", "")
    if norm(dom) == norm(dl):
        return dl
    return dom or dl


def parse(svg_path):
    root = ET.parse(svg_path).getroot()
    meta = {}
    md = root.find(".//*[@id='provenance']")
    if md is not None and md.text:
        meta = json.loads(md.text)
    prov = meta.get("provenance", {})
    wmm = num(re.match(r"([\d.]+)", root.get("width")).group(1))
    hmm = num(re.match(r"([\d.]+)", root.get("height")).group(1))
    spec = {"spec_version": root.get("data-spec-version", "1.0"),
            "case_id": root.get("data-case-id", meta.get("case_id", "")),
            "title": text_of(root, "fig-title"),
            "canvas": {"width_mm": wmm, "height_mm": hmm,
                       "dpi": int(root.get("data-dpi", 300))}}
    spec["panels"], spec["entities"], spec["relations"] = [], [], []
    spec["charts"], spec["groups"] = [], {}
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        eid = el.get("id", "")
        if tag == "rect" and el.get("data-role"):
            r, c = el.get("data-grid").split(",")
            dom = texts(root, eid + "-title")
            role_prefix = {"question": "Question: ", "methods": "Methods: ",
                           "results": "Results: ", "conclusion": "Conclusion: "}[el.get("data-role")]
            dt = el.get("data-title", "")
            title = dt if norm(dom) == norm(role_prefix + dt) else dom.replace(role_prefix, "", 1)
            spec["panels"].append({"id": eid, "role": el.get("data-role"),
                                   "title": title, "grid": [int(r), int(c)]})
        elif el.get("data-kind") and not el.get("data-unit"):
            e = {"id": eid, "panel": el.get("data-panel"),
                 "label": label_of(root, el, eid + "-label"),
                 "kind": el.get("data-kind"),
                 "slot": [int(v) for v in el.get("data-slot").split(",")]}
            if el.get("data-group"):
                e["group"] = el.get("data-group")
            if eid in prov:
                e["source"] = prov[eid]
            spec["entities"].append(e)
        elif tag in ("line", "polyline") and el.get("data-type"):
            r = {"id": eid, "from": el.get("data-from"), "to": el.get("data-to"),
                 "type": el.get("data-type"), "label": text_of(root, eid + "-label")}
            if eid in prov:
                r["source"] = prov[eid]
            spec["relations"].append(r)
        elif tag == "g" and el.get("data-unit") is not None:
            c = {"id": eid, "panel": el.get("data-panel"), "kind": el.get("data-kind", "bar"),
                 "title": el.get("data-title", ""), "unit": el.get("data-unit"),
                 "scale": {"min": num(el.get("data-scale-min")),
                           "max": num(el.get("data-scale-max"))}, "series": []}
            dom = text_of(root, eid + "-title")
            if norm(dom) != norm(f'{c["title"]} ({c["unit"]})'):
                m = re.match(r"(.*)\s*\((.*)\)\s*$", dom)
                if m:
                    c["title"], c["unit"] = m.group(1).strip(), m.group(2)
            if eid in prov:
                c["source"] = prov[eid]
            if c.get("kind", "bar") == "line":
                for pt in el.iter():
                    if pt.tag.split("}")[-1] == "circle" and pt.get("data-value"):
                        sid = pt.get("id")[len(eid) + 1:]
                        s = {"id": sid, "label": pt.get("data-label", ""),
                             "value": num(pt.get("data-value")),
                             "group": pt.get("data-group")}
                        if pt.get("data-error"):
                            s["error"] = num(pt.get("data-error"))
                        c["series"].append(s)
            else:
                for bar in el.iter():
                    if bar.tag.split("}")[-1] == "rect" and bar.get("data-value"):
                        sid = bar.get("id")[len(eid) + 1:]
                        s = {"id": sid,
                             "label": label_of(root, bar, bar.get("id") + "-label"),
                             "value": num(bar.get("data-value")),
                             "group": bar.get("data-group")}
                        if bar.get("data-category"):
                            s["category"] = bar.get("data-category")
                        if bar.get("data-error"):
                            s["error"] = num(bar.get("data-error"))
                        c["series"].append(s)
            spec["charts"].append(c)
        elif tag == "rect" and eid.startswith("legend-") and el.get("data-color"):
            key = eid[len("legend-"):]
            dom = text_of(root, eid + "-text")
            dl = el.get("data-label", "")
            spec["groups"][key] = {"label": dl if norm(dom) == norm(dl) else dom,
                                   "color": el.get("data-color")}
    concl = texts(root, "conclusion-line")
    if concl:
        mt = meta.get("conclusion_text", "")
        spec["conclusion"] = {"text": mt if norm(concl) == norm(mt) else concl,
                              "source": prov.get("conclusion", {})}
    spec["uncertainties"] = meta.get("uncertainties", [])
    spec["off_figure_notes"] = meta.get("off_figure_notes", [])
    return spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    spec = parse(a.svg)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    print(f"OK reconstructed spec: {len(spec['entities'])} entities, "
          f"{len(spec['relations'])} relations, {len(spec['charts'])} charts -> {a.out}")


if __name__ == "__main__":
    main()