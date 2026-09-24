"""ReconResolve leadership deck (.pptx) — styled to match the Field-Eng "RCA Notebook &
skill" template (10x5.63, Barlow + DM Sans, red/ink/teal palette). Import into Google Slides.

Run:  python3 docs/build_deck.py  ->  docs/ReconResolve_Leadership.pptx
"""
from pptx import Presentation
from pptx.util import Inches as In, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
import os

# ---- template palette ----
RED  = RGBColor(0xFF, 0x36, 0x20)
INK  = RGBColor(0x1B, 0x30, 0x37)
TEAL = RGBColor(0x1B, 0x51, 0x61)
MUT  = RGBColor(0x61, 0x87, 0x93)
LMUT = RGBColor(0x9E, 0xB7, 0xBE)
DARK = RGBColor(0x1B, 0x30, 0x37)
DARK2= RGBColor(0x24, 0x42, 0x4B)
PANEL= RGBColor(0xF1, 0xF1, 0xF1)
PANEL2=RGBColor(0xF3, 0xF6, 0xF7)
GREEN= RGBColor(0x00, 0xB3, 0x78)
GOLD = RGBColor(0xFF, 0xAB, 0x00)
PURP = RGBColor(0x7E, 0x4C, 0xA8)
WHITE= RGBColor(0xFF, 0xFF, 0xFF)

HEAD = "Barlow"
BODY = "DM Sans"
MONO = "DM Sans"

prs = Presentation()
prs.slide_width = In(10); prs.slide_height = In(5.625)
BLANK = prs.slide_layouts[6]
SW = 10.0


def slide(bg=WHITE):
    s = prs.slides.add_slide(BLANK)
    r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, In(0), In(0), In(SW), In(5.625))
    r.fill.solid(); r.fill.fore_color.rgb = bg; r.line.fill.background(); r.shadow.inherit = False
    return s


def rect(s, l, t, w, h, fill=None, line=None, lw=1.0, shape=MSO_SHAPE.RECTANGLE, radius=0.08):
    sp = s.shapes.add_shape(shape, In(l), In(t), In(w), In(h))
    if fill is None: sp.fill.background()
    else: sp.fill.solid(); sp.fill.fore_color.rgb = fill
    if line is None: sp.line.fill.background()
    else: sp.line.color.rgb = line; sp.line.width = Pt(lw)
    sp.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try: sp.adjustments[0] = radius
        except Exception: pass
    return sp


def txt(s, l, t, w, h, runs, size=12, color=INK, bold=False, font=BODY, align=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.TOP, spacing=1.0, sa=3):
    tb = s.shapes.add_textbox(In(l), In(t), In(w), In(h)); tf = tb.text_frame
    tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = 0; tf.margin_top = tf.margin_bottom = 0
    if isinstance(runs, str): runs = [(runs, {})]
    p = tf.paragraphs[0]; p.alignment = align; p.line_spacing = spacing; p.space_after = Pt(sa)
    first = True
    for text, o in runs:
        if o.get("nl") and not first:
            p = tf.add_paragraph(); p.alignment = o.get("align", align)
            p.line_spacing = o.get("spacing", spacing); p.space_after = Pt(o.get("sa", sa))
        r = p.add_run(); r.text = text
        r.font.size = Pt(o.get("size", size)); r.font.bold = o.get("bold", bold)
        r.font.name = o.get("font", font); r.font.color.rgb = o.get("color", color)
        first = False
    return tb


def lines(items):
    return [(t, {**o, "nl": True}) for (t, o) in (i if isinstance(i, tuple) else (i, {}) for i in items)]


def chrome(s, eye, title, sub=None, title_size=26):
    rect(s, 0.6, 0.52, 0.55, 0.09, fill=RED)
    txt(s, 0.6, 0.64, 8.8, 0.3, [(eye.upper(), {"size": 12, "bold": True, "font": HEAD, "color": MUT})])
    txt(s, 0.6, 0.98, 8.9, 0.7, [(title, {"size": title_size, "bold": True, "font": HEAD, "color": INK})], spacing=1.0)
    if sub:
        txt(s, 0.6, 1.66, 8.9, 0.5, [(sub, {"size": 12.5, "font": BODY, "color": TEAL})], spacing=1.05)


