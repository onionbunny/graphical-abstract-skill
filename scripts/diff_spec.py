#!/usr/bin/env python3
"""Structural diff between two figure specs.
Uses: (a) edit change reports (source-preserving editing evidence),
(b) repetition-consistency evidence across repeated runs.
Outputs diff_report.json with per-element changes and a structural similarity score.
"""
import argparse, json


def index(spec):
    idx = {}
    for p in spec.get("panels", []):
        idx[("panel", p["id"])] = p
    for e in spec.get("entities", []):
        idx[("entity", e["id"])] = e
    for r in spec.get("relations", []):
        idx[("relation", r["id"])] = r
    for c in spec.get("charts", []):
        idx[("chart", c["id"])] = {k: v for k, v in c.items() if k != "series"}
        for s in c.get("series", []):
            idx[("series", c["id"] + "/" + s["id"])] = s
    for k, g in spec.get("groups", {}).items():
        idx[("group", k)] = g
    if spec.get("conclusion"):
        idx[("conclusion", "conclusion")] = spec["conclusion"]
    return idx


def field_diff(a, b):
    keys = sorted(set(a) | set(b))
    return {k: {"old": a.get(k), "new": b.get(k)} for k in keys if a.get(k) != b.get(k)}


def structure(spec):
    """Semantic skeleton: relation triples + data values + entity kinds/panels."""
    sk = set()
    for e in spec.get("entities", []):
        sk.add(("E", e["panel"], e["kind"], e["label"]))
    for r in spec.get("relations", []):
        sk.add(("R", r["from"], r["type"], r["to"]))
    for c in spec.get("charts", []):
        for s in c.get("series", []):
            sk.add(("D", c["id"], s["label"], s["value"], s.get("category", "")))
    return sk


def diff(sa, sb):
    ia, ib = index(sa), index(sb)
    added = [list(k) for k in ib if k not in ia]
    removed = [list(k) for k in ia if k not in ib]
    changed = []
    for k in ia:
        if k in ib:
            fd = field_diff(ia[k], ib[k])
            if fd:
                changed.append({"element": list(k), "fields": fd})
    ska, skb = structure(sa), structure(sb)
    union = ska | skb
    sim = len(ska & skb) / len(union) if union else 1.0
    return {"added": added, "removed": removed, "changed": changed,
            "structural_similarity": round(sim, 4),
            "identical_structure": ska == skb,
            "n_elements_a": len(ia), "n_elements_b": len(ib)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-changed", type=int, default=-1,
                    help="exit 1 if more than N elements changed (regression gate)")
    args = ap.parse_args()
    sa = json.load(open(args.a, encoding="utf-8"))
    sb = json.load(open(args.b, encoding="utf-8"))
    rep = diff(sa, sb)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"added={len(rep['added'])} removed={len(rep['removed'])} "
          f"changed={len(rep['changed'])} structural_similarity={rep['structural_similarity']}")
    if args.max_changed >= 0 and len(rep["changed"]) + len(rep["added"]) + len(rep["removed"]) > args.max_changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()