#!/usr/bin/env python3
"""Ingest real source data (CSV/XLSX) into a chart fragment for figure_spec.json.
Cell-level provenance: every value carries file + sheet!cell / row,col + raw quote.
The LLM must NOT transcribe numbers by hand when a data file exists — use this.
Long layout: header row with columns label,value,group[,error][,category]
(case-insensitive; extra columns ignored). Stdlib only (xlsx = zip of XML).
"""
import argparse, csv, json, re, sys, zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
COLS = ("label", "value", "group", "error", "category")


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    return "CSV", rows, [f"row {i + 1}" for i in range(len(rows))]


def col_letters(ref):
    return re.match(r"[A-Z]+", ref).group(0)


def read_xlsx(path, sheet_name=None):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid2target = {rel.get("Id"): rel.get("Target") for rel in rels}
    sheets = [(s.get("name"), rid2target[s.get("{%s}id" % NS["r"])]) for s in wb.find("m:sheets", NS)]
    name, target = sheets[0]
    if sheet_name:
        match = [s for s in sheets if s[0] == sheet_name]
        if not match:
            raise SystemExit(f"sheet '{sheet_name}' not found; available: {[s[0] for s in sheets]}")
        name, target = match[0]
    t = target.lstrip("/")
    target = t if t.startswith("xl/") else "xl/" + t
    ws = ET.fromstring(z.read(target))
    grid, rownums = {}, []
    for row in ws.iter("{%s}row" % NS["m"]):
        rn = int(row.get("r"))
        rownums.append(rn)
        for cell in row.findall("m:c", NS):
            ref = cell.get("r")
            v = cell.find("m:v", NS)
            if cell.get("t") == "inlineStr":
                txt = "".join(t.text or "" for t in cell.iter("{%s}t" % NS["m"]))
            elif v is None or v.text is None:
                txt = ""
            elif cell.get("t") == "s":
                txt = shared[int(v.text)]
            else:
                txt = v.text
            grid[(rn, col_letters(ref))] = (txt, f"{name}!{ref}")
    maxrow = max(rownums) if rownums else 0
    letters = sorted({c for _, c in grid}, key=lambda s: (len(s), s))
    rows, locs = [], []
    for rn in range(1, maxrow + 1):
        rows.append([grid.get((rn, L), ("", f"{name}!{L}{rn}"))[0] for L in letters])
        locs.append({COLS[j] if j < len(COLS) else j: grid.get((rn, L), ("", f"{name}!{L}{rn}"))[1]
                     for j, L in enumerate(letters)})
    return name, rows, locs, letters


def nice_max(v):
    if v <= 0:
        return 1.0
    import math
    exp = math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if m * 10 ** exp >= v:
            return m * 10 ** exp
    return 10 ** (exp + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--sheet")
    ap.add_argument("--id", required=True)
    ap.add_argument("--panel", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--unit", required=True)
    ap.add_argument("--scale-max", type=float)
    ap.add_argument("--kind", choices=("bar", "line"), default="bar",
                    help="chart encoding emitted in the fragment")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    warnings = []
    if a.file.lower().endswith(".csv"):
        sheet, rows, _ = read_csv(a.file)
        locs = [{c: f"row {i + 1}, col '{h}'" for c, h in zip(COLS, rows[0])} for i in range(len(rows))]
        letters = None
    else:
        sheet, rows, locs, letters = read_xlsx(a.file, a.sheet)
    if not rows:
        raise SystemExit("empty data file")
    header = [h.strip().lower() for h in rows[0]]
    idx = {c: header.index(c) for c in COLS if c in header}
    if "label" not in idx or "value" not in idx or "group" not in idx:
        raise SystemExit(f"header must contain label,value,group; got {header}")
    series, values = [], []
    for ri, row in enumerate(rows[1:], start=2):
        if not any(v.strip() for v in row):
            continue
        raw = row[idx["value"]].strip()
        try:
            val = float(raw)
        except ValueError:
            warnings.append(f"row {ri}: value '{raw}' not numeric — skipped, NOT invented")
            continue
        loc = locs[ri - 1]
        if letters:  # xlsx: map by actual column letters
            vletter = letters[idx["value"]]
            vloc = f"{sheet}!{vletter}{ri}"
        else:
            vloc = loc.get("value", f"row {ri}")
        s = {"id": f"s{len(series) + 1}", "label": row[idx["label"]].strip(),
             "value": val, "group": row[idx["group"]].strip(),
             "source_cell": vloc, "raw_quote": raw}
        if "error" in idx and row[idx["error"]].strip():
            s["error"] = float(row[idx["error"]])
        if "category" in idx and row[idx["category"]].strip():
            s["category"] = row[idx["category"]].strip()
        series.append(s)
        values.append(val + s.get("error", 0))
    if not series:
        raise SystemExit("no usable data rows")
    smax = a.scale_max if a.scale_max else nice_max(max(values))
    cells = "; ".join(f'{s["label"]}={s["raw_quote"]}@{s["source_cell"]}' for s in series)
    chart = {"id": a.id, "panel": a.panel, "kind": a.kind, "title": a.title,
             "unit": a.unit, "scale": {"min": 0, "max": smax},
             "series": [{k: v for k, v in s.items() if k not in ("source_cell", "raw_quote")} for s in series],
             "source": {"file": a.file, "locator": cells, "quote": cells}}
    out = {"chart": chart, "ingest_warnings": warnings,
           "cell_provenance": [{"series_id": s["id"], "cell": s["source_cell"], "raw": s["raw_quote"]} for s in series]}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"OK ingested {len(series)} series from {a.file} [{sheet}] -> {a.out}; scale max={smax}")
    for w in warnings:
        print("WARNING:", w)


if __name__ == "__main__":
    main()