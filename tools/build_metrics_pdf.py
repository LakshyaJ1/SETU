"""Build the daylight SETU research dossier from measured, coordinate-free evidence."""

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from tools.run_road_stress import PROFILES, digest

PAPER = colors.HexColor("#F4F6F2")
SURFACE = colors.HexColor("#FCFDF9")
INK = colors.HexColor("#202A23")
MUTED = colors.HexColor("#5F6E62")
FOREST = colors.HexColor("#195A40")
BLUE = colors.HexColor("#176C96")
RULE = colors.HexColor("#CCD6CA")
WIDTH, HEIGHT = A4
MARGIN = 44
CONTENT = WIDTH - 2 * MARGIN
NAMES = {"cv": "Constant velocity", "imu": "Native IMU", "car": "Car constraints"}


def label(canvas, text, left, top, size=10, color=INK, bold=False):
    canvas.setFillColor(color)
    canvas.setFont("SetuBold" if bold else "Setu", size)
    canvas.drawString(left, top, str(text))


def paragraph(canvas, text, left, top, width=CONTENT, size=10, color=INK):
    style = ParagraphStyle("body", fontName="Setu", fontSize=size, leading=size * 1.5,
                           textColor=color)
    item = Paragraph(text, style)
    _, height = item.wrap(width, HEIGHT)
    if top - height < 50:
        raise ValueError("Report content exceeds the printable area")
    item.drawOn(canvas, left, top - height)
    return top - height


def page(canvas, title, subtitle):
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, WIDTH, HEIGHT, fill=1, stroke=0)
    label(canvas, "SETU", MARGIN, HEIGHT - 39, 17, FOREST, True)
    label(canvas, "Research dossier · not release approval", 235, HEIGHT - 37, 8, MUTED)
    canvas.setStrokeColor(RULE)
    canvas.line(MARGIN, HEIGHT - 54, WIDTH - MARGIN, HEIGHT - 54)
    label(canvas, title, MARGIN, HEIGHT - 97, 24, FOREST, True)
    paragraph(canvas, subtitle, MARGIN, HEIGHT - 116, size=9, color=MUTED)
    label(canvas, "GPS-free navigation / evidence before claims", MARGIN, 29, 8, MUTED)
    label(canvas, f"{canvas.getPageNumber():02d}", WIDTH - MARGIN - 15, 29, 9, FOREST)


def table(canvas, rows, widths, top, row_height=25, size=9):
    for row_index, row in enumerate(rows):
        left = MARGIN
        if row_index == 0:
            canvas.setFillColor(FOREST)
            canvas.rect(left, top - row_height, sum(widths), row_height, fill=1, stroke=0)
        elif row_index % 2:
            canvas.setFillColor(SURFACE)
            canvas.rect(left, top - row_height, sum(widths), row_height, fill=1, stroke=0)
        for value, width in zip(row, widths, strict=True):
            font = "SetuBold" if row_index == 0 else "Setu"
            if pdfmetrics.stringWidth(str(value), font, size) > width - 14:
                raise ValueError(f"Table label does not fit: {value}")
            label(canvas, value, left + 7, top - row_height + 9, size,
                  colors.white if row_index == 0 else INK, row_index == 0)
            left += width
        top -= row_height
    return top


