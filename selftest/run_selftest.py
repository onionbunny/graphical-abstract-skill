#!/usr/bin/env python3
"""One-command regression suite for the graphical-abstract skill.
SYNTHETIC cases only (fictional materials + gold specs) — NOT formal case answers.
Checks per case: determinism, validation, SVG<->spec round-trip fidelity,
byte-identical re-render, and data-ingestion agreement with the gold chart.
Usage: python3 selftest/run_selftest.py [--export]
"""
import argparse, hashlib, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
PY = sys.executable


def run(script, *args):
    r = subprocess.run([PY, os.path.join(SCRIPTS, script)] + list(args),
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def check_case(case_dir, tmp, do_export):
    name = os.path.basename(case_dir)
    gold = os.path.join(case_dir, "spec_gold.json")
    results = {}
    canon = os.path.join(tmp, f"{name}_canon.json")
    run("canonicalize_spec.py", "--spec", gold, "--out", canon)
    svg1, svg2 = os.path.join(tmp, f"{name}_1.svg"), os.path.join(tmp, f"{name}_2.svg")
    run("render_svg.py", "--spec", canon, "--out", svg1)
    run("render_svg.py", "--spec", canon, "--out", svg2)
    results["determinism"] = sha(svg1) == sha(svg2)
    val = os.path.join(tmp, f"{name}_val.json")
    rc, out, err = run("validate_figure.py", "--spec", canon, "--svg", svg1, "--out", val)
    results["validation"] = rc == 0
    rt = os.path.join(tmp, f"{name}_rt.json")
    run("svg_to_spec.py", "--svg", svg1, "--out", rt)
    drep = os.path.join(tmp, f"{name}_diff.json")
    run("diff_spec.py", "--a", canon, "--b", rt, "--out", drep)
    d = json.load(open(drep, encoding="utf-8"))
    results["roundtrip_zero_diff"] = not (d["added"] or d["removed"] or d["changed"])
    svg3 = os.path.join(tmp, f"{name}_3.svg")
    run("render_svg.py", "--spec", rt, "--out", svg3)
    results["roundtrip_byte_identical"] = sha(svg1) == sha(svg3)
    data = os.path.join(case_dir, "data.csv")
    if os.path.isfile(data):
        frag_path = os.path.join(tmp, f"{name}_frag.json")
        g = json.load(open(gold, encoding="utf-8"))["charts"][0]
        rc, out, err = run("ingest_data.py", "--file", data, "--id", g["id"],
                           "--panel", g["panel"], "--title", g["title"],
                           "--unit", g["unit"], "--scale-max", str(g["scale"]["max"]),
                           "--out", frag_path)
        ok = rc == 0
        if ok:
            frag = json.load(open(frag_path, encoding="utf-8"))["chart"]
            gv = sorted((s["label"], s["value"]) for s in g["series"])
            fv = sorted((s["label"], s["value"]) for s in frag["series"])
            ok = gv == fv
        results["ingest_matches_gold"] = ok
    if do_export:
        rc, out, err = run("export_figure.py", "--svg", svg1, "--outdir", tmp,
                           "--basename", name, "--dpi", "300")
        results["export"] = rc == 0
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    a = ap.parse_args()
    cases = sorted(d for d in os.listdir(HERE)
                   if os.path.isfile(os.path.join(HERE, d, "spec_gold.json")))
    all_ok = True
    with tempfile.TemporaryDirectory() as tmp:
        for c in cases:
            res = check_case(os.path.join(HERE, c), tmp, a.export)
            ok = all(res.values())
            all_ok &= ok
            print(f"[{'PASS' if ok else 'FAIL'}] {c}: " +
                  ", ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in res.items()))
    print("ALL PASS" if all_ok else "FAILURES PRESENT")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()