def marker_head(s, l, t, w, text, mc=RED, tc=INK, size=13):
    rect(s, l, t + 0.05, 0.15, 0.15, fill=mc)
    txt(s, l + 0.28, t, w, 0.32, [(text, {"size": size, "bold": True, "font": HEAD, "color": tc})])


CHK = "✓  "

# ============================ 1 — TITLE ============================
s = slide(WHITE)
rect(s, 0.6, 1.5, 0.55, 0.09, fill=RED)
txt(s, 0.6, 1.72, 8.8, 1.0, [("ReconResolve", {"size": 40, "bold": True, "font": HEAD, "color": INK})])
txt(s, 0.6, 2.62, 8.8, 0.45, [("The 4th stage after Lakebridge: reconcile tells you ",
     {"size": 15, "font": BODY, "color": MUT}),
    ("what", {"size": 15, "font": BODY, "color": RED, "bold": True}),
    (" differs — ReconResolve tells you ", {"size": 15, "font": BODY, "color": MUT}),
    ("why", {"size": 15, "font": BODY, "color": RED, "bold": True}),
    (".", {"size": 15, "font": BODY, "color": MUT})], spacing=1.15)
txt(s, 0.6, 3.15, 8.8, 0.4, [("Deterministic + agentic root-cause analysis · App · CLI · Genie Code",
     {"size": 12.5, "font": BODY, "color": TEAL})])
