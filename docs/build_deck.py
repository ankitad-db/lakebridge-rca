"""Build the ReconResolve leadership deck as a .pptx (16:9), import-ready for Google Slides.

Same content + palette as docs/reconresolve_leadership_deck.html. Run:
    python3 docs/build_deck.py   ->  docs/ReconResolve_Leadership.pptx
"""
from pptx import Presentation
from pptx.util import Inches as In, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
import os

# ---- palette ----
PAPER = RGBColor(0xF4, 0xF3, 0xEF)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
INK   = RGBColor(0x1B, 0x1E, 0x24)
MUTED = RGBColor(0x5C, 0x64, 0x72)
LINE  = RGBColor(0xE4, 0xE1, 0xD9)
STEEL = RGBColor(0x2B, 0x5B, 0x8A)
STEELS= RGBColor(0xE7, 0xEE, 0xF5)
HEAT  = RGBColor(0xC5, 0x6A, 0x2E)
HEATS = RGBColor(0xF6, 0xE9, 0xDD)
GOOD  = RGBColor(0x2E, 0x7D, 0x5B)
AGENT = RGBColor(0x7E, 0x4C, 0xA8)
AGENTS= RGBColor(0xEF, 0xE7, 0xF6)
SURF2 = RGBColor(0xEF, 0xED, 0xE6)

DISP = "Archivo"
BODY = "IBM Plex Sans"
MONO = "IBM Plex Mono"

prs = Presentation()
prs.slide_width = In(13.333)
prs.slide_height = In(7.5)
BLANK = prs.slide_layouts[6]
SW, SH = 13.333, 7.5


def slide(bg=WHITE):
    s = prs.slides.add_slide(BLANK)
    r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, In(0), In(0), In(SW), In(SH))
    r.fill.solid(); r.fill.fore_color.rgb = bg; r.line.fill.background()
    r.shadow.inherit = False
    return s


def box(s, l, t, w, h, fill=None, line=None, line_w=1.0, shape=MSO_SHAPE.RECTANGLE, radius=None):
    sp = s.shapes.add_shape(shape, In(l), In(t), In(w), In(h))
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid(); sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line; sp.line.width = Pt(line_w)
    sp.shadow.inherit = False
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            sp.adjustments[0] = radius
        except Exception:
            pass
    return sp


def text(s, l, t, w, h, runs, size=14, color=INK, bold=False, font=BODY, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, spacing=1.0, space_after=4):
    tb = s.shapes.add_textbox(In(l), In(t), In(w), In(h)); tf = tb.text_frame
    tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    if isinstance(runs, str):
        runs = [(runs, {})]
    first = True
    # a "run list" is a list of (text, opts) that all go on ONE paragraph unless opts has 'nl'
    p = tf.paragraphs[0]; p.alignment = align; p.line_spacing = spacing; p.space_after = Pt(space_after)
    for txt, o in runs:
        if o.get("nl") and not first:
            p = tf.add_paragraph(); p.alignment = o.get("align", align)
            p.line_spacing = o.get("spacing", spacing); p.space_after = Pt(o.get("space_after", space_after))
        r = p.add_run(); r.text = txt
        r.font.size = Pt(o.get("size", size)); r.font.bold = o.get("bold", bold)
        r.font.name = o.get("font", font); r.font.color.rgb = o.get("color", color)
        first = False
    return tb


def para(text_list):
    """Convenience: list of (txt, opts) where each starts a new line."""
    out = []
    for i, item in enumerate(text_list):
        t, o = (item if isinstance(item, tuple) else (item, {}))
        o = dict(o); o["nl"] = True
        out.append((t, o))
    return out


def eyebrow(s, txt, x=0.9, y=0.62, color=HEAT):
    text(s, x, y, 11, 0.3, [(txt.upper(), {"size": 12, "bold": True, "font": MONO, "color": color})])


