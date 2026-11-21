#!/usr/bin/env python3
"""Assemble /app/output/result.json: merges the case output_contract fields
(agent-authored result_fields.json) with mechanical evidence (spec provenance,
validation report, export report). Honest status; never invents missing data.
"""
import argparse, json, os, sys


def load(p):
    if p and os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, help="/input/case.json")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--fields", required=True, help="agent-authored result_fields.json")
    ap.add_argument("--svg", required=True)
    ap.add_argument("--png")
    ap.add_argument("--pdf")
    ap.add_argument("--validation", required=True)
    ap.add_argument("--export-report")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    case = load(a.case) or {}
    spec = load(a.spec) or {}
    fields = load(a.fields) or {}
    val = load(a.validation) or {}
    exp = load(a.export_report) or {}
    case_id = case.get("case_id") or spec.get("case_id") or "unknown"
    contract = case.get("output_contract", {})
    contract_keys = list(contract.keys()) if isinstance(contract, dict) else (
        contract if isinstance(contract, list) else [])
    missing_fields = [k for k in contract_keys if k not in fields]
    prov = {}
    for o in spec.get("entities", []) + spec.get("relations", []) + spec.get("charts", []):
        prov[o["id"]] = o.get("source", {})
    if spec.get("conclusion"):
        prov["conclusion"] = spec["conclusion"].get("source", {})
    exports_ok = bool(exp) and not exp.get("failed", True)
    svg_ok = os.path.isfile(a.svg)
    # claim audit: every entity/relation/value/conclusion -> claim + quote + verdict
    elabel = {e["id"]: e["label"] for e in spec.get("entities", [])}
    verdicts = fields.get("audit_verdicts", {})
    audit = []
    def row(cid, claim, src):
        audit.append({"id": cid, "claim": claim, "source": src,
                      "verdict": verdicts.get(cid, "unverified")})
    for e in spec.get("entities", []):
        row(e["id"], f"{e['label']} ({e['kind']}) is part of this study", e.get("source", {}))
    for r in spec.get("relations", []):
        lbl = f" [{r['label']}]" if r.get("label") else ""
        row(r["id"], f"{elabel.get(r['from'], r['from'])} {r['type']} {elabel.get(r['to'], r['to'])}{lbl}",
            r.get("source", {}))
    for c in spec.get("charts", []):
        for s in c.get("series", []):
            err = f" +/- {s['error']}" if s.get("error") is not None else ""
            row(f"{c['id']}/{s['id']}",
                f"{c.get('title', '')}: {s['label']} = {s['value']}{err} {c['unit']}", c.get("source", {}))
    if spec.get("conclusion"):
        row("conclusion", spec["conclusion"]["text"], spec["conclusion"].get("source", {}))
    unverified = [r["id"] for r in audit if r["verdict"] == "unverified"]
    contradicted = [r["id"] for r in audit if r["verdict"] == "contradicted"]
    if svg_ok and exports_ok and val.get("passed") and not missing_fields and not unverified and not contradicted:
        status = "complete"
    elif svg_ok:
        status = "partial"
    else:
        status = "failed"
    result = dict(fields)  # output_contract fields first, verbatim
    result.update({
        "case_id": case_id,
        "status": status,
        "artifacts": {
            "editable_source": a.svg if svg_ok else None,
            "png_preview": a.png if a.png and os.path.isfile(a.png) else None,
            "pdf_preview": a.pdf if a.pdf and os.path.isfile(a.pdf) else None,
            "figure_spec": a.spec,
        },
        "source_map": prov,
        "uncertainties": spec.get("uncertainties", []) + fields.get("extra_uncertainties", []),
        "off_figure_notes": spec.get("off_figure_notes", []),
        "validation": val,
        "export_checks": exp,
        "claim_audit": audit,
        "change_log": fields.get("change_log", []),
        "limits": fields.get("limits", []),
        "missing_output_contract_fields": missing_fields,
        "skill_version": "graphical-abstract/1.0",
    })
    if missing_fields:
        result["limits"].append(f"output_contract fields not filled: {missing_fields}")
    if unverified:
        result["limits"].append(f"claim_audit rows without verdict (fill audit_verdicts): {unverified}")
    if contradicted:
        result["limits"].append(f"claim_audit rows CONTRADICTED by source — fix figure: {contradicted}")
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"OK {a.out} status={status}")
    if missing_fields:
        print(f"WARNING missing contract fields: {missing_fields}")


if __name__ == "__main__":
    main()