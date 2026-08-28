"""Render the evidence record as a PDF.

Takes the same dict `report.build_report` produces, so the PDF and the JSON can
never disagree — one is a rendering of the other.

Structured to be read in whatever depth the reader has time for. The summary
box answers the question on its own; the numbered sections — result, solution,
method, confidence, evidence, provenance, assumptions, limitations, conclusion
— each answer one thing and say in their heading which. A planner who reads
only sections 1, 2 and the conclusion has the decision; a judge who wants to
check it has the working in between.

Designed to be read on paper: no colour carries meaning on its own, tables are
ruled rather than shaded for identity, and every figure that is an assumption
rather than a measurement is labelled in the text beside it.
"""

from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

INK = colors.HexColor("#0b0b0b")
MUTED = colors.HexColor("#52514e")
FAINT = colors.HexColor("#898781")
RULE = colors.HexColor("#c3c2b7")
BAND = colors.HexColor("#f0efec")
FLAG_HEX = "#a54812"                # the ramp's dark step, used only for emphasis
FLAG = colors.HexColor(FLAG_HEX)

_ss = getSampleStyleSheet()


def _style(name, size, leading, colour=INK, space_before=0, space_after=4,
           bold=False):
    return ParagraphStyle(
        name, parent=_ss["BodyText"],
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, leading=leading, textColor=colour,
        spaceBefore=space_before, spaceAfter=space_after, alignment=TA_LEFT,
    )


S = {
    "title": _style("t", 18, 22, bold=True, space_after=2),
    "sub": _style("s", 9.5, 13, MUTED, space_after=6),
    "toc": _style("toc", 7.6, 11, FAINT, space_after=12),
    "h2": _style("h2", 11.5, 14, bold=True, space_before=15, space_after=2),
    "deck": _style("deck", 8, 11, MUTED, space_before=3, space_after=6),
    "h3": _style("h3", 9, 12, bold=True, space_before=9, space_after=3),
    "lead": _style("l", 10, 14, space_after=6),
    "body": _style("b", 8.8, 12.5, space_after=5),
    "bullet": _style("bul", 8.8, 12.5, space_after=4),
    "note": _style("n", 7.8, 11, MUTED, space_after=4),
    "cell": _style("c", 7.4, 9.5),
    "cellb": _style("cb", 7.4, 9.5, bold=True),
    "kvk": _style("kvk", 7.6, 10.5, MUTED, bold=True),
    "kvv": _style("kvv", 8.2, 10.5),
    "flag": _style("f", 9, 12.5, FLAG, bold=True, space_after=5),
}


# ReportLab's standard fonts are WinAnsi-encoded, so any character outside that
# set is drawn as a black box. The model reaches for typographic punctuation the
# encoding does not carry — non-breaking hyphens above all, which turned
# "highest-ranking" into "highest[]ranking" — so it is folded back to the ASCII
# equivalent on the way to the page. Applied to every string rather than only to
# the model's prose: route names and amenity tags come from the open web too.
_WINANSI_FALLBACK = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2212": "-",
    "\u2007": " ", "\u2008": " ", "\u2009": " ", "\u200a": " ",
    "\u202f": " ",
    "\u200b": "", "\u200c": "", "\u200d": "", "\u00ad": "", "\ufeff": "",
    "\u2032": "'", "\u2033": '"',
})


S["bullet"].leftIndent = 10
S["bullet"].firstLineIndent = -10


def _p(text, style="body"):
    return Paragraph(str(text).translate(_WINANSI_FALLBACK), S[style])