def title(s, txt, x=0.9, y=0.95, w=11.5, size=30, color=INK):
    text(s, x, y, w, 1.4, [(txt, {"size": size, "bold": True, "font": DISP, "color": color})], spacing=1.0)


def accent_bar(s, color=HEAT):
    box(s, 0, 0, SW, 0.14, fill=color)


# ============================ SLIDE 1 — TITLE ============================
s = slide(PAPER)
box(s, 0, 0, SW, 0.16, fill=HEAT)
text(s, 0.9, 1.5, 11.5, 0.4, [("RECONRESOLVE", {"size": 15, "bold": True, "font": DISP, "color": HEAT})])
text(s, 0.9, 1.95, 11.5, 0.35, [("Post-Lakebridge reconciliation · root-cause analysis",
     {"size": 13, "font": MONO, "color": MUTED})])
text(s, 0.9, 2.7, 11.5, 2.2, [
    ("Reconcile tells you ", {"size": 40, "bold": True, "font": DISP, "color": INK}),
    ("what", {"size": 40, "bold": True, "font": DISP, "color": HEAT}),
    (" differs.", {"size": 40, "bold": True, "font": DISP, "color": INK}),
], spacing=1.05)
text(s, 0.9, 3.6, 11.5, 1.2, [
    ("ReconResolve tells you ", {"size": 40, "bold": True, "font": DISP, "color": INK}),
    ("why", {"size": 40, "bold": True, "font": DISP, "color": HEAT}),
    (" — and proves it.", {"size": 40, "bold": True, "font": DISP, "color": INK}),
], spacing=1.05)
text(s, 0.9, 4.95, 10.8, 1.1, [(
    "Reads the migrated SQL, pinpoints the exact transform and the part that broke, and confirms every "
    "verdict with a live query — deterministic by default, with an agentic layer for the hard long tail.",
    {"size": 15, "color": MUTED})], spacing=1.2)