def bars(canvas, cases, duration, top):
    left, plot_width = MARGIN + 163, CONTENT - 163
    label(canvas, "Within 10 m, including missing outputs", left, top + 17, 8, MUTED)
    for tick in (0, 50, 90, 100):
        position = left + plot_width * tick / 100
        canvas.setStrokeColor(FOREST if tick == 90 else RULE)
        canvas.setDash([3, 3] if tick == 90 else [])
        canvas.line(position, top - 246, position, top)
        label(canvas, str(tick), position - (16 if tick == 100 else 7), top - 261, 8, MUTED)
    canvas.setDash([])
    for index, profile in enumerate(PROFILES):
        center = top - index * 27 - 10
        name = profile.replace("scooter_", "").replace("_", " ").capitalize()
        label(canvas, name, MARGIN, center - 1, 8)
        for offset, algorithm in enumerate(("cv", "imu", "car")):
            case = cases[(algorithm, duration, profile)]
            canvas.setFillColor((MUTED, BLUE, FOREST)[offset])
            canvas.rect(left, center + 7 - offset * 6,
                        plot_width * case["jointSuccess"], 4, fill=1, stroke=0)
    for index, algorithm in enumerate(("cv", "imu", "car")):
        position = MARGIN + index * 173
        canvas.setFillColor((MUTED, BLUE, FOREST)[index])
        canvas.rect(position, top - 290, 13, 4, fill=1, stroke=0)
        label(canvas, NAMES[algorithm], position + 19, top - 291, 8)


