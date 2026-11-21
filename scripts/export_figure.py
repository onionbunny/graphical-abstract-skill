#!/usr/bin/env python3
"""Export SVG -> PNG (target dpi) + PDF, with engine fallback and honest checks.
Engine chain: cairosvg (python) -> rsvg-convert -> inkscape.
Writes export_report.json. Never fakes success: failures are recorded.
"""
import argparse, json, os, shutil, struct, subprocess, sys


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def try_cairosvg(svg, png, pdf, width_px):
    import cairosvg
    cairosvg.svg2png(url=svg, write_to=png, output_width=width_px)
    cairosvg.svg2pdf(url=svg, write_to=pdf)
    return "cairosvg"


def try_pymupdf(svg, png, pdf, dpi):
    import pymupdf
    doc = pymupdf.open(svg)
    pdfbytes = doc.convert_to_pdf()
    out = pymupdf.open("pdf", pdfbytes)
    out.save(pdf)
    page = out[0]
    page.get_pixmap(dpi=dpi).save(png)
    return "pymupdf"


def try_rsvg(svg, png, pdf, width_px, dpi):
    exe = shutil.which("rsvg-convert")
    if not exe:
        raise RuntimeError("rsvg-convert not found")
    subprocess.run([exe, "-w", str(width_px), "-o", png, svg], check=True)
    subprocess.run([exe, "-f", "pdf", "--dpi-x", str(dpi), "--dpi-y", str(dpi),
                    "-o", pdf, svg], check=True)
    return "rsvg-convert"


def try_inkscape(svg, png, pdf, dpi):
    exe = shutil.which("inkscape")
    if not exe:
        raise RuntimeError("inkscape not found")
    subprocess.run([exe, svg, "--export-type=png", f"--export-dpi={dpi}",
                    f"--export-filename={png}"], check=True)
    subprocess.run([exe, svg, "--export-type=pdf",
                    f"--export-filename={pdf}"], check=True)
    return "inkscape"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--basename", default="graphical_abstract")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    png = os.path.join(a.outdir, a.basename + ".png")
    pdf = os.path.join(a.outdir, a.basename + ".pdf")
    rep = os.path.join(a.outdir, "export_report.json")
    # read canvas mm from svg width attr
    with open(a.svg, encoding="utf-8") as f:
        head = f.read(2000)
    import re
    mw = re.search(r'width="([\d.]+)mm"', head)
    mh = re.search(r'height="([\d.]+)mm"', head)
    wmm = float(mw.group(1)) if mw else 180.0
    hmm = float(mh.group(1)) if mh else 120.0
    width_px = round(wmm / 25.4 * a.dpi)
    height_px = round(hmm / 25.4 * a.dpi)
    report = {"engine": None, "attempts": [], "dpi": a.dpi,
              "target_px": [width_px, height_px], "canvas_mm": [wmm, hmm],
              "png": None, "pdf": None, "checks": {}, "failed": False}
    for fn, args in ((try_cairosvg, (a.svg, png, pdf, width_px)),
                     (try_pymupdf, (a.svg, png, pdf, a.dpi)),
                     (try_rsvg, (a.svg, png, pdf, width_px, a.dpi)),
                     (try_inkscape, (a.svg, png, pdf, a.dpi))):
        try:
            report["engine"] = fn(*args)
            break
        except Exception as ex:
            report["attempts"].append({"engine": fn.__name__, "error": str(ex)[:300]})
    if report["engine"]:
        ok_png = os.path.isfile(png) and os.path.getsize(png) > 0
        ok_pdf = os.path.isfile(pdf) and open(pdf, "rb").read(5) == b"%PDF-"
        dims = png_size(png) if ok_png else None
        report["png"] = png if ok_png else None
        report["pdf"] = pdf if ok_pdf else None
        report["checks"] = {
            "png_exists": ok_png, "pdf_exists": ok_pdf,
            "png_dims": dims,
            "png_dims_match_target": (abs(dims[0] - width_px) <= 2 and abs(dims[1] - height_px) <= 2) if dims else False,
            "dpi_target": a.dpi,
            "font_note": ("text kept editable in SVG source; raster/PDF rendering uses "
                          "system fonts matching 'DejaVu Sans, Arial, Helvetica, sans-serif'. "
                          "Inspect the PNG preview for glyph substitution (esp. CJK)."),
        }
        report["failed"] = not (ok_png and ok_pdf)
    else:
        report["failed"] = True
        report["checks"]["note"] = ("all export engines unavailable; SVG source preserved. "
                                    "Install one of: pip install cairosvg / pip install pymupdf / "
                                    "rsvg-convert / inkscape")
    with open(rep, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if not report["failed"] else 1)


if __name__ == "__main__":
    main()