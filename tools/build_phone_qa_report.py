"""Report GPS-withheld phone replay without disguising missing predictions as accuracy."""

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np

DURATIONS = (10, 20, 30, 40, 50, 90)


def read_suite(path):
    fields = {}
    cases = []
    status_names = {0: "passed", -1: "error", -2: "failed", -3: "skipped", -4: "skipped"}
    raw = path.read_bytes()
    contents = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    for line in contents.splitlines():
        match = re.match(r"INSTRUMENTATION_STATUS: (\w+)=(.*)", line)
        if match:
            fields[match[1]] = match[2]
        match = re.match(r"INSTRUMENTATION_STATUS_CODE: (-?\d+)", line)
        if not match:
            continue
        code = int(match[1])
        if code in status_names and "class" in fields and "test" in fields:
            cases.append({"test": fields["class"] + "." + fields["test"],
                          "status": status_names[code], "detail": fields.get("stack")})
        fields = {}
    return {"log": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "cases": cases, "counts": dict(Counter(case["status"] for case in cases)),
            "runnerCompleted": "INSTRUMENTATION_CODE: -1" in contents}


def score(rows):
    if not rows:
        raise ValueError("Cannot score an empty outage")
    errors = []
    for row in rows:
        if (type(row.get("available")) is not bool
                or type(row.get("referenceAvailable")) is not bool):
            raise ValueError("Availability must be explicit")
        error = row.get("errorMeters")
        if error is not None:
            if (not row["available"] or not row["referenceAvailable"]
                    or not math.isfinite(error) or error < 0):
                raise ValueError("Invalid position error")
            errors.append(error)
    within = sum(error <= 10 for error in errors)
    return {"expected": len(rows), "available": sum(row["available"] for row in rows),
            "referenceAvailable": sum(row["referenceAvailable"] for row in rows),
            "comparable": len(errors), "within10m": within,
            "jointSuccessPercent": 100 * within / len(rows),
            "availabilityPercent": 100 * sum(row["available"] for row in rows) / len(rows),
            "conditionalRmseMeters": float(np.sqrt(np.mean(np.square(errors)))) if errors else None,
            "conditionalMedianMeters": float(np.median(errors)) if errors else None,
            "conditionalP90Meters": (
                float(np.quantile(errors, .9, method="higher")) if errors else None),
            "conditionalMaxMeters": max(errors, default=None)}