class _Sections:
    """Numbers the sections as they are emitted and remembers their names.

    The contents strip under the title is built from the same list, so it can
    never fall out of step with the body — sections that a given run has no
    data for are simply never numbered.
    """

    def __init__(self):
        self.n = 0
        self.entries: list[str] = []

    def heading(self, label: str, deck: str, short: str = "") -> KeepTogether:
        self.n += 1
        self.entries.append(f"{self.n} {short or label}")
        return KeepTogether([
            _p(f"<font color='{FLAG_HEX}'>{self.n}</font>&nbsp;&nbsp;"
               f"{label.upper()}", "h2"),
            HRFlowable(width="100%", thickness=0.6, color=RULE,
                       spaceBefore=2, spaceAfter=0),
            _p(deck, "deck"),
        ])

    def appendix(self, letter: str, label: str, deck: str,
                 short: str = "") -> KeepTogether:
        self.entries.append(f"{letter} {short or label}")
        return KeepTogether([
            _p(f"<font color='{FLAG_HEX}'>{letter}</font>&nbsp;&nbsp;"
               f"APPENDIX — {label.upper()}", "h2"),
            HRFlowable(width="100%", thickness=0.6, color=RULE,
                       spaceBefore=2, spaceAfter=0),
            _p(deck, "deck"),
        ])

    def strip(self) -> Paragraph:
        return _p("&nbsp;·&nbsp; ".join(self.entries), "toc")


def _bullet(text):
    return _p(f"\u2022&nbsp;&nbsp;{text}", "bullet")


def _table(data, widths, header=True, zebra=False, highlight_rows=()):
    # Left-aligned rather than reportlab's centred default: a table narrower
    # than the frame would otherwise sit indented from the margin every other
    # element is flush to.
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0,
              hAlign="LEFT")
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, colors.HexColor("#e1e0d9")),
    ]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafaf8")))
    for r in highlight_rows:
        cmds.append(("BACKGROUND", (0, r), (-1, r), BAND))
    t.setStyle(TableStyle(cmds))
    return t


def _summary_box(rows: list[tuple[str, str]]) -> Table:
    """The whole answer in one block, for a reader who stops after page one."""
    t = Table([[_p(k, "kvk"), _p(v, "kvv")] for k, v in rows],
              colWidths=[42 * mm, 132 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("LINEABOVE", (0, 0), (-1, 0), 1.2, FLAG),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, RULE),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#dedcd3")),
    ]))
    return t


def _fmt(v, nd=2, dash="—"):
    if v is None:
        return dash
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _gist(text: str | None, min_chars: int = 70) -> str:
    """Enough leading sentences to carry the meaning, not just the first.

    Some verdicts open with a single word — "Fragile." — which tells a reader
    of the summary box nothing on its own.
    """
    if not text:
        return "—"
    out = ""
    for sentence in text.split(". "):
        out += sentence.rstrip(".") + ". "
        if len(out) >= min_chars:
            break
    return out.strip()


def _prose(text: str) -> list[Paragraph]:
    """Model-written text, escaped — it is data here, not markup."""
    return [_p(escape(block.strip()).replace("\n", " "))
            for block in text.split("\n\n") if block.strip()]


