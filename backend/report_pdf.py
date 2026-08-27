"""Render the evidence record as a PDF.

Takes the same dict `report.build_report` produces, so the PDF and the JSON can
never disagree — one is a rendering of the other.

Designed to be read on paper: no colour carries meaning on its own, tables are
ruled rather than shaded for identity, and every figure that is an assumption
rather than a measurement is labelled in the text beside it.
"""

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

INK = colors.HexColor("#0b0b0b")
MUTED = colors.HexColor("#52514e")
FAINT = colors.HexColor("#898781")
RULE = colors.HexColor("#c3c2b7")
BAND = colors.HexColor("#f0efec")
FLAG = colors.HexColor("#a54812")   # the ramp's dark step, used only for emphasis

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
    "sub": _style("s", 9.5, 13, MUTED, space_after=14),
    "h2": _style("h2", 11, 14, bold=True, space_before=16, space_after=6),
    "h3": _style("h3", 9, 12, bold=True, space_before=9, space_after=3),
    "body": _style("b", 8.8, 12.5, space_after=5),
    "note": _style("n", 7.8, 11, MUTED, space_after=4),
    "cell": _style("c", 7.4, 9.5),
    "cellb": _style("cb", 7.4, 9.5, bold=True),
    "flag": _style("f", 9, 12.5, FLAG, bold=True, space_after=5),
}


def _p(text, style="body"):
    return Paragraph(str(text), S[style])


def _table(data, widths, header=True, zebra=False, highlight_rows=()):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
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


def _fmt(v, nd=2, dash="—"):
    if v is None:
        return dash
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def render_pdf(report: dict[str, Any]) -> bytes:
    """Return the report as PDF bytes."""
    buf = BytesIO()
    route = report.get("route") or {}
    run = report.get("run") or {}
    scoring = report.get("scoring") or {}
    sens = report.get("sensitivity") or {}
    deg = report.get("degenerate_factors") or {}

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Ambient Ops evidence record — {run.get('route_id')}",
        author="Ambient Ops",
    )

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

    # --- headline --------------------------------------------------------
    f.append(_p("What this says", "h2"))
    top = sens.get("baseline_top_segment")
    f.append(_p(
        f"The highest-priority segment is <b>{top}</b> at "
        f"{_fmt(sens.get('baseline_top_HPS'))} HPS, out of "
        f"{len(report.get('segments') or [])} segments over "
        f"{_fmt(route.get('distance_m'), 0)} m. Scores span "
        f"{_fmt(scoring.get('hps_spread'))} points."))

    if sens.get("verdict"):
        f.append(_p(f"Sensitivity: {sens['verdict']}", "flag"))

    if deg.get("factors"):
        f.append(_p(
            f"<b>{', '.join(deg['factors'])} carried no ranking information "
            f"on this route.</b> {deg.get('meaning')}"))
    else:
        f.append(_p(f"Degenerate factors: {deg.get('meaning', '')}"))

    # --- how it is scored -------------------------------------------------
    f.append(_p("How the score is built", "h2"))
    f.append(_p(f"<font face='Courier'>{scoring.get('formula')}</font>"))
    w = scoring.get("weights_used") or {}
    f.append(_table(
        [[_p("Factor", "cellb"), _p("Weight", "cellb"), _p("Meaning", "cellb")]]
        + [[_p(k, "cellb"), _p(_fmt(w.get(k)), "cell"),
            _p((scoring.get("factor_meanings") or {}).get(k, ""), "cell")]
           for k in ("HEI", "DTF", "SVI", "PSI")],
        widths=[18 * mm, 16 * mm, 140 * mm]))
    f.append(_p(scoring.get("weights_note", ""), "note"))

    # --- sensitivity ------------------------------------------------------
    if sens.get("perturbations"):
        f.append(_p("Does the ranking depend on those weights?", "h2"))
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

    # --- ranking ----------------------------------------------------------
    f.append(PageBreak())
    f.append(_p("Ranked segments", "h2"))
    head = [_p(h, "cellb") for h in
            ("Rank", "Segment", "HPS", "HEI", "DTF", "SVI", "PSI",
             "Heat (h)", "Run (m)", "Tree %")]
    rows = [head]
    for s in report.get("segments") or []:
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
        "construction.", "note"))

    # --- context ----------------------------------------------------------
    f.append(_p("What is physically present", "h2"))
    rows = [[_p(h, "cellb") for h in
             ("Seg", "Surface", "Shelter", "Buildings", "Transit <100 m",
              "Water (m)", "Nearby amenities")]]
    for s in report.get("segments") or []:
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

    # --- provenance -------------------------------------------------------
    f.append(PageBreak())
    f.append(_p("Where the data came from", "h2"))
    prov = report.get("data_provenance") or {}
    rows = [[_p("Input", "cellb"), _p("Source", "cellb"), _p("Detail", "cellb")]]
    for key, label in (("heat", "Heat exposure"), ("land_cover", "Land cover"),
                       ("route", "Route geometry"), ("context", "Context")):
        d = prov.get(key) or {}
        detail = " ".join(
            str(x) for x in (
                f"layer {d.get('layer')}, {d.get('threshold_c')} °C, "
                f"{d.get('window_days')} day window, {d.get('granularity_m')} m"
                if key == "heat" else "",
                d.get("note", ""),
            ) if x
        )
        rows.append([_p(label, "cellb"), _p(d.get("source", "—"), "cell"),
                     _p(detail, "cell")])
    f.append(_table(rows, widths=[28 * mm, 46 * mm, 100 * mm]))

    # --- assumptions ------------------------------------------------------
    f.append(_p("Intervention assumptions", "h2"))
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

    # --- limitations ------------------------------------------------------
    f.append(_p("Limitations", "h2"))
    for lim in report.get("limitations") or []:
        f.append(_p(f"•&nbsp;&nbsp;{lim}"))

    # --- agent trace ------------------------------------------------------
    trace = report.get("agent_trace") or []
    if trace:
        f.append(PageBreak())
        f.append(_p("What the agent did", "h2"))
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