def build_report(directory, suite_paths=(), hardware_path=None, checks_path=None):
    summaries = json.loads((directory / "summary.json").read_text(encoding="utf-8-sig"))
    identifiers = sorted({row["recordingId"] for row in summaries})
    expected = {(identifier, duration) for identifier in identifiers for duration in DURATIONS}
    observed = [(row["recordingId"], row["outageSeconds"]) for row in summaries]
    if len(identifiers) != 3 or len(observed) != len(set(observed)) or set(observed) != expected:
        raise ValueError("Require all six durations for exactly three distinct rides")
    hashes = {row["apkSha256"] for row in summaries}
    if len(hashes) != 1 or not re.fullmatch(r"[a-f0-9]{64}", next(iter(hashes))):
        raise ValueError("All replays must use one verified APK")
    checks = json.loads(checks_path.read_text(encoding="utf-8-sig")) if checks_path else None
    if checks_path and (not isinstance(checks, dict) or
                        checks.get("apkSha256") != next(iter(hashes))):
        raise ValueError("Supplementary checks belong to a different APK")
    all_rows = {duration: [] for duration in DURATIONS}
    prefixes = {duration: [] for duration in DURATIONS}
    phases = {duration: [] for duration in DURATIONS}
    cases = []
    for summary in summaries:
        identifier = summary["recordingId"]
        duration = summary["outageSeconds"]
        if not re.fullmatch(r"[a-f0-9-]{36}", identifier):
            raise ValueError("Invalid recording identifier")
        if (summary.get("schema") != "setu.phone-outage.v2"
                or summary["warmupSeconds"] != 120 or summary["scoreHz"] != 10):
            raise ValueError("Wrong replay protocol")
        trace = directory / f"{identifier}-{duration}.jsonl"
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        if len(rows) != summary["cycles"] * duration * 10 or not rows:
            raise ValueError("Incomplete scoring grid")
        for index, row in enumerate(rows):
            if row["cycle"] != index // (duration * 10) or not math.isclose(
                    row["outageElapsedSeconds"], (index % (duration * 10)) / 10, abs_tol=1e-9):
                raise ValueError("Scoring grid is missing, reordered or duplicated")
        metrics = score(rows)
        for source, metric in (("outputs", "expected"), ("available", "available"),
                               ("referenceAvailable", "referenceAvailable"),
                               ("comparable", "comparable"), ("within10Meters", "within10m")):
            if summary[source] != metrics[metric]:
                raise ValueError(f"Trace/summary mismatch: {source}")
        cases.append({"ride": identifiers.index(identifier) + 1, "outageSeconds": duration,
                      "sourceSha256": summary["sourceSha256"], "cycles": summary["cycles"],
                      "traceSha256": hashlib.sha256(trace.read_bytes()).hexdigest(), **metrics})
        all_rows[duration].extend(rows)
        if duration == 90:
            for phase_index, end in enumerate(DURATIONS):
                start = 0 if phase_index == 0 else DURATIONS[phase_index - 1]
                prefixes[end].extend(row for row in rows if row["outageElapsedSeconds"] < end)
                phases[end].extend(
                    row for row in rows if start <= row["outageElapsedSeconds"] < end)
    return {"schema": "setu.phone-qa.v1", "apkSha256": next(iter(hashes)),
            "deploymentApproved": False,
            "protocol": "120 s GPS warmup; 10 Hz ticks in [0, duration); "
                        "missing estimates count as failures",
            "reference": "Withheld phone GNSS, not independent surveyed ground truth",
            "limits": ["Three same-phone/day development rides with unconfirmed mounts",
                       "Duration runs have different cycle counts; matched prefixes use 90 s runs",
                       "Ticks and duration prefixes are correlated, not independent trials",
                       "Conditional errors exclude missing predictions; joint success does not",
                       "Missing references are unknown: joint success is a verified lower bound",
                       "Low errors on rare outputs do not prove long-outage tracking",
                       "Physical Location-off continuity is not a moving accuracy experiment"],
            "durations": [{"seconds": duration, **score(all_rows[duration])}
                          for duration in DURATIONS],
            "matched90SecondPrefixes": [{"seconds": duration, **score(prefixes[duration])}
                                         for duration in DURATIONS],
            "matched90SecondPhases": [{"start": 0 if index == 0 else DURATIONS[index - 1],
                                        "end": duration, **score(phases[duration])}
                                       for index, duration in enumerate(DURATIONS)],
            "rides": cases, "suites": [read_suite(path) for path in suite_paths],
            "supplementaryChecks": checks,
            "physicalLocationOff": json.loads(hardware_path.read_text(encoding="utf-8-sig"))
            if hardware_path else None}


