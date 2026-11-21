---
name: graphical-abstract
description: Source-bound scientific Graphical Abstract generation and editing. Use when the task asks to create or edit a graphical abstract, mechanism diagram, pathway figure, or single-page research summary (question-methods-results-conclusion) from papers, lab records, or case materials, and requires editable SVG/PNG/PDF outputs with provenance. Triggers include graphical_abstract workorders, /input/case.json + task.md harness cases, and requests for 图形摘要/机制图/科研示意图 with editable source files and export checks.
---

# Graphical Abstract — source-bound, deterministic, editable

Produce a single-page graphical abstract where every entity, relation and number
traces back to the input materials, the same input reproduces a structurally
identical figure, and the deliverable is a layered editable SVG plus PNG/PDF exports.

**Division of labor (do not violate):** the LLM does scientific extraction and
judgement (materials → `figure_spec.json`); Python scripts do all layout, rendering,
export and checking. Never hand-draw coordinates, never let a generative image model
draw scientific text/data, never bypass the validator.

## Runtime contract (harness cases)

- Inputs: `/input/case.json` (contains `case_id`, `output_contract`) and `/input/task.md`,
  plus material files under `/input`. Read the actual files; never trust labels.
- Work dir: `/app/work` (spec, reports, intermediate files).
- Final dir: `/app/output` — must contain `graphical_abstract.svg` (editable source),
  `graphical_abstract.png` (300 dpi preview), `graphical_abstract.pdf`,
  `figure_spec.json`, `validation_report.json`, `export_report.json`, `result.json`.
- `result.json` must contain `case_id` and every `output_contract` field, plus honest
  status / sources / uncertainties / change_log. Save a partial result early, then improve.
- If `environment/resources.yaml` exists, read it first for preinstalled tools.

## Workflow (follow in order)

1. **Read inputs.** Parse `case.json` (note `case_id` and `output_contract` keys) and
   `task.md`. List and actually read every material file. PDF: `pdftotext -layout` or
   pypdf; render key PDF pages with `pdftoppm` and view them. Follow the task's declared
   primary source when materials conflict.
2. **Ingest real data first.** If the case provides CSV/XLSX source data, NEVER transcribe
   numbers by hand. Run:
   `python3 {skill_dir}/scripts/ingest_data.py --file <data> --id c1 --panel p3 --title "..." --unit "..." --out /app/work/chart_frag.json`
   (long layout: label,value,group[,error][,category]; xlsx needs no extra deps). Add
   `--kind line` for dose-response/time-series curves; default is bar.
   Merge the returned `chart` into the spec; keep `cell_provenance` for result.json.
3. **Extract.** Read `references/drawing_rules.md` fully. Build the panel–point mapping
   (question / methods / results / conclusion), then write `/app/work/figure_spec.json`
   following `references/spec_schema.md` exactly. Every entity/relation/chart/conclusion
   needs `source {file, locator, quote}` with a verbatim snippet. Numbers only from the
   materials or ingested data; missing data → `uncertainties`, never invented. Verify each
   relation's direction against its quote (watch passive voice). Then canonicalize:
   `python3 {skill_dir}/scripts/canonicalize_spec.py --spec /app/work/figure_spec.json --out /app/work/figure_spec.json`
4. **Pre-validate.**
   `python3 {skill_dir}/scripts/validate_figure.py --spec /app/work/figure_spec.json --out /app/work/validation_report.json`
   Fix all errors before rendering. Warnings: resolve or record in uncertainties.
5. **Render.**
   `python3 {skill_dir}/scripts/render_svg.py --spec /app/work/figure_spec.json --out /app/output/graphical_abstract.svg`
   Deterministic: identical spec → identical SVG. Layout, legend, badges, wrapping,
   cross-panel orthogonal arrow routing are automatic; do not edit coordinates by hand.
6. **Export.**
   `python3 {skill_dir}/scripts/export_figure.py --svg /app/output/graphical_abstract.svg --outdir /app/output --dpi 300`
   If all engines fail: `python3 -m pip install cairosvg` (or `pip install pymupdf`,
   which needs no system libraries) then retry. Still failing →
   keep SVG, report honestly in export_report.json (already written by the script).
7. **Post-validate + defect loop.** Re-run step 4 with `--svg /app/output/graphical_abstract.svg`.
   The report's `defects` list gives deterministic geometry findings (text_collision,
   text_over_entity, line_pierces_entity) each with a spec-level fix suggestion.
   Apply the suggested spec change, re-render, re-validate until zero errors.