steps = [("analyze", False), ("transpile", False), ("reconcile", False), ("RCA · ReconResolve", True)]
x = 0.6
for lbl, on in steps:
    w = 0.32 + 0.115 * len(lbl)
    rect(s, x, 4.15, w, 0.42, fill=(RED if on else PANEL), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5)
    txt(s, x, 4.15, w, 0.42, [(lbl, {"size": 11, "bold": on, "font": HEAD, "color": (WHITE if on else MUT)})],
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    x += w
    if lbl != "RCA · ReconResolve":
        txt(s, x, 4.15, 0.4, 0.42, [("→", {"size": 13, "color": LMUT})], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        x += 0.4
rect(s, 0.6, 4.95, 2.0, 0.36, fill=DARK, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.3)
txt(s, 0.6, 4.95, 2.0, 0.36, [("Field Engineering", {"size": 10, "bold": True, "font": HEAD, "color": LMUT})],
    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

# ============================ 2 — THE GAP ============================
s = slide(WHITE)
chrome(s, "The problem", "Between “the numbers don’t match” and a fix — a week of manual work", title_size=24)
gap = [("TODAY · LAKEBRIDGE RECONCILE", "A list of differences", RED,
        ["Reports WHICH columns / rows differ — e.g. unit_price differs on 1,844,309 of 2,000,000 rows",
         "Stops at the symptom: no mechanism, no source, no proof",
         "Engineer opens the ETL, hypothesizes, writes queries — days per table"], PANEL, INK, MUT),
       ("WITH RECONRESOLVE", "The mechanism, the culprit, the proof", GREEN,
        ["Category + exact migrated derivation + ⚠️ likely-culprit sub-expression",
         "The source script + a runnable confirming query + a suggested fix",
         "Reviewer-ready notebook in minutes — deterministic or agentic"], DARK, WHITE, LMUT)]
for i, (k, h, c, items, bg, tc, sc) in enumerate(gap):
    x = 0.6 + i * 4.55
    rect(s, x, 2.35, 4.25, 2.9, fill=bg, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    rect(s, x, 2.35, 0.08, 2.9, fill=c)
    txt(s, x + 0.32, 2.55, 3.8, 0.28, [(k, {"size": 9.5, "bold": True, "font": HEAD, "color": c})])
    txt(s, x + 0.32, 2.82, 3.8, 0.5, [(h, {"size": 16, "bold": True, "font": HEAD, "color": tc})], spacing=1.0)
    txt(s, x + 0.32, 3.5, 3.85, 1.6, lines([(CHK + it if bg == DARK else "•  " + it,
        {"size": 10.5, "color": sc, "sa": 6}) for it in items]), spacing=1.05)

# ============================ 3 — TWO TIERS ============================
s = slide(WHITE)
chrome(s, "How it works", "Two tiers — every verdict backed by a query, never a bare model guess", title_size=23)
tiers = [("TIER 1 · DETERMINISTIC", TEAL, PANEL, INK, TEAL, "Rule-based · query-confirmed · the default",
          ["Per-dialect probes classify the mechanism",
           "Parses migrated SQL → transformation logic + culprit",
           "One confirming query per finding sets the verdict",
           "Threshold-aware · schema & aggregate RCA · fixes"],
          "Runs anywhere — no Genie, no model, no external calls."),
         ("TIER 2 · AGENTIC", PURP, DARK, WHITE, GOLD, "Foundation-model · query-gated · optional",
          ["Reconstructs the derivation from source columns",
           "Proposes the precise cause AND a confirming query",
           "Promoted only if the query matches every row",
           "Interactive (Genie) or headless (FM endpoint)"],
          "Guardrail: the query is the gate — a wrong guess doesn’t stick.")]
for i, (badge, c, bg, tc, hc, sub, items, guard) in enumerate(tiers):
    x = 0.6 + i * 4.55
    rect(s, x, 2.3, 4.25, 3.0, fill=bg, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
    rect(s, x + 0.3, 2.55, 2.15, 0.34, fill=(WHITE if bg == DARK else WHITE), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5)
    txt(s, x + 0.3, 2.55, 2.15, 0.34, [(badge, {"size": 9, "bold": True, "font": HEAD, "color": c})],
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    txt(s, x + 0.3, 3.0, 3.7, 0.3, [(sub, {"size": 10, "font": BODY, "color": (LMUT if bg == DARK else MUT)})])
    txt(s, x + 0.3, 3.38, 3.75, 1.5, lines([(CHK + it, {"size": 10.5, "color": tc, "sa": 5}) for it in items]), spacing=1.03)
    txt(s, x + 0.3, 4.92, 3.75, 0.32, [(guard, {"size": 9.5, "font": BODY, "color": hc, "bold": True})], spacing=1.0)

# ============================ 3b — FLOW DIAGRAM ============================
def fbox(s, l, t, w, h, title, subt, fill, tc, sc, line=None):
    rect(s, l, t, w, h, fill=fill, line=line, lw=1.3, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.12)
    txt(s, l + 0.08, t + 0.13, w - 0.16, 0.34, [(title, {"size": 10.5, "bold": True, "font": HEAD, "color": tc})],
        align=PP_ALIGN.CENTER)
    if subt:
        txt(s, l + 0.08, t + 0.46, w - 0.16, h - 0.5, [(subt, {"size": 7.8, "font": BODY, "color": sc})],
            align=PP_ALIGN.CENTER, spacing=1.0)

def arrow(s, l, t, w, h, shape, color=MUT):
    rect(s, l, t, w, h, fill=color, shape=shape)

s = slide(WHITE)
chrome(s, "Pipeline", "How a recon_id becomes a proven root cause", title_size=23,
       sub="Deterministic path across the top; the agentic tier is an optional fallback for the residual — both end in the same query-backed notebook.")
xs = [0.6, 2.42, 4.24, 6.06, 7.88]; BW = 1.5; BY = 2.55; BH = 0.95
boxes = [
    ("recon_id", "from Lakebridge\nreconcile", PANEL, INK, MUT, TEAL),
    ("Ingest + classify", "typed probes ·\nper-dialect KB", PANEL, INK, MUT, None),
    ("Code-correlation", "parse migrated SQL →\n🔧 transform + ⚠️ culprit", PANEL, INK, MUT, None),
    ("Confirm", "one live query\nper finding", PANEL, INK, MUT, None),
    ("RCA Notebook", "verdict · culprit ·\nfix · owner", DARK, WHITE, LMUT, None),
]
for (title, subt, fill, tc, sc, ln), x in zip(boxes, xs):
    st = subt.replace("\n", " ")
    fbox(s, x, BY, BW, BH, title, st, fill, tc, sc, line=ln)
for x in xs[:-1]:
    arrow(s, x + BW + 0.01, BY + BH / 2 - 0.13, 0.30, 0.26, MSO_SHAPE.RIGHT_ARROW, color=LMUT)
# agentic branch below Confirm → RCA Notebook
arrow(s, xs[3] + BW / 2 - 0.13, BY + BH + 0.02, 0.26, 0.34, MSO_SHAPE.DOWN_ARROW, color=PURP)
txt(s, xs[3] + BW / 2 + 0.16, BY + BH + 0.04, 1.2, 0.3, [("residual", {"size": 8, "font": BODY, "color": PURP, "bold": True})])
fbox(s, xs[2] + 0.2, 4.05, 3.4, 1.0, "Tier-2 · Agentic fallback (optional)",
     "FM reconstructs the derivation from source columns + proposes a confirming query — promoted ONLY if it matches",
     DARK2, WHITE, LMUT)
arrow(s, xs[4] + BW / 2 - 0.13, 4.05 - 0.36, 0.26, 0.34, MSO_SHAPE.UP_ARROW, color=GREEN)
txt(s, xs[4] + BW / 2 + 0.16, 4.05 - 0.34, 1.5, 0.3, [("promoted ✓", {"size": 8, "font": BODY, "color": GREEN, "bold": True})])
# footnote legend
rect(s, 0.6, 5.18, 0.16, 0.16, fill=PANEL); txt(s, 0.82, 5.14, 4.5, 0.25, [("Deterministic — rule + query, no LLM",
     {"size": 8.5, "font": BODY, "color": MUT})])
rect(s, 5.2, 5.18, 0.16, 0.16, fill=DARK2); txt(s, 5.42, 5.14, 4.2, 0.25, [("Agentic — query-gated FM, optional",
     {"size": 8.5, "font": BODY, "color": MUT})])

# ============================ 4 — SURFACE MATRIX ============================
s = slide(WHITE)
chrome(s, "Surface fit", "One engine, three entry points — matched to workspace policy", title_size=23,
       sub="The same code-aware engine backs all three surfaces — the RCA notebook is identical wherever it runs.")
cols = [0.6, 3.7, 5.55, 7.35]; wid = [3.0, 1.8, 1.75, 2.05]
for cx, w, h in zip(cols, wid, ["ENTRY POINT", "DETERMINISTIC", "HYBRID", "BEST FOR"]):
    txt(s, cx, 2.35, w, 0.3, [(h, {"size": 9.5, "bold": True, "font": HEAD, "color": MUT})])
rect(s, 0.6, 2.66, 8.8, 0.02, fill=LMUT)
rows = [("Databricks App", "web UI · no local setup", "✓ default", GREEN, "✓ endpoint", GREEN, "Analysts; Genie-restricted"),
        ("CLI", "python -m rca_engine.cli", "✓ default", GREEN, "✓ --endpoint", GREEN, "CI/CD; Genie-restricted"),
        ("Genie Code skill", "rca-recon · agent mode", "✓ llm off", GREEN, "✓ BEST", RED, "Flexible · live agentic")]
y = 2.78
for name, sub, det, dc, hyb, hc, best in rows:
    txt(s, cols[0], y, wid[0], 0.32, [(name, {"size": 13, "bold": True, "font": HEAD, "color": INK})])
    txt(s, cols[0], y + 0.3, wid[0], 0.25, [(sub, {"size": 9, "font": BODY, "color": MUT})])
    txt(s, cols[1], y + 0.04, wid[1], 0.3, [(det, {"size": 11.5, "bold": True, "font": HEAD, "color": dc})])
    txt(s, cols[2], y + 0.04, wid[2], 0.3, [(hyb, {"size": 11.5, "bold": True, "font": HEAD, "color": hc})])
    txt(s, cols[3], y + 0.02, wid[3], 0.6, [(best, {"size": 10.5, "font": BODY, "color": TEAL})], spacing=1.02)
    rect(s, 0.6, y + 0.66, 8.8, 0.015, fill=PANEL)
    y += 0.82

# ============================ 5 — DECISION ============================
s = slide(WHITE)
chrome(s, "Decision guide", "Which entry point? Start with one question — is Genie Code approved?", title_size=22,
       sub="Genie Code isn’t enabled everywhere. It never blocks ReconResolve — deterministic runs anywhere; agentic runs where an FM endpoint is allowed.")
paths = [("⛔  Genie Code NOT approved", "restricted / regulated workspace", RED, PANEL, INK,
          [("Deterministic", "App · CLI — ship as-is, no model, fully auditable"),
           ("Hybrid", "App toggle · CLI --endpoint when an FM endpoint is allowed; else stay deterministic")]),
         ("✅  Genie Code approved", "flexible workspace", GREEN, DARK, WHITE,
          [("Deterministic", "Any surface — skill (llm off), App or CLI"),
           ("Hybrid", "Genie Code skill — best (agent reasons live); App / CLI + endpoint also work")])]
for i, (top, q, c, bg, tc, rws) in enumerate(paths):
    x = 0.6 + i * 4.55
    rect(s, x, 2.5, 4.25, 2.35, fill=bg, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
    rect(s, x, 2.5, 4.25, 0.06, fill=c)
    txt(s, x + 0.3, 2.68, 3.8, 0.35, [(top, {"size": 14, "bold": True, "font": HEAD, "color": tc})])
    txt(s, x + 0.3, 3.04, 3.8, 0.25, [(q.upper(), {"size": 8.5, "font": HEAD, "color": (LMUT if bg == DARK else MUT)})])
    yy = 3.45
    for mode, rec in rws:
        txt(s, x + 0.3, yy, 1.15, 0.6, [(mode.upper(), {"size": 9, "bold": True, "font": HEAD, "color": c})])
        txt(s, x + 1.45, yy, 2.65, 0.7, [(rec, {"size": 9.5, "font": BODY, "color": tc})], spacing=1.05)
        yy += 0.72
txt(s, 0.6, 5.05, 8.8, 0.4, [("Same engine underneath — the notebook is identical on every path. The choice is workspace "
    "policy and experience, never capability.", {"size": 10, "font": BODY, "color": MUT})], spacing=1.0)

# ============================ 6 — DEMO (BOTH) ============================
s = slide(WHITE)
chrome(s, "Proof · live demo", "Retail mart, Snowflake → Databricks, 2M rows — both approaches", title_size=22,
       sub="Two beds share the same rich composed ETL. Same engine, one flag apart.")
# deterministic card
rect(s, 0.6, 2.35, 4.25, 2.95, fill=PANEL, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
rect(s, 0.6, 2.35, 0.08, 2.95, fill=TEAL)
txt(s, 0.9, 2.5, 3.8, 0.3, [("DETERMINISTIC BED", {"size": 10, "bold": True, "font": HEAD, "color": TEAL})])
txt(s, 0.9, 2.78, 3.8, 0.3, [("13 findings @ 98% · no LLM · every verdict query-confirmed",
    {"size": 10, "font": BODY, "color": MUT})], spacing=1.02)
det_items = ["unit_price → precision · culprit DECIMAL(18,2)",
             "order_ts_utc → timezone · culprit + INTERVAL '5 HOURS'",
             "customer_name → string · culprit UPPER(TRIM(...))",
             "is_active → boolean · CASE 'Y'/'N' → 'true'/'false'",
             "tax_rate → within tolerance · correctly benign"]
txt(s, 0.9, 3.2, 3.9, 1.9, lines([(CHK + it, {"size": 9.5, "color": INK, "sa": 5, "font": BODY}) for it in det_items]), spacing=1.03)
# hybrid card
rect(s, 5.15, 2.35, 4.25, 2.95, fill=DARK, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
rect(s, 5.15, 2.35, 0.08, 2.95, fill=PURP)
txt(s, 5.45, 2.5, 3.8, 0.3, [("HYBRID BED — + AGENTIC", {"size": 10, "bold": True, "font": HEAD, "color": GOLD})])
txt(s, 5.45, 2.78, 3.8, 0.3, [("3 defects no rule can name — each query-confirmed @ 95%",
    {"size": 10, "font": BODY, "color": LMUT})], spacing=1.02)
hyb_items = [("net_revenue", "missing discount×tax cross-term"),
             ("amount_usd", "FX joined at month-start, not daily"),
             ("status_bucket", "dropped 'R' CASE branch → 'Unknown'")]
yy = 3.24
for col, cause in hyb_items:
    txt(s, 5.45, yy, 3.9, 0.5, [(CHK, {"size": 10, "color": GREEN, "bold": True, "font": BODY}),
        (col + " — ", {"size": 10.5, "color": WHITE, "bold": True, "font": HEAD}),
        (cause, {"size": 10, "color": LMUT, "font": BODY})], spacing=1.02)
    yy += 0.56
txt(s, 5.45, 5.02, 3.9, 0.28, [("Every finding carries 🔧 transformation logic + ⚠️ culprit + source script.",
    {"size": 8.5, "font": BODY, "color": LMUT})], spacing=1.0)

# ============================ 7 — BENCHMARKS (with data size) ============================
s = slide(WHITE)
chrome(s, "Benchmarks · measured on ps-dr-east", "Correct, fast, and scale-bounded on genuine reconcile output", title_size=21)
tiles = [("100%", "defects detected\n& classified", RED), ("7/7", "hybrid findings\nquery-confirmed", INK),
         ("~270s", "deterministic RCA\n2M · 3 tables", INK), ("6/6", "concurrent runs\n~500s wall", INK)]
for i, (n, l, c) in enumerate(tiles):
    x = 0.6 + i * 2.22
    rect(s, x, 2.2, 2.05, 1.0, fill=PANEL2, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    txt(s, x, 2.3, 2.05, 0.5, [(n, {"size": 26, "bold": True, "font": HEAD, "color": c})],
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    txt(s, x, 2.78, 2.05, 0.4, lines([(seg, {"size": 8.5, "font": BODY, "color": MUT}) for seg in l.split("\n")]),
        align=PP_ALIGN.CENTER)
# data-size / scale table
txt(s, 0.6, 3.42, 8.8, 0.28, [("SCALE & DATA SIZE", {"size": 9.5, "bold": True, "font": HEAD, "color": MUT})])
tcols = [0.6, 2.15, 3.55, 5.15, 6.55, 8.0]
theads = ["Source rows", "Stored (Delta)", "Logical", "Reconcile", "RCA det", "RCA hybrid"]
for cx, h in zip(tcols, theads):
    txt(s, cx, 3.72, 1.5, 0.25, [(h, {"size": 9, "bold": True, "font": HEAD, "color": TEAL})])
rect(s, 0.6, 3.98, 8.8, 0.015, fill=LMUT)
data = [("2,000,000", "~8.5 MB / table", "~0.15 GB", "944 s (warm)", "~270 s", "~390 s"),
        ("20,000,000", "~94 MB / table", "~1.5 GB", "1,014 s", "~50 s", "— (det)"),
        ("50,000,000 (wide)", "8.5 GB / table", "~17 GB", "1,637 s", "~97 s", "— (det)")]
yy = 4.06
for i, row in enumerate(data):
    for cx, v in zip(tcols, row):
        hl = (i == 2)  # prod-volume row
        txt(s, cx, yy, 1.55, 0.3, [(v, {"size": 9.5, "font": BODY, "color": (RED if hl else INK), "bold": hl})])
    yy += 0.34
txt(s, 0.6, 5.18, 8.8, 0.4, [("Prod-volume proof (bottom row): 50M WIDE high-cardinality rows = 8.5 GB stored/table "
    "(~17 GB) — reconcile 27 min, RCA ~97 s. RCA runs on the bounded recon sample, so it stays flat as volume "
    "grows. Stored = DESCRIBE DETAIL; low-cardinality demo cols compress ~20–30× (logical = GB column).",
    {"size": 8, "font": BODY, "color": MUT})], spacing=1.02)
if False:
  txt(s, 0.6, 4.86, 8.8, 0.6, [("Stored = Delta/Parquet bytes (DESCRIBE DETAIL); low-cardinality demo columns compress ~20–30× "
    "(logical = the GB figure). RCA runs on the bounded recon sample — 10× data grows RCA ~2×, reconcile ~3.2×. "
    "A true TB run needs wider, higher-cardinality rows (raise N in build_retail_beds.py) — flagged follow-up, "
    "reproducible from the same scripts.", {"size": 8.5, "font": BODY, "color": MUT})], spacing=1.05)

# ============================ VALIDATION / TEST COVERAGE ============================
s = slide(WHITE)
chrome(s, "Validation · test coverage", "Tested across every capability — and every entry point", title_size=22)
vt = [("3", "beds: hybrid ·\ndeterministic · aggregate", INK), ("100%", "seeded defects\ndetected & classified", RED),
      ("3", "entry points:\nApp · CLI · Skill", INK), ("50M", "rows · 8.5 GB\nreconciled (prod)", INK)]
for i, (n, l, c) in enumerate(vt):
    x = 0.6 + i * 2.22
    rect(s, x, 2.0, 2.05, 1.0, fill=PANEL2, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    txt(s, x, 2.1, 2.05, 0.5, [(n, {"size": 26, "bold": True, "font": HEAD, "color": c})],
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    txt(s, x, 2.6, 2.05, 0.4, lines([(seg, {"size": 8, "font": BODY, "color": MUT}) for seg in l.split("\n")]),
        align=PP_ALIGN.CENTER)
rect(s, 0.6, 3.18, 8.8, 0.46, fill=DARK, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
txt(s, 0.85, 3.18, 8.3, 0.46, [("Tested:  ", {"size": 9.5, "bold": True, "font": HEAD, "color": WHITE}),
    ("correctness · transform-logic + culprit + script location · confidence · deterministic & hybrid · "
     "App/CLI/Skill parity · concurrency · prod-volume (50M / 8.5 GB)", {"size": 9.5, "font": BODY, "color": LMUT})],
    anchor=MSO_ANCHOR.MIDDLE, spacing=1.0)
worked = ["Explains every mismatch and proves it with a live query",
          "Shows the migrated derivation, the ⚠️ culprit sub-expression, and the 📄 script path + line",
          "Deterministic (rules) and hybrid (query-gated FM) — same engine, one flag",
          "Per-finding confidence + a run-level rollup",
          "Identical output on App, CLI & Skill; 6 concurrent runs held"]
watch = ["Agentic root-cause needs an FM endpoint + a good confirming query — query-gated, so a miss stays "
         "needs-review, never wrong",
         "TB-scale needs wider / higher-cardinality rows (50M / 8.5 GB shown; TB = data-gen + warehouse cost)",
         "A joined derivation (e.g. FX) needs the lookup table's columns — supplied via join-context"]
txt(s, 0.6, 3.85, 4.3, 0.3, [("✅  What worked", {"size": 13, "bold": True, "font": HEAD, "color": GREEN})])
txt(s, 0.6, 4.2, 4.4, 1.4, lines([("•  " + w, {"size": 9, "color": INK, "sa": 4}) for w in worked]), spacing=1.05)
txt(s, 5.1, 3.85, 4.3, 0.3, [("🔎  Watch-outs", {"size": 13, "bold": True, "font": HEAD, "color": TEAL})])
txt(s, 5.1, 4.2, 4.3, 1.4, lines([("•  " + w, {"size": 9, "color": INK, "sa": 4}) for w in watch]), spacing=1.05)

# ============================ CAPABILITY MATRIX ============================
s = slide(WHITE)
chrome(s, "Capability matrix", "Capability status — the same across App, CLI & Skill", title_size=22)
ccols = [0.6, 3.85, 5.1, 8.35]; cwid = [3.1, 1.15, 3.1, 1.25]
for cx, w, h in zip(ccols, cwid, ["CAPABILITY", "STATUS", "WHAT WORKS", "ENTRY POINTS"]):
    txt(s, cx, 2.05, w, 0.3, [(h, {"size": 9, "bold": True, "font": HEAD, "color": MUT})])
rect(s, 0.6, 2.33, 8.8, 0.02, fill=LMUT)
caps = [
    ("Deterministic RCA", "rule + confirming query per finding", "App·CLI·Skill"),
    ("Transformation logic + culprit + script location", "derivation, culprit sub-expr, path·line·snippet", "App·CLI·Skill"),
    ("Hybrid (agentic fallback)", "query-gated FM on residual; promote only if confirmed", "App·CLI·Skill"),
    ("Confidence scoring", "per-finding % + confirmed badge + run rollup", "App·CLI·Skill"),
    ("Aggregate RCA", "per-rule SUM / AVG / COUNT by group", "App·CLI·Skill"),
    ("Threshold & schema", "within-tolerance benign; type/precision diffs", "App·CLI·Skill"),
    ("UC lineage trace-back + blast radius", "walks column/table lineage to the root; downstream consumers", "App·CLI·Skill"),
    ("Scale / prod-volume", "50M rows · 8.5 GB reconciled + RCA", "All"),
    ("Concurrency", "6 concurrent runs · ~500 s wall", "All"),
]
y = 2.42
for cap, works, ep in caps:
    txt(s, ccols[0], y, cwid[0], 0.34, [(cap, {"size": 10, "bold": True, "font": HEAD, "color": INK})], spacing=0.95)
    txt(s, ccols[1], y, cwid[1], 0.3, [("✅ Works", {"size": 9.5, "bold": True, "font": HEAD, "color": GREEN})])
    txt(s, ccols[2], y, cwid[2], 0.34, [(works, {"size": 8.5, "font": BODY, "color": MUT})], spacing=0.95)
    txt(s, ccols[3], y, cwid[3], 0.3, [(ep, {"size": 8.5, "font": MONO, "color": TEAL})])
    rect(s, 0.6, y + 0.335, 8.8, 0.012, fill=PANEL)
    y += 0.348

# ============================ 8 — IMPACT ============================
s = slide(WHITE)
chrome(s, "Why it matters", "Technical rigor that converts into migration throughput", title_size=23)
tech = [("Query-gated, never hallucinated", "Every verdict proven by a re-runnable query."),
        ("Code-aware to the sub-expression", "Names the exact culprit + the source script."),
        ("One engine, three surfaces", "App · CLI · Genie — identical output, det & agentic."),
        ("Scale-bounded", "Recon sample + scoped checks; 20M rows, 6 concurrent.")]
biz = [("Days → minutes per migration", "Reviewer-ready root cause for every difference."),
       ("Fits every customer", "Deterministic for Genie-restricted; agentic where allowed."),
       ("Auditable & trusted", "Append-only audit trail; a query behind every verdict."),
       ("Reusable asset", "Dialect-agnostic KBs + harness = program-wide capability.")]
for i, (head, items, c) in enumerate([("Technical impact", tech, TEAL), ("Business impact", biz, RED)]):
    x = 0.6 + i * 4.55
    txt(s, x, 2.3, 4.2, 0.35, [(head, {"size": 15, "bold": True, "font": HEAD, "color": c})])
    yy = 2.8
    for b, sub in items:
        rect(s, x, yy + 0.02, 0.05, 0.55, fill=c)
        txt(s, x + 0.22, yy, 4.0, 0.3, [(b, {"size": 11.5, "bold": True, "font": HEAD, "color": INK})])
        txt(s, x + 0.22, yy + 0.28, 4.0, 0.35, [(sub, {"size": 9.5, "font": BODY, "color": MUT})], spacing=1.0)
        yy += 0.66

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ReconResolve_Leadership.pptx")
prs.save(out)
print("saved", out, "·", len(prs.slides._sldIdLst), "slides · 10x5.63 · Barlow/DM Sans template")