def markdown(report):
    def number(value):
        return "Unavailable" if value is None else f"{value:.2f}"

    def table(rows, phase=False):
        lines = ["| Duration | Within 10 m / expected | Joint success | Available | "
                 "Reference | RMSE / p90, m |",
                 "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for row in rows:
            label = f"{row['start']}–{row['end']} s" if phase else f"{row['seconds']} s"
            lines.append(f"| {label} | {row['within10m']} / {row['expected']} | "
                         f"{row['jointSuccessPercent']:.2f}% | {row['available']} | "
                         f"{row['referenceAvailable']} | {number(row['conditionalRmseMeters'])} / "
                         f"{number(row['conditionalP90Meters'])} |")
        return lines

    lines = ["# SETU — phone QA and GPS-withheld report", "",
             "**Development evidence, not release approval.**",
             "", f"APK SHA-256: `{report['apkSha256']}`", "", report["protocol"], "",
             report["reference"],
             "", "## Requested outage durations", "", *table(report["durations"]),
             "", "## Matched prefixes of the same 90-second outages", "",
             *table(report["matched90SecondPrefixes"]), "",
             "## Non-overlapping phases of 90-second outages", "",
             *table(report["matched90SecondPhases"], phase=True), "", "## Limits", "",
             *(f"- {limit}" for limit in report["limits"]), "",
             "## Physical Location-off check", ""]
    hardware = report["physicalLocationOff"]
    if hardware:
        lines.extend([hardware["reference"], "", "| Checkpoint | Location enabled | "
                      "New paired IMU samples | Sensor age, ms | Native position |",
                      "| --- | --- | ---: | ---: | --- |"])
        for stage in hardware["stages"]:
            lines.append(f"| {stage['seconds']} s | {stage['systemLocationEnabled']} | "
                         f"{stage['pairedImuInPhase']} | {stage['lastSensorAgeMs']:.1f} | "
                         f"{stage['hasNativePosition']} |")
    else:
        lines.append("Not measured; no physical-continuity result is claimed.")
    checks = report.get("supplementaryChecks")
    if checks:
        lines.extend(["", "## Build and user-flow checks", "",
                      "| Check | Result | Detail |", "| --- | --- | --- |"])
        for check in checks["checks"]:
            lines.append("| " + " | ".join(str(check[key]).replace("|", "/")
                                           for key in ("name", "result", "detail")) + " |")
        lines.extend(["", "## Findings and remaining work", "",
                      *(f"- {finding}" for finding in checks["findings"])])
    lines.extend(["", "## Device test inventory", ""])
    for suite in report["suites"]:
        lines.extend([f"### {suite['log']}", "",
                      f"Runner completed: {suite['runnerCompleted']}. "
                      f"Counts: {suite['counts']}.", "",
                      "| Test | Result | Detail |", "| --- | --- | --- |"])
        for case in suite["cases"]:
            detail = (case["detail"] or "").replace("|", "/")
            lines.append(f"| `{case['test'].removeprefix('com.setu.navigator.')}` | "
                         f"{case['status']} | {detail} |")
        lines.append("")
        source_apk = checks.get("suiteApks", {}).get(suite["log"]) if checks else None
        if source_apk:
            lines.extend([f"Suite APK SHA-256: `{source_apk}`", ""])
    return "\n".join(lines) + "\n"


def write_pdf(report, destination):
    from xml.sax.saxutils import escape

    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    from tools.build_metrics_pdf import CONTENT, FOREST, INK, MARGIN, MUTED, PAPER, RULE, page

    fonts = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont("Setu", str(fonts / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("SetuBold", str(fonts / "VeraBd.ttf")))
    body = ParagraphStyle("body", fontName="Setu", fontSize=9, leading=14, textColor=INK)
    heading = ParagraphStyle("heading", parent=body, fontName="SetuBold", fontSize=18,
                             leading=23, textColor=FOREST, spaceAfter=16)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=12, textColor=MUTED)
    story = []

    def text(value, style=body):
        story.extend([Paragraph(escape(str(value)), style), Spacer(1, 10)])

    def grid(rows, widths):
        cells = [[Paragraph(escape(str(value)), body) for value in row] for row in rows]
        table = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DBEDBD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, colors.HexColor("#FCFDF9")]),
            ("LINEBELOW", (0, 0), (-1, -1), .35, RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
        story.extend([table, Spacer(1, 18)])

    def results(rows, phase=False):
        cells = [["GPS gap", "Within 10 m / expected", "Success", "Available", "p90 error"]]
        for row in rows:
            label = f"{row['start']}–{row['end']} s" if phase else f"{row['seconds']} s"
            error = row["conditionalP90Meters"]
            cells.append([label, f"{row['within10m']} / {row['expected']}",
                          f"{row['jointSuccessPercent']:.2f}%", row["available"],
                          "Unavailable" if error is None else f"{error:.2f} m"])
        grid(cells, [63, 140, 75, 75, CONTENT - 353])

    text("Six durations. No missing points hidden.", heading)
    text(report["protocol"])
    text(report["reference"])
    text("These development results do not establish the 90%-within-10-metre field target.")
    results(report["durations"])
    text("Verified success is a conservative lower bound: known within 10 metres "
         "divided by every expected update. Missing references remain unknown. "
         "p90 errors describe comparable predictions only, not missing positions.")
    for limitation in report["limits"]:
        text(limitation, small)
    text("APK SHA-256: " + report["apkSha256"], small)
    story.append(PageBreak())
    text("The same outages, examined in phases.", heading)
    text("Cumulative prefixes of the same 90-second outages. These keep the test "
         "cohort fixed when comparing durations; they are not independent experiments.")
    results(report["matched90SecondPrefixes"])
    text("Non-overlapping intervals within those same outages:")
    results(report["matched90SecondPhases"], phase=True)
    story.append(PageBreak())
    text("The actual Android Location switch.", heading)
    hardware = report["physicalLocationOff"]
    if hardware:
        text(hardware["reference"])
        grid([["Time", "Location on", "Paired IMU in phase", "Sensor age"], *[
            [f"{stage['seconds']} s", str(stage["systemLocationEnabled"]),
             stage["pairedImuInPhase"], f"{stage['lastSensorAgeMs']:.1f} ms"]
            for stage in hardware["stages"]]], [65, 95, 175, CONTENT - 335])
    else:
        text("Not yet measured. No hardware-continuity or physical-position accuracy is claimed.")
    text("A stationary USB-connected phone does not supply an independently measured "
         "moving route. Sensor continuity and GPS-withheld replay are separate checks.")
    if hardware:
        text("Native position at checkpoints: " + ", ".join(
            f"{stage['seconds']} s: {'available' if stage['hasNativePosition'] else 'unavailable'}"
            for stage in hardware["stages"]))
    checks = report.get("supplementaryChecks")
    if checks:
        story.append(PageBreak())
        text("Build and user-flow checks", heading)
        grid([["Check", "Result", "Evidence"], *[
            [check["name"], check["result"], check["detail"]] for check in checks["checks"]]],
            [120, 65, CONTENT - 185])
        story.append(PageBreak())
        text("Findings and remaining work", heading)
        for finding in checks["findings"]:
            text(finding)
    for suite in report["suites"]:
        story.append(PageBreak())
        text("Device checks", heading)
        text(suite["log"], small)
        source_apk = checks.get("suiteApks", {}).get(suite["log"]) if checks else None
        if source_apk:
            text("Suite APK SHA-256: " + source_apk, small)
        text(f"Runner completed: {suite['runnerCompleted']}. Counts: {suite['counts']}")
        grid([["Test", "Result"], *[
            [case["test"].removeprefix("com.setu.navigator."), case["status"]]
            for case in suite["cases"]]], [CONTENT - 70, 70])
        for case in suite["cases"]:
            if case["detail"] and case["status"] != "skipped":
                text(case["test"].removeprefix("com.setu.navigator."), small)
                text(case["detail"], small)
    document = SimpleDocTemplate(str(destination), leftMargin=MARGIN, rightMargin=MARGIN,
                                 topMargin=155, bottomMargin=55, title="SETU phone QA and outages")

    def decorate(canvas, document):
        page(canvas, "Phone QA & GPS outages",
             "Measured development evidence · not release approval")

    document.build(story, onFirstPage=decorate, onLaterPages=decorate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay_directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--suite", type=Path, action="append", default=[])
    parser.add_argument("--suite-directory", type=Path)
    parser.add_argument("--hardware", type=Path)
    parser.add_argument("--checks", type=Path)
    args = parser.parse_args()
    suites = list(args.suite)
    if args.suite_directory:
        suites += sorted(args.suite_directory.glob("[0-9]*.log"))
    report = build_report(args.replay_directory, suites, args.hardware, args.checks)
    if args.suite_directory:
        grouped = report["suites"][len(args.suite):]
        if not grouped:
            raise ValueError("Isolated suite must match the complete discovered test inventory")
        if grouped:
            cases = [case for suite in grouped for case in suite["cases"]]
            discovered = read_suite(args.suite_directory / "discovery.log")
            if (not discovered["runnerCompleted"] or
                    Counter(case["test"] for case in cases) !=
                    Counter(case["test"] for case in discovered["cases"])):
                raise ValueError("Isolated suite must match the complete discovered test inventory")
            report["suites"] = report["suites"][:len(args.suite)] + [{
                "log": "Isolated device test methods", "cases": cases,
                "runnerCompleted": all(suite["runnerCompleted"] for suite in grouped),
                "counts": dict(Counter(case["status"] for case in cases)),
                "sourceLogs": [{"log": suite["log"], "sha256": suite["sha256"]}
                               for suite in grouped]}]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.md").write_text(markdown(report), encoding="utf-8")
    write_pdf(report, args.output / "report.pdf")
    report["artifacts"] = {
        "markdownSha256": hashlib.sha256((args.output / "report.md").read_bytes()).hexdigest(),
        "pdfSha256": hashlib.sha256((args.output / "report.pdf").read_bytes()).hexdigest(),
    }
    staging = args.output / "report.json.partial"
    staging.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    staging.replace(args.output / "report.json")
    print(json.dumps(report["durations"], indent=2))


if __name__ == "__main__":
    main()