def build(comparison_path, model_path, output, rides_path=None, pooled_path=None,
          training_path=None):
    report = json.loads(comparison_path.read_text(encoding="utf-8"))
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if report.get("synthetic") is not True or report.get("releaseApproved") is not False:
        raise ValueError("Report requires explicitly labelled research evidence")
    if (model.get("deployment_approved") is not False
            or model.get("version") != "speed-real-20260914"):
        raise ValueError("Update the archived model interpretation before reporting another model")
    cases = {(row["algorithm"], row["durationSeconds"], row["profile"]): row
             for row in report["cases"]}
    expected = {(algorithm, duration, profile) for algorithm in NAMES
                for duration in (10, 30, 60, 120, 180) for profile in PROFILES}
    if set(cases) != expected or len(report["cases"]) != len(expected):
        raise ValueError("The PDF requires the full paired comparison matrix")
    fonts = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont("Setu", str(fonts / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("SetuBold", str(fonts / "VeraBd.ttf")))
    pdfmetrics.registerFontFamily("Setu", normal="Setu", bold="SetuBold")
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(output), pagesize=A4, invariant=1, pageCompression=1)
    canvas.setTitle("SETU | GPS-free navigation evidence")
    canvas.setAuthor("SETU engineering")
    canvas.setSubject("Synthetic comparisons, recorded-ride diagnostics and model promotion gates")

    page(canvas, "Not yet a navigation release.",
         "The current evidence does not support the agreed 90% GPS-free positioning claim.")
    paragraph(canvas,
              "<b>The target is precise.</b> At least 90% of 10 Hz position updates within "
              "10 metres of an independent reference across 10–180-second GPS outages. "
              "Missing estimates count as failures. Existing drift and recovery gates still apply.",
              MARGIN, 660, size=11)
    label(canvas, "Ten-second outages, every stress profile", MARGIN, 557, 14, FOREST, True)
    bars(canvas, cases, 10, 515)
    paragraph(canvas,
              f"<b>{report['trials']} synthetic trials · {report['conditions']} conditions · "
              f"{report['repeats']} paired seeds.</b> The 90% line is a target, not a measured "
              "field guarantee. Car constraints on leaning profiles are a negative control.",
              MARGIN, 178, size=10)
    paragraph(canvas,
              "<b>Decision:</b> no GPS-free release winner. Keep GPS as the navigation reference; "
              "continue constrained, explicitly labelled sensor research "
              "without concealing missing output.",
              MARGIN, 103, size=9)
    canvas.showPage()

    page(canvas, "The whole comparison.",
         "Within-10-m success (%), with missing predictions in the denominator. Synthetic only.")
    top = 668
    for algorithm in ("cv", "imu", "car"):
        label(canvas, NAMES[algorithm], MARGIN, top, 13, FOREST, True)
        rows = [["Profile / outage", "10 s", "30 s", "60 s", "120 s", "180 s"]]
        for profile in PROFILES:
            rows.append([profile.replace("scooter_", "").replace("_", " ")] + [
                f"{cases[(algorithm, duration, profile)]['jointSuccess'] * 100:.1f}"
                for duration in (10, 30, 60, 120, 180)
            ])
        table(canvas, rows, [197, 62, 62, 62, 62, CONTENT - 445], top - 13, 15, 7.6)
        top -= 195
    paragraph(canvas, "Complete-seed bootstrap intervals and paired differences are available in "
              "comparison.json. Five seeds are exploratory; adjacent 10 Hz points "
              "are not independent trials.",
              MARGIN, 80, size=8)
    canvas.showPage()

    page(canvas, "Count the silence, too.",
         "Short successful fragments cannot stand in for complete GPS-free journeys.")
    paragraph(canvas,
              "<b>Protocol.</b> Each trial receives 120 seconds of GPS warmup and 200 Hz IMU. "
              "During the outage it receives neither GPS nor absolute-attitude assistance. "
              "The scorer checks every expected 10 Hz instant, including both endpoints.",
              MARGIN, 663, size=11)
    label(canvas, "Native IMU on scooter lean + potholes", MARGIN, 565, 14, FOREST, True)
    rows = [["Outage", "Available", "Within 10 m", "Missing ends"]]
    for duration in (10, 30, 60, 120, 180):
        case = cases[("imu", duration, "scooter_lean_potholes")]
        rows.append([f"{duration} s", f"{case['availability']*100:.1f}%",
                     f"{case['jointSuccess']*100:.1f}%",
                     f"{case['unavailableEnds']}/{case['runs']}"])
    table(canvas, rows, [98, 130, 140, CONTENT - 368], 541, 29)
    paragraph(canvas,
              "<b>Why availability falls.</b> The uncalibrated native core retains its 10-second "
              "outage / 150-metre uncertainty-radius limit. The last 1 Hz GPS fix precedes the "
              "first withheld fix, so this may leave only about nine seconds of output "
              "in the scored window. "
              "Removing the limit would not remove drift.", MARGIN, 334, size=10)
    paragraph(canvas,
              "<b>Hazards tested:</b> rough turns, smooth pothole displacement, scooter lean, "
              "sensor clipping, a 200 ms IMU gap and a phone-handling rotation. Sensor limits use "
              "the connected phone's recorded descriptors. The displacement and vibration profiles "
              "are controlled stress fixtures, not measurements of Indian road "
              "or suspension dynamics.",
              MARGIN, 215, size=10)
    paragraph(canvas,
              "The test harness corrects the former yaw-rate sign mismatch, measures travelled "
              "path length rather than endpoint displacement, and removes the ideal "
              "speed-locked vibration cue. "
              "Historical benchmark figures are not comparable release evidence.",
              MARGIN, 104, size=8)
    canvas.showPage()

    evaluation = model["evaluation"]
    test = evaluation["test"]
    baseline = evaluation["constant_training_median_baseline"]
    page(canvas, "Speed is not position.",
         "Archived learned-model evidence, separate from the native road-stress benchmark.")
    paragraph(canvas,
              f"The bundled <b>{escape(model['version'])}</b> speed model was trained on "
              f"{evaluation['trained_on']['real_runs']} real IO-VNBD recordings "
              f"({evaluation['trained_on']['training_windows']:,} windows). "
              f"Its held-out test contains {test['windows']:,} windows from four recordings "
              "by driver A. This is Car-only research from one vehicle/country, "
              "not scooter validation.",
              MARGIN, 665, size=11)
    rows = [["Speed metric", "Median baseline", "Learned model"]]
    for key, name in (("mae_mps", "MAE (m/s)"), ("rmse_mps", "RMSE (m/s)"),
                      ("p90_absolute_error_mps", "p90 absolute error (m/s)")):
        rows.append([name, f"{baseline[key]:.3f}", f"{test[key]:.3f}"])
    table(canvas, rows, [245, 132, CONTENT - 377], 542, 35)
    improvement = 100 * (1 - test["mae_mps"] / baseline["mae_mps"])
    paragraph(canvas,
              f"<b>{improvement:.1f}% lower mean absolute speed error</b> "
              "is useful research progress. "
              "It is not 90% position accuracy. Speed cannot supply absolute heading, distinguish "
              "parallel roads or remove accumulated position drift on its own.",
              MARGIN, 367, size=11)
    paragraph(canvas,
              f"<b>Promotion remains blocked.</b> Test three-sigma coverage is "
              f"{test['coverage']['3_sigma']*100:.2f}% versus the 98% gate. The stricter project "
              "quantization-parity gate also failed. The manifest's deployment approval is false.",
              MARGIN, 260, size=11)
    paragraph(canvas,
              "No new model was trained from the three scooter rides in this investigation. "
              "Kaggle MCP returned Unauthenticated; no new GPU run has been submitted. "
              "The original training run and its provenance remain separate and preserved.",
              MARGIN, 146, size=10)
    canvas.showPage()

    page(canvas, "Your rides are diagnostic data.",
         ("Baseline before pooled heading. " if pooled_path else "") +
         "Only the 9.007 km, 2.387 km and 3.423 km rides are selected; "
         "the 28 m recording is excluded.")
    paragraph(canvas,
              "The longest ride includes a phone orientation change in its final approximately "
              "2–3 km. The 2.387 km ride used scooter storage. The 3.423 km ride kept one phone "
              "position, but rigid mounting was not confirmed. These facts are preserved, not "
              "rewritten to make the data pass a training gate.", MARGIN, 665, size=10)
    if rides_path:
        rides = json.loads(rides_path.read_text(encoding="utf-8"))
        rows = [["Ride", "Outage", "Available", "Valid GPS", "Within 10 m"]]
        for ride in rides:
            outputs = ride["outputs"]
            rows.append([ride["ride"], f"{ride['outageSeconds']} s",
                         f"{ride['available']}/{outputs}",
                         f"{ride['referenceAvailable']}/{outputs}",
                         f"{ride['within10Meters']}/{outputs}"])
        table(canvas, rows, [85, 62, 114, 120, CONTENT - 381], 570, 20, 8)
        remaining = 220
    else:
        paragraph(canvas,
                  "<b>120-second-warmup replay is not yet included in this PDF.</b> "
                  "It is measured on the physical phone with withheld GPS and 10 Hz scoring. "
                  "Pending measurements are not filled with synthetic or zero-error results.",
                  MARGIN, 553, size=12)
        remaining = 375
    paragraph(canvas,
              "<b>Reference boundary.</b> Held-out phone GPS is a noisy comparison, "
              "not independent survey truth. Only GPS-provider observations may enter the "
              "reference map; fused/network updates can share timestamps and must not "
              "overwrite them. Poor or missing references "
              "are unscorable. Known successes divided by all updates are lower bounds, "
              "not an accuracy claim.", MARGIN, remaining, size=10)
    paragraph(canvas,
              "All originals remain read-only. Same-phone/day rides with unconfirmed mounts do not "
              "constitute independent training, validation, calibration and test sets. No private "
              "route coordinates or raw recordings are embedded in this report.",
              MARGIN, remaining - 113, size=10)
    canvas.showPage()

    page(canvas, "What we choose, and why.",
         "Choose a research direction now. Choose a release algorithm "
         "only after it passes the gates.")
    choices = [
        ("GPS for current navigation",
         "Use fresh, quality-checked GPS when available. Keep estimated and stale "
         "positions visibly "
         "distinct. This is the reliable path today, not a GPS-free solution."),
        ("Sensor fusion for controlled research",
         "Continue IMU, bias and heading work with explicit availability and uncertainty. "
         "Car non-holonomic and vibration assumptions cannot silently transfer "
         "to a leaning scooter."),
        ("No model promotion yet",
         "Retain the Car speed model as evaluation-only. A mount-aware scooter model "
         "needs independent "
         "sessions and vehicle-domain validation, not random windows from these three rides."),
        ("Independent road validation before release",
         "Measure mounted GPS-off journeys against an independent reference, including "
         "turns, stops, potholes, handling, screen-off operation and recovery. "
         "Count missing predictions as failures."),
    ]
    top = 665
    for title, detail in choices:
        label(canvas, title, MARGIN, top, 14, FOREST, True)
        paragraph(canvas, detail, MARGIN, top - 17, size=10)
        top -= 126
    paragraph(canvas,
              "The final APK and matching light-theme beta website remain release deliverables. "
              "Neither a polished report nor passing software checks substitutes for the agreed "
              "navigation accuracy. No final-release claim is made here.", MARGIN, 134, size=10)
    canvas.showPage()

    if pooled_path:
        pooled = json.loads(pooled_path.read_text(encoding="utf-8"))
        if pooled.get("deploymentApproved") is not False:
            raise ValueError("Pooled heading comparison must remain research evidence")
        ride_labels = {row.get("sourceSha256"): row["ride"] for row in rides} if rides_path else {}
        page(canvas, "More useful. Not yet enough.",
             "Pooled, bias-aware heading alignment. Matched development replays on the same phone.")
        paragraph(canvas,
                  "The new path fits relative yaw and horizontal acceleration bias over up to "
                  "60 seconds of GPS-aided motion. It requires uncertainty, residual, scale and "
                  "bias checks plus agreement between temporal halves. Strong short-window "
                  "alignment remains available. Neither path receives withheld GPS.",
                  MARGIN, 663, size=10)
        rows = [["Ride", "Outage", "Available before", "Available after", "Within 10 m after"]]
        for case in pooled["cases"]:
            denominator = case["outputs"]
            rows.append([
                ride_labels.get(case["sourceSha256"], case["recordingId"][:8]),
                f"{case['outageSeconds']} s",
                f"{case['availableBefore']}/{denominator}",
                f"{case['availableAfter']}/{denominator}",
                f"{case['within10After']}/{denominator}",
            ])
        table(canvas, rows, [85, 52, 117, 111, CONTENT - 365], 583, 19, 7.5)
        lost = sum(case["previousSuccessesLost"] for case in pooled["cases"])
        missing = sum(case["previouslyAvailableLost"] for case in pooled["cases"])
        paragraph(canvas,
                  f"<b>Paired regression check:</b> {lost} previously successful updates lost; "
                  f"{missing} previously available updates lost. Missing estimates remain in "
                  "every denominator. The table reports known successes, not survey accuracy.",
                  MARGIN, 248, size=10)
        paragraph(canvas,
                  "<b>Still below target.</b> The native 10-second / 150-metre uncertainty-radius "
                  "guard is unchanged. Longer scored outages still contain mostly missing "
                  "estimates. "
                  "These recordings informed development; they are not an unseen field test or "
                  "evidence of 90% generalization.", MARGIN, 142, size=10)
        canvas.showPage()

    if training_path:
        training = json.loads(training_path.read_text(encoding="utf-8"))
        if (training.get("deploymentApproved") is not False
                or training.get("status") != "completed" or len(training.get("folds", [])) != 3):
            raise ValueError("CPU training must be completed, three-fold research evidence")
        page(canvas, "Real rides. Local learning.",
             "A time-bounded CPU experiment; no GPU, data upload or Android model replacement.")
        minutes = training["elapsedSeconds"] / 60
        paragraph(canvas,
                  f"<b>{minutes:.1f} minutes.</b> Trained the existing speed-network architecture "
                  f"from random initialization on {training['totalWindows']:,} quality-filtered "
                  "four-second IMU windows. Forty epochs per whole-ride-held-out fold, followed "
                  "by a separate checkpoint trained on all three rides. The 28 m recording "
                  "remains excluded.", MARGIN, 664, size=11)
        rows = [["Held-out ride", "Model MAE", "Median MAE", "Error p90", "At-rest speed p90"]]
        for fold in training["folds"]:
            measured = fold["model"]
            rest = measured["stationaryPredictedSpeedP90Mps"]
            rows.append([
                fold["ride"], f"{measured['maeMps']:.2f}",
                f"{fold['trainMedianBaseline']['maeMps']:.2f}",
                f"{measured['absoluteErrorP90Mps']:.2f}", "n/a" if rest is None else f"{rest:.2f}",
            ])
        label(canvas, "ALL SPEED VALUES IN METRES PER SECOND", MARGIN, 535, 8, MUTED)
        table(canvas, rows, [90, 91, 91, 91, CONTENT - 363], 521, 31, 9)
        paragraph(canvas,
                  "<b>What this establishes:</b> the phone's collection pipeline can supply real "
                  "sensor/GPS training pairs, and local CPU training fits the requested time "
                  "budget. GPS supplies labels only; no GPS coordinates enter the network inputs.",
                  MARGIN, 357, size=11)
        paragraph(canvas,
                  "<b>Why the model stays out of navigation:</b> standstill predictions still "
                  "show motion on two held-out rides. These sessions share a phone and day, "
                  "their mounts are unconfirmed, and the longest ride includes a late orientation "
                  "change. The combined checkpoint has no independent evaluation. Speed error "
                  "cannot be presented as 90% GPS-free position accuracy.", MARGIN, 247, size=10)
        paragraph(canvas, escape(training_path.as_posix()), MARGIN, 122, size=8)
        label(canvas, digest(training_path), MARGIN, 85, 7, MUTED)
        canvas.showPage()

    page(canvas, "Reproduce the evidence.",
         "Machine-readable comparisons retain every condition, seed count "
         "and unavailable endpoint.")
    sources = [
        ("Synthetic comparison", comparison_path),
        ("Bundled speed-model manifest", model_path),
    ]
    if rides_path:
        sources.append(("Selected-ride replay summary", rides_path))
    if pooled_path:
        sources.append(("Matched pooled-heading comparison", pooled_path))
    top = 664
    for name, path in sources:
        label(canvas, name, MARGIN, top, 12, FOREST, True)
        paragraph(canvas, escape(path.as_posix()), MARGIN, top - 19, size=8)
        label(canvas, digest(path), MARGIN, top - 58, 7, MUTED)
        top -= 84
    paragraph(canvas,
              "<b>Scoring:</b> joint success is within-threshold predictions divided "
              "by every expected "
              "position update. Error quantiles on successful outputs are conditional and cannot "
              "replace availability. Missing final errors are null, never a stale last estimate.",
              MARGIN, top - 2, size=10)
    paragraph(canvas,
              "<b>Uncertainty:</b> 2,000 bootstrap resamples of complete simulation seeds, "
              "paired across algorithms. Five seeds are exploratory. "
              "This is not a confidence certificate for real "
              "road performance, and simulated noise is not a measured phone error distribution.",
              MARGIN, top - 110, size=10)
    paragraph(canvas,
              "<b>Regenerate:</b> see docs/verification/android/road-stress/README.md "
              "for commands, "
              "source hashes, protocol corrections and the exact measured builds. The original "
              "dark HTML experiment report and Android interface are unchanged by this PDF.",
              MARGIN, top - 220, size=9)
    canvas.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path,
                        default=Path("docs/verification/android/road-stress/comparison.json"))
    parser.add_argument(
        "--model", type=Path,
        default=Path("android/app/src/main/assets/models/setu-speed-v1/manifest.json"),
    )
    parser.add_argument("--rides", type=Path)
    parser.add_argument("--pooled-comparison", type=Path)
    parser.add_argument("--cpu-training", type=Path)
    parser.add_argument("--output", type=Path, default=Path("metrics.pdf"))
    arguments = parser.parse_args()
    build(arguments.comparison, arguments.model, arguments.output, arguments.rides,
          arguments.pooled_comparison, arguments.cpu_training)
    print(f"Wrote {arguments.output}: research evidence, not release approval")


if __name__ == "__main__":
    main()
