#!/usr/bin/env python3
"""Canonicalize a figure spec so repeated extractions converge:
stable ordering, whitespace normalization, explicit defaults.
Never renames ids (provenance stability) and never alters scientific content.
"""
import argparse, json, re


def clean(o):
    if isinstance(o, str):
        return re.sub(r"\s+", " ", o).strip()
    if isinstance(o, list):
        return [clean(v) for v in o]
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    return o


def canonicalize(spec):
    s = clean(spec)
    s.setdefault("spec_version", "1.0")
    cv = s.setdefault("canvas", {})
    cv.setdefault("width_mm", 180); cv.setdefault("height_mm", 120); cv.setdefault("dpi", 300)
    s["panels"] = sorted(s.get("panels", []), key=lambda p: (p["grid"][0], p["grid"][1], p["id"]))
    s["entities"] = sorted(s.get("entities", []), key=lambda e: (e["panel"], e["slot"][0], e["slot"][1], e["id"]))
    s["relations"] = sorted(s.get("relations", []), key=lambda r: (r["from"], r["to"], r["type"], r["id"]))
    s["charts"] = sorted(s.get("charts", []), key=lambda c: (c["panel"], c["id"]))
    for c in s["charts"]:
        c["series"] = sorted(c.get("series", []),
                             key=lambda x: (x.get("category", ""), x.get("group", ""), x["label"], x["id"]))
    s["groups"] = {k: s["groups"][k] for k in sorted(s.get("groups", {}))}
    s.setdefault("uncertainties", [])
    s.setdefault("off_figure_notes", [])
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    out = canonicalize(spec)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    changed = json.dumps(spec, sort_keys=True) != json.dumps(out, sort_keys=True)
    print(f"OK canonicalized -> {a.out} (reordered/normalized: {changed})")


if __name__ == "__main__":
    main()