def render_pdf(report: dict[str, Any]) -> bytes:
    """Return the report as PDF bytes."""
    buf = BytesIO()
    route = report.get("route") or {}
    run = report.get("run") or {}
    scoring = report.get("scoring") or {}
    sens = report.get("sensitivity") or {}
    deg = report.get("degenerate_factors") or {}
    rec = report.get("recommendation") or {}
    segments = report.get("segments") or []

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Ambient Ops evidence record — {run.get('route_id')}",
        author="Ambient Ops",
    )

    sec = _Sections()
    f: list[Any] = []

    # --- header ----------------------------------------------------------
    f.append(_p("Ambient Ops — evidence record", "title"))
    f.append(_p(
        f"{route.get('name') or run.get('route_id')} · "
        f"{route.get('origin_name')} → {route.get('destination_name')}<br/>"
        f"Run {run.get('run_id')} · {run.get('model')} · "
        f"{run.get('tool_calls')} tool calls · generated "
        f"{report.get('generated_at', '')[:19].replace('T', ' ')} UTC",
        "sub"))
    contents_at = len(f)
    f.append(Spacer(0, 0))          # replaced by the contents strip once built

    # --- summary ---------------------------------------------------------
    cands = rec.get("candidates") or []
    f.append(_summary_box([
        ("Question",
         f"Which {_fmt(route.get('distance_m'), 0)} m of this route should be "
         f"cooled first?"),
        ("Answer",
         f"Segment {rec.get('segment_index', '—')} "
         f"({rec.get('segment_id', '—')}), {_fmt(rec.get('HPS'))} HPS of a "
         f"possible 100, highest of {len(segments)} segments."),
        ("Shortlist",
         ", ".join(f"{c['intervention']} ({c['cost_tier'].lower()} cost)"
                   for c in cands) or "No rule in the table applies."),
        ("How firm", _gist(sens.get("verdict"))),
        ("Blind spots",
         f"{', '.join(deg['factors'])} carried no ranking information on this "
         f"route." if deg.get("factors") else "Every factor varied."),
        ("Not claimed",
         "No cooling magnitude, anywhere. No ground truth exists to validate "
         "the ranking against."),
    ]))

    # --- 1 result --------------------------------------------------------
    f.append(sec.heading("Result", "What the measurements found on this route."))
    f.append(_p(
        f"The highest-priority segment is <b>{sens.get('baseline_top_segment')}"
        f"</b> at {_fmt(sens.get('baseline_top_HPS'))} HPS, out of "
        f"{len(segments)} segments over {_fmt(route.get('distance_m'), 0)} m. "
        f"Scores span {_fmt(scoring.get('hps_spread'))} points.", "lead"))

    if sens.get("verdict"):
        f.append(_p(f"Sensitivity: {sens['verdict']}", "flag"))

    if deg.get("factors"):
        f.append(_p(
            f"<b>{', '.join(deg['factors'])} carried no ranking information "
            f"on this route.</b> {deg.get('meaning')}"))
    else:
        f.append(_p(f"Degenerate factors: {deg.get('meaning', '')}"))

    # --- 2 solution ------------------------------------------------------
    f.append(sec.heading(
        "Solution",
        "What to build on that segment, and the evidence that shortlisted it."))

    why = rec.get("why_this_segment") or []
    if why:
        f.append(_p("Why this segment", "h3"))
        for line in why:
            f.append(_bullet(line))

    if cands:
        f.append(_p("Candidate interventions", "h3"))
        rows = [[_p(h, "cellb") for h in
                 ("Intervention", "Cost", "Effect", "Why it qualifies",
                  "Trade-off")]]
        for c in cands:
            rows.append([
                _p(c.get("intervention"), "cellb"),
                _p(c.get("cost_tier"), "cell"),
                _p(c.get("time_to_effect"), "cell"),
                _p(c.get("condition"), "cell"),
                _p(c.get("trade_off"), "cell"),
            ])
        f.append(_table(rows, widths=[34 * mm, 14 * mm, 18 * mm, 44 * mm,
                                      64 * mm], zebra=True))
    f.append(_p(rec.get("note", ""), "note"))

    if rec.get("agent_brief"):
        f.append(_p("The agent's brief", "h3"))
        f.extend(_prose(str(rec["agent_brief"])))

    # --- 3 method --------------------------------------------------------
    f.append(sec.heading("Method",
                         "How a segment's Heat Priority Score is arrived at."))
    f.append(_p(f"<font face='Courier'>{scoring.get('formula')}</font>"))
    w = scoring.get("weights_used") or {}
    f.append(_table(
        [[_p("Factor", "cellb"), _p("Weight", "cellb"), _p("Meaning", "cellb")]]
        + [[_p(k, "cellb"), _p(_fmt(w.get(k)), "cell"),
            _p((scoring.get("factor_meanings") or {}).get(k, ""), "cell")]
           for k in ("HEI", "DTF", "SVI", "PSI")],
        widths=[18 * mm, 16 * mm, 140 * mm]))
    f.append(_p(scoring.get("weights_note", ""), "note"))

    # --- 4 confidence ----------------------------------------------------
    if sens.get("perturbations"):
        f.append(sec.heading(
            "Confidence",
            "Whether the ranking is driven by the measurements or by the "
            "weights someone chose."))
        f.append(_p(
            "Each weight is zeroed and doubled in turn and the resulting order "
            "compared against the baseline. A ranking that survives every "
            "perturbation is driven by the measurements; one whose leader "
            "changes under a single tweak is driven by the weighting."))
        rows = [[_p("Change", "cellb"), _p("Mean rank move", "cellb"),
                 _p("Max move", "cellb"), _p("New leader", "cellb")]]
        flips = []
        for i, p in enumerate(sens["perturbations"], start=1):
            if p["top_segment_changed"]:
                flips.append(i)
            rows.append([
                _p(f"{p['factor']} {p['change']}", "cell"),
                _p(_fmt(p["mean_rank_change"], 2), "cell"),
                _p(p["max_rank_change"], "cell"),
                _p(p["top_segment"] if p["top_segment_changed"] else "unchanged",
                   "cellb" if p["top_segment_changed"] else "cell"),
            ])
        f.append(_table(rows, widths=[38 * mm, 34 * mm, 24 * mm, 78 * mm],
                        highlight_rows=flips))
        f.append(_p(
            f"Margin between first and second: "
            f"{_fmt(sens.get('margin_to_second'))} HPS. "
            f"{sens.get('segments_within_2_HPS_of_top')} segment(s) lie within "
            f"2 HPS of the leader. Shaded rows are perturbations that change "
            f"which segment ranks first.", "note"))

    # --- 5 evidence: the ranking -----------------------------------------
    f.append(PageBreak())
    f.append(sec.heading(
        "Evidence — ranked segments",
        "Every segment, its score, and the four factor values behind it.",
        short="Ranked segments"))
    head = [_p(h, "cellb") for h in
            ("Rank", "Segment", "HPS", "HEI", "DTF", "SVI", "PSI",
             "Heat (h)", "Run (m)", "Tree %")]
    rows = [head]
    for s in segments:
        fac = s.get("factors") or {}
        raw = s.get("raw") or {}
        lc = s.get("land_cover_percent") or {}
        rows.append([
            _p(s.get("rank"), "cellb"), _p(f"seg {s.get('index')}", "cell"),
            _p(_fmt(s.get("HPS")), "cellb"),
            _p(_fmt(fac.get("HEI")), "cell"), _p(_fmt(fac.get("DTF")), "cell"),
            _p(_fmt(fac.get("SVI")), "cell"), _p(_fmt(fac.get("PSI")), "cell"),
            _p(_fmt(raw.get("heat_hours")), "cell"),
            _p(_fmt(raw.get("exposed_run_m"), 0), "cell"),
            _p(_fmt(lc.get("tree"), 1), "cell"),
        ])
    f.append(_table(rows,
                    widths=[12 * mm, 20 * mm, 16 * mm, 14 * mm, 14 * mm,
                            14 * mm, 14 * mm, 18 * mm, 18 * mm, 16 * mm],
                    zebra=True, highlight_rows=(1,)))
    f.append(_p(
        "Heat is hours above the threshold accumulated over the window. Run is "
        "the unbroken unshaded stretch the segment belongs to, which is what "
        "DTF measures — not the segment's own length, which is constant by "
        "construction. The shaded row is the segment section 2 recommends.",
        "note"))

    # --- 6 evidence: context ---------------------------------------------
    f.append(sec.heading(
        "Evidence — what is physically present",
        "The ground conditions each score was derived from.",
        short="Context"))
    rows = [[_p(h, "cellb") for h in
             ("Seg", "Surface", "Shelter", "Buildings", "Transit <100 m",
              "Water (m)", "Nearby amenities")]]
    for s in segments:
        c = s.get("context") or {}
        am = ", ".join(
            f"{a.get('type')} {a.get('distance_m')}m"
            for a in (c.get("nearby_amenities") or [])[:3]) or "—"
        rows.append([
            _p(s.get("index"), "cell"), _p(c.get("surface") or "—", "cell"),
            _p("yes" if c.get("shelter") else "—", "cell"),
            _p(c.get("building_count", "—"), "cell"),
            _p("yes" if c.get("transit_within_100m") else "—", "cell"),
            _p(_fmt(c.get("water_within_m"), 0), "cell"),
            _p(am, "cell"),
        ])
    f.append(_table(rows, widths=[12 * mm, 22 * mm, 16 * mm, 20 * mm,
                                  24 * mm, 18 * mm, 62 * mm], zebra=True))

    # --- 7 provenance ----------------------------------------------------
    f.append(PageBreak())
    f.append(sec.heading("Provenance",
                         "Which service each input came from, and at what "
                         "resolution."))
    prov = report.get("data_provenance") or {}
    rows = [[_p("Input", "cellb"), _p("Source", "cellb"), _p("Detail", "cellb")]]
    for key, label in (("heat", "Heat exposure"), ("land_cover", "Land cover"),
                       ("route", "Route geometry"), ("context", "Context")):
        d = prov.get(key) or {}
        detail = " ".join(
            str(x) for x in (
                f"layer {d.get('layer')}, {d.get('threshold_c')} °C, "
                f"{d.get('window_days')} day window, "
                f"{d.get('granularity_m')} m tiles."
                if key == "heat" else "",
                d.get("note", ""),
            ) if x
        )
        rows.append([_p(label, "cellb"), _p(d.get("source", "—"), "cell"),
                     _p(detail, "cell")])
    f.append(_table(rows, widths=[28 * mm, 46 * mm, 100 * mm]))

    # --- 8 assumptions ---------------------------------------------------
    f.append(sec.heading(
        "Assumptions",
        "What the simulator changes for each intervention, and which "
        "magnitudes are sourced."))
    ce = report.get("cooling_estimates") or {}
    f.append(_p(f"<b>{ce.get('note', '')}</b>"))
    rows = [[_p(h, "cellb") for h in
             ("Intervention", "What the model changes", "Magnitude sourced",
              "Trade-off")]]
    for i in report.get("intervention_assumptions") or []:
        rows.append([
            _p(i.get("label"), "cellb"), _p(i.get("assumption"), "cell"),
            _p("yes" if i.get("magnitude_sourced") else "NO — illustrative",
               "cell" if i.get("magnitude_sourced") else "cellb"),
            _p(i.get("caveat"), "cell"),
        ])
    f.append(_table(rows, widths=[36 * mm, 54 * mm, 26 * mm, 58 * mm],
                    zebra=True))

    # --- 9 limitations ---------------------------------------------------
    f.append(sec.heading("Limitations",
                         "What this record does not establish, stated as part "
                         "of the result."))
    for lim in report.get("limitations") or []:
        f.append(_bullet(lim))

    # --- 10 conclusion ---------------------------------------------------
    conclusion = report.get("conclusion") or []
    if conclusion:
        # Held together: a conclusion split across a page boundary leaves the
        # reader with two half-answers and a mostly blank page between them.
        f.append(KeepTogether(
            [sec.heading("Conclusion",
                         "What a planner should take away, and how far it "
                         "goes.")]
            + [_bullet(line) for line in conclusion]))

    # --- appendix: agent trace -------------------------------------------
    trace = report.get("agent_trace") or []
    if trace:
        f.append(sec.appendix(
            "A", "what the agent did",
            "The tool calls the model chose, in the order it chose them.",
            short="Agent trace"))
        f.append(_p(
            "The agent chose which tools to call and in what order; nothing in "
            "the code sequences the analysis. Durations are the tool call "
            "itself — where they are near zero the answer came from the local "
            "cache, and the elapsed time is the model deciding what to call "
            "next."))
        rows = [[_p(h, "cellb") for h in
                 ("#", "Tool", "Arguments", "ms", "Cached", "Result")]]
        for c in trace:
            args = "  ".join(f"{k}={v}" for k, v in (c.get("arguments") or {}).items())
            rows.append([
                _p(c.get("seq"), "cell"),
                _p(c.get("tool"), "cellb" if c.get("ok") else "cell"),
                _p(args or "—", "cell"),
                _p(c.get("duration_ms"), "cell"),
                _p("yes" if c.get("cache_hit") else "—", "cell"),
                _p(c.get("result_summary") or "", "cell"),
            ])
        f.append(_table(rows, widths=[8 * mm, 34 * mm, 44 * mm, 12 * mm,
                                      14 * mm, 62 * mm], zebra=True))

    f[contents_at] = sec.strip()

    def _chrome(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(FAINT)
        canvas.drawString(18 * mm, 10 * mm,
                          "Ambient Ops — decision support with a transparent "
                          "model, not a prediction. No cooling figures are stated.")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc_.page}")
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(18 * mm, 13 * mm, A4[0] - 18 * mm, 13 * mm)
        canvas.restoreState()

    doc.build(f, onFirstPage=_chrome, onLaterPages=_chrome)
    return buf.getvalue()