# pipeline chips
steps = [("analyze", False), ("transpile", False), ("reconcile", False), ("RCA · ReconResolve", True)]
x = 0.9
for lbl, on in steps:
    w = 0.35 + 0.13 * len(lbl)
    b = box(s, x, 6.2, w, 0.5, fill=(HEATS if on else WHITE), line=(HEAT if on else LINE),
            shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5)
    text(s, x, 6.2, w, 0.5, [(lbl, {"size": 12, "font": MONO, "bold": on,
         "color": (INK if on else MUTED)})], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    x += w + 0.28
    if x < 8.5 and lbl != "RCA · ReconResolve":
        text(s, x - 0.24, 6.2, 0.22, 0.5, [("→", {"size": 13, "color": LINE})],
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# ============================ SLIDE 2 — THE GAP ============================
s = slide(WHITE); accent_bar(s)
eyebrow(s, "The gap")
title(s, "Between “the numbers don’t match” and a fix, there’s a week of manual work.", size=26, w=11.5)
cards = [
    ("TODAY · LAKEBRIDGE RECONCILE", "A list of differences", WARN if False else HEAT,
     "Reconcile reports which columns and rows differ — e.g. unit_price differs on 1,844,309 of "
     "2,000,000 rows. Correct and essential, but it stops at the symptom. An engineer still has to open "
     "the ETL, read the transform, hypothesize, and write queries to prove it — days per table."),
    ("WITH RECONRESOLVE", "The mechanism, the culprit, the proof", GOOD,
     "For every difference: the category, the exact migrated derivation, the ⚠️ likely-culprit "
     "sub-expression, the source script, a runnable confirming query, and a suggested fix — as a "
     "reviewer-ready notebook, in minutes."),
]
for i, (k, h, c, body) in enumerate(cards):
    x = 0.9 + i * 5.95
    box(s, x, 2.5, 5.55, 3.4, fill=WHITE, line=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
    box(s, x, 2.5, 0.09, 3.4, fill=c)
    text(s, x + 0.35, 2.8, 5.0, 0.3, [(k, {"size": 11, "bold": True, "font": MONO, "color": MUTED})])
    text(s, x + 0.35, 3.2, 5.0, 0.6, [(h, {"size": 20, "bold": True, "font": DISP, "color": INK})])
    text(s, x + 0.35, 3.95, 4.95, 1.9, [(body, {"size": 13, "color": MUTED})], spacing=1.2)

WARN = RGBColor(0xB9, 0x82, 0x2A)


# ============================ SLIDE 3 — TWO TIERS ============================
s = slide(WHITE); accent_bar(s, STEEL)
eyebrow(s, "How it works", color=STEEL)
title(s, "Two tiers. Every verdict is backed by a query — never a bare model guess.", size=25, w=11.5)
tiers = [
    ("TIER 1 · DETERMINISTIC", STEEL, STEELS, "Rule-based, query-confirmed",
     "No LLM. Reproducible and auditable — the default.",
     ["Per-dialect probes classify the mechanism",
      "Parses migrated SQL → transformation logic + culprit sub-expression",
      "One confirming query per finding; verdict + confidence from the result",
      "Threshold-aware, schema & aggregate RCA, suggested fixes"],
     "Runs anywhere — no Genie, no model, no external calls."),
    ("TIER 2 · AGENTIC", AGENT, AGENTS, "Foundation-model, query-gated",
     "Only the residual the rules can’t name. Optional.",
     ["Reconstructs the migrated derivation from source columns",
      "Proposes the precise cause AND a confirming SQL query",
      "Promoted only if the query matches every row — else needs-review",
      "Interactive (Genie Code) or headless (FM endpoint) — same gate"],
     "Guardrail: the query is the gate. A wrong hypothesis doesn’t stick."),
]
for i, (badge, c, cs, h, sub, items, guard) in enumerate(tiers):
    x = 0.9 + i * 5.95
    box(s, x, 2.4, 5.55, 4.4, fill=WHITE, line=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.03)
    bb = box(s, x + 0.35, 2.7, 2.6, 0.42, fill=cs, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5)
    text(s, x + 0.35, 2.7, 2.6, 0.42, [(badge, {"size": 10.5, "bold": True, "font": MONO, "color": c})],
         align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.35, 3.25, 5.0, 0.5, [(h, {"size": 19, "bold": True, "font": DISP, "color": INK})])
    text(s, x + 0.35, 3.8, 5.0, 0.3, [(sub, {"size": 12.5, "color": MUTED})])
    bullets = []
    for it in items:
        bullets.append(("•  " + it, {"size": 12.5, "color": INK, "space_after": 7}))
    text(s, x + 0.35, 4.25, 4.95, 1.9, para(bullets), spacing=1.1)
    box(s, x + 0.35, 6.15, 4.85, 0.5, fill=SURF2, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
    text(s, x + 0.5, 6.15, 4.6, 0.5, [(guard, {"size": 11, "color": MUTED})], anchor=MSO_ANCHOR.MIDDLE)


# ============================ SLIDE 4 — SURFACE MATRIX ============================
s = slide(WHITE); accent_bar(s)
eyebrow(s, "Surface fit")
title(s, "One engine, three entry points — matched to what each workspace allows.", size=25, w=11.5)
text(s, 0.9, 1.85, 11.5, 0.4, [("The same code-aware engine backs all three surfaces — the RCA notebook is "
     "identical wherever it runs. Both approaches are available on every surface.", {"size": 13, "color": MUTED})],
     spacing=1.15)
# table
cols = [0.9, 4.6, 6.7, 9.1]  # x of Entry, Det, Hybrid, Best-for
widths = [3.5, 2.0, 2.3, 3.3]
head = ["ENTRY POINT", "DETERMINISTIC", "HYBRID (DET + AGENTIC)", "BEST FOR"]
y = 2.55
for cx, w, h in zip(cols, widths, head):
    text(s, cx, y, w, 0.3, [(h, {"size": 10.5, "bold": True, "font": MONO, "color": MUTED})])
box(s, 0.9, y + 0.34, 11.5, 0.02, fill=LINE)
rows = [
    ("Databricks App", "web UI · no local setup", "✓ default", GOOD, "✓ toggle → FM endpoint", GOOD,
     "Analysts & leadership; Genie-restricted workspaces"),
    ("CLI", "python -m rca_engine.cli", "✓ default", GOOD, "✓ --endpoint", GOOD,
     "CI/CD & automation; Genie-restricted workspaces"),
    ("Genie Code skill", "rca-recon · agent mode", "✓ llm off", GOOD, "✓ BEST — interactive agent", HEAT,
     "Flexible workspaces wanting the live agentic experience"),
]
y = 3.05
for name, sub, det, detc, hyb, hybc, best in rows:
    text(s, cols[0], y, widths[0], 0.4, [(name, {"size": 14, "bold": True, "font": DISP, "color": INK})])
    text(s, cols[0], y + 0.32, widths[0], 0.3, [(sub, {"size": 10.5, "font": MONO, "color": MUTED})])
    text(s, cols[1], y, widths[1], 0.4, [(det, {"size": 12.5, "bold": True, "color": detc})])
    text(s, cols[2], y, widths[2], 0.4, [(hyb, {"size": 12.5, "bold": True, "color": hybc})])
    text(s, cols[3], y, widths[3], 0.7, [(best, {"size": 12, "color": MUTED})], spacing=1.05)
    box(s, 0.9, y + 0.78, 11.5, 0.015, fill=LINE)
    y += 1.0


# ============================ SLIDE 5 — DECISION ============================
s = slide(PAPER); accent_bar(s)
eyebrow(s, "Decision guide")
title(s, "Which entry point? Start with one question — is Genie Code approved?", size=25, w=11.5)
text(s, 0.9, 1.85, 11.5, 0.6, [("Genie Code isn’t enabled in every customer workspace. It never blocks "
     "ReconResolve: deterministic RCA runs everywhere, and the agentic tier runs wherever a Foundation-Model "
     "serving endpoint is permitted.", {"size": 13, "color": MUTED})], spacing=1.15)
paths = [
    ("⛔  Genie Code NOT approved", "restricted / regulated workspace", HEAT, HEATS,
     [("Deterministic", "App  ·  CLI  ship as-is — no model, fully auditable."),
      ("Hybrid", "App toggle · CLI --endpoint when an FM endpoint is allowed; else stay deterministic.")]),
    ("✅  Genie Code approved", "flexible workspace", STEEL, STEELS,
     [("Deterministic", "Any surface — skill (llm off), or App / CLI."),
      ("Hybrid", "Genie Code skill — best: the agent reasons live. App / CLI + endpoint also work.")]),
]
for i, (top, q, c, cs, rows2) in enumerate(paths):
    x = 0.9 + i * 5.95
    box(s, x, 2.65, 5.55, 3.2, fill=WHITE, line=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.03)
    box(s, x, 2.65, 5.55, 0.85, fill=cs, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    box(s, x, 3.3, 5.55, 0.2, fill=cs)  # square off bottom of header
    text(s, x + 0.35, 2.8, 5.0, 0.4, [(top, {"size": 16, "bold": True, "font": DISP, "color": INK})])
    text(s, x + 0.35, 3.18, 5.0, 0.3, [(q.upper(), {"size": 10, "font": MONO, "color": MUTED})])
    yy = 3.75
    for mode, rec in rows2:
        text(s, x + 0.35, yy, 1.4, 0.9, [(mode.upper(), {"size": 10.5, "bold": True, "font": MONO, "color": MUTED})])
        text(s, x + 1.75, yy, 3.5, 0.9, [(rec, {"size": 12.5, "color": INK})], spacing=1.12)
        yy += 1.0
text(s, 0.9, 6.15, 11.5, 0.6, [("Same engine underneath — the RCA notebook is identical on every path. The "
     "choice is workspace policy and experience, never capability.", {"size": 12.5, "color": MUTED, "bold": False})],
     spacing=1.1)


# ============================ SLIDE 6 — DEMO / AGENTIC WINS ============================
s = slide(WHITE); accent_bar(s, AGENT)
eyebrow(s, "Proof · live demo", color=AGENT)
title(s, "Retail mart, Snowflake → Databricks, 2M rows — genuine Lakebridge reconcile.", size=23, w=11.5)
text(s, 0.9, 1.8, 11.5, 0.6, [("Deterministic bed: 13 findings at 98%, every verdict query-confirmed. "
     "Hybrid bed adds three defects no rule can name — each precisely root-caused by the agentic tier and "
     "proven by a live reconstruction query:", {"size": 13, "color": MUTED})], spacing=1.15)
wins = [
    ("fact_sales.net_revenue", "ROUND(qty*price*(1+tax)\n   - qty*price*discount, 4)",
     "Missing cross-term.", " Discount & tax applied additively — the (1−d)(1+t) cross-term is dropped, inflating revenue."),
    ("fact_sales.amount_usd", "JOIN dim_fx\n  ON fx_date =\n     trunc(dt,'MM')",
     "FX join grain.", " Joined at month-start instead of the daily rate — intra-month drift is lost."),
    ("fact_sales.status_bucket", "CASE status_code\n  WHEN 'A'..'C'..'P'\n  ELSE 'Unknown' END",
     "Dropped CASE branch.", " No arm for 'R' (Returned) — those rows collapse to 'Unknown'."),
]
for i, (col, sql, cause_b, cause) in enumerate(wins):
    x = 0.9 + i * 3.95
    box(s, x, 2.55, 3.7, 3.9, fill=WHITE, line=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
    tg = box(s, x + 0.3, 2.8, 1.9, 0.34, fill=AGENTS, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5)
    text(s, x + 0.3, 2.8, 1.9, 0.34, [("AGENTIC · CONFIRMED", {"size": 8.5, "bold": True, "font": MONO, "color": AGENT})],
         align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.3, 3.25, 3.2, 0.3, [(col, {"size": 12.5, "bold": True, "font": MONO, "color": INK})])
    box(s, x + 0.3, 3.65, 3.1, 1.15, fill=SURF2, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    text(s, x + 0.45, 3.72, 2.9, 1.05, [(sql, {"size": 9.5, "font": MONO, "color": INK})], spacing=1.05)
    text(s, x + 0.3, 4.95, 3.2, 1.1, [(cause_b, {"size": 12, "bold": True, "color": HEAT}),
         (cause, {"size": 12, "color": MUTED})], spacing=1.12)
    text(s, x + 0.3, 6.05, 3.2, 0.3, [("✓ query-confirmed · 95%", {"size": 11, "bold": True, "font": MONO, "color": GOOD})])


# ============================ SLIDE 7 — BENCHMARKS ============================
s = slide(PAPER); accent_bar(s)
eyebrow(s, "Benchmarks · measured on ps-dr-east")
title(s, "Correct, fast, and scale-bounded on genuine reconcile output.", size=25, w=11.5)
tiles = [("100%", "Seeded defects detected & correctly classified", True),
         ("7/7", "Hybrid findings query-confirmed (4 det + 3 agentic)", False),
         ("~270s", "Deterministic RCA · 3 tables · 2M rows · full enrichment", False),
         ("6/6", "Concurrent RCA runs succeeded — ~500s wall (fleet)", False)]
for i, (n, l, hl) in enumerate(tiles):
    x = 0.9 + i * 2.98
    box(s, x, 2.35, 2.75, 1.65, fill=WHITE, line=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    text(s, x + 0.28, 2.5, 2.4, 0.7, [(n, {"size": 34, "bold": True, "font": DISP, "color": (HEAT if hl else INK)})])
    text(s, x + 0.28, 3.25, 2.3, 0.7, [(l, {"size": 10.5, "color": MUTED})], spacing=1.05)
# latency bar chart
box(s, 0.9, 4.3, 11.5, 2.55, fill=WHITE, line=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.02)
text(s, 1.2, 4.5, 8, 0.35, [("Stage latency", {"size": 15, "bold": True, "font": DISP, "color": INK}),
     ("   2M-row retail bed · seconds", {"size": 11, "font": MONO, "color": MUTED})])
bars = [("Reconcile (warm)", 944, STEEL), ("RCA · hybrid", 390, AGENT), ("RCA · deterministic", 270, STEEL),
        ("RCA · deterministic (lean)", 24, RGBColor(0x9D, 0xB8, 0xD2)), ("Aggregate RCA", 18, GOOD)]
maxv = 944.0; x0 = 4.0; maxw = 7.6
y = 5.05
for lbl, v, c in bars:
    text(s, 1.2, y - 0.03, 2.7, 0.3, [(lbl, {"size": 10.5, "font": MONO, "color": MUTED})])
    w = max(0.12, maxw * v / maxv)
    box(s, x0, y, w, 0.24, fill=c, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.4)
    text(s, x0 + w + 0.1, y - 0.03, 1.2, 0.3, [(f"{v}s", {"size": 10.5, "bold": True, "font": MONO, "color": INK})])
    y += 0.36
text(s, 1.2, 6.5, 11, 0.3, [("RCA cost is driven by optional live checks + FM calls (each toggleable) — not raw "
     "volume. 10× the data (2M→20M) grows RCA ~2×, reconcile ~3.2×; every seeded defect still caught.",
     {"size": 10.5, "color": MUTED})], spacing=1.1)


# ============================ SLIDE 8 — IMPACT ============================
s = slide(WHITE); accent_bar(s)
eyebrow(s, "Why it matters")
title(s, "Technical rigor that converts directly into migration throughput.", size=25, w=11.5)
tech = [("Query-gated, never hallucinated", "Every verdict — deterministic or agentic — is proven by a re-runnable query."),
        ("Code-aware to the sub-expression", "Names the exact culprit (a scale, an interval, a dropped CASE arm) and the source script."),
        ("One engine, three surfaces", "App, CLI, and Genie skill share the engine — identical output, deterministic & agentic on each."),
        ("Scale-bounded", "Runs on the recon sample + scope-bounded checks; proven at 20M rows, six concurrent runs.")]
biz = [("Days → minutes per migration", "Reviewer-ready root cause for every difference — engineers fix instead of investigate."),
       ("Fits every customer", "Deterministic ships to Genie-restricted & regulated workspaces; agentic where allowed."),
       ("Auditable & trusted", "An append-only audit trail and a query behind every verdict make results defensible."),
       ("Reusable asset", "Dialect-agnostic knowledge bases + a repeatable harness = a program-wide capability.")]
for i, (head, items, c) in enumerate([("Technical impact", tech, STEEL), ("Business impact", biz, HEAT)]):
    x = 0.9 + i * 5.95
    text(s, x, 2.4, 5.4, 0.4, [(head, {"size": 17, "bold": True, "font": DISP, "color": c})])
    yy = 3.05
    for b, sub in items:
        box(s, x, yy, 0.05, 0.85, fill=c)
        text(s, x + 0.25, yy, 5.2, 0.35, [(b, {"size": 13.5, "bold": True, "color": INK})])
        text(s, x + 0.25, yy + 0.35, 5.2, 0.6, [(sub, {"size": 11.5, "color": MUTED})], spacing=1.1)
        yy += 1.0

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ReconResolve_Leadership.pptx")
prs.save(out)
print("saved", out, "·", len(prs.slides._sldIdLst), "slides")