8. **Visual self-check.** Open the PNG preview and inspect: reading order ①→④,
   arrow directions, legend correctness, glyph substitution. Fix problems by editing
   the spec and re-running steps 5–7. Record each iteration in change_log.
9. **Assemble result.** Copy `figure_spec.json` to `/app/output/`. Write
   `/app/work/result_fields.json`: fill EVERY `output_contract` field from case.json
   with real content, plus `change_log` (list of {step, change, reason}), `limits`,
   and `audit_verdicts` — for EVERY claim id listed by make_result (entities, relations,
   chart series as `c1/s1`, conclusion) set `confirmed` / `uncertain` / `contradicted`
   after re-reading the source quote. `complete` status requires full verdict coverage;
   `contradicted` claims must be fixed in the figure, not just reported. Then:
   ```
   python3 {skill_dir}/scripts/make_result.py --case /input/case.json \
     --spec /app/output/figure_spec.json --fields /app/work/result_fields.json \
     --svg /app/output/graphical_abstract.svg --png /app/output/graphical_abstract.png \
     --pdf /app/output/graphical_abstract.pdf --validation /app/output/validation_report.json \
     --export-report /app/output/export_report.json --out /app/output/result.json
   ```
   Status is computed honestly (complete / partial / failed). Partial results must say
   what is missing and why.

## Editing an existing figure (source-preserving, minimal-change)

1. Reconstruct the spec from the SVG (works even for hand-edited SVGs — semantic
   data-* attributes carry structure, DOM text carries label edits):
   `python3 {skill_dir}/scripts/svg_to_spec.py --svg <figure.svg> --out /app/work/spec_before.json`
2. Apply ONLY the requested change to the spec (or accept the hand edit already in the SVG).
3. Produce a minimal-change evidence report:
   `python3 {skill_dir}/scripts/diff_spec.py --a spec_before.json --b spec_after.json --out /app/output/edit_diff.json`
   Append its added/removed/changed summary to change_log. Untouched elements must stay
   byte-identical after re-render (the renderer is deterministic).
4. Re-render, re-export, re-validate (steps 5–7). Never flatten to raster-only; the SVG
   remains the canonical editable source (layers: background/panels/charts/relations/
   entities/labels/legend; all text is real `<text>`).

## Repetition-consistency evidence

When asked to prove stability across runs: canonicalize each run's spec, then
`diff_spec.py --a run1.json --b run2.json` — report `structural_similarity` and
`identical_structure` in result.json. Identical specs render byte-identical SVGs.

## Failure handling

See the table in `references/drawing_rules.md` §7. Key rules: missing numbers → degrade
to qualitative relation + uncertainty; export failure → engine fallback chain, then
honest partial; unreadable material → failed status with file-level reason; canvas/font
errors → fix spec, never shrink fonts below 2.2 mm or draw outside the canvas.

## Resources

- `references/spec_schema.md` — the figure_spec.json contract (read before extraction).
- `references/drawing_rules.md` — extraction, direction, encoding, layout, failure rules.
- `assets/palettes.json` — Okabe-Ito colorblind-safe palette + role colors.
- `assets/example_spec.json` — minimal EXAMPLE spec (fictional data, interface demo only;
  never reuse its content in real cases).
- `scripts/` — render_svg.py, validate_figure.py (incl. geometry defect detection),
  export_figure.py, make_result.py (claim audit), ingest_data.py (CSV/XLSX cell-level
  provenance), svg_to_spec.py + diff_spec.py (source-preserving edit loop),
  canonicalize_spec.py (repetition stability).
  Python 3.8+, stdlib only except export (engine chain: cairosvg → pymupdf →
  rsvg-convert → inkscape; pymupdf is pip-installable with no system dependencies).
- `selftest/run_selftest.py` — one-command regression over synthetic cases
  (determinism / validation / round-trip / ingest agreement / export). Synthetic only;
  never reuse its content as a formal case answer.

## Minimal example (illustrative, not a formal case)

```
python3 scripts/validate_figure.py --spec assets/example_spec.json --out /tmp/val.json
python3 scripts/render_svg.py --spec assets/example_spec.json --out /tmp/ga.svg
python3 scripts/export_figure.py --svg /tmp/ga.svg --outdir /tmp --dpi 300
python3 scripts/validate_figure.py --spec assets/example_spec.json --svg /tmp/ga.svg --out /tmp/val.json
```
Expected: a 180×120 mm 2×2 figure (question/methods/results/conclusion), GPX4-inhibition
mechanism with a T-bar inhibitor arrow, a 2-bar viability chart (92.1 vs 41.3 %), auto
legend, and a passing validation report.