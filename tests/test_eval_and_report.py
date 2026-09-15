"""Pipeline, metrics, experiment and report tests.

The pipeline tests are the ones that matter most in this file. Three separate
bugs in it produced the *same* visible symptom -- a filter that diverged past a
kilometre -- and in each case the innovation gate was rejecting nearly every
measurement rather than anything crashing. So the assertions here check the
gate-acceptance rates directly, not just the final error: a filter that is
accurate today because two errors cancel is not a filter anyone should trust.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from setu.eval.experiment import BASELINES, run_outage, sawtooth_score
from setu.eval.metrics import evaluate_outage, summarise
from setu.pipeline import PipelineConfig, run_pipeline
from setu.sim import PHONE_MID, simulate_drive

OUTAGE = (150.0, 210.0)


@pytest.fixture(scope="module")
def drive():
    return simulate_drive(
        "curvy_a_road", route_length_m=5000.0, device=PHONE_MID, outages=(OUTAGE,), seed=11
    )


@pytest.fixture(scope="module")
def the_map(drive):
    return drive.path.perturbed(1.5, np.random.default_rng(0))


@pytest.fixture(scope="module")
def solution(drive, the_map):
    return run_pipeline(drive.log, path=the_map)


def horizontal_error(sol, truth):
    tp = np.stack([np.interp(sol.t, truth.t, truth.pos_enu[:, k]) for k in range(2)], axis=1)
    return np.linalg.norm(sol.pos_enu[:, :2] - tp, axis=1)


class TestMetrics:
    def test_summarise_orders_percentiles(self):
        s = summarise(np.arange(101.0))
        assert s.p50 == 50 and s.p90 == 90 and s.p95 == 95 and s.max == 100
        assert s.n == 101

    def test_summarise_handles_empty(self):
        s = summarise(np.array([]))
        assert s.n == 0 and np.isnan(s.p50)

    def test_summarise_ignores_non_finite(self):
        s = summarise(np.array([1.0, np.nan, 3.0, np.inf]))
        assert s.n == 2

    def test_along_and_cross_decomposition(self):
        """A pure lateral offset must land entirely in cross-track."""
        t = np.linspace(0, 10, 50)
        true_xy = np.stack([t * 10.0, np.zeros_like(t)], axis=1)
        est_xy = true_xy + np.array([0.0, 2.0])  # 2 m to the left, heading east
        m = evaluate_outage(t, est_xy, true_xy, true_heading=np.zeros_like(t))
        assert m.cross_track.p50 == pytest.approx(2.0, abs=1e-9)
        assert m.along_track.p50 == pytest.approx(0.0, abs=1e-9)
        assert m.lane_keeping_rate == pytest.approx(0.0)

    def test_drift_ratio_is_error_over_distance(self):
        t = np.linspace(0, 10, 50)
        true_xy = np.stack([t * 10.0, np.zeros_like(t)], axis=1)
        est_xy = true_xy.copy()
        est_xy[-1, 0] += 5.0
        m = evaluate_outage(t, est_xy, true_xy, true_heading=np.zeros_like(t))
        assert m.distance_m == pytest.approx(100.0, rel=1e-6)
        assert m.drift_ratio == pytest.approx(0.05, rel=1e-6)


class TestPipeline:
    def test_spectral_inputs_do_not_include_a_gnss_acceleration_prior(self, monkeypatch):
        drive = simulate_drive(
            "curvy_a_road",
            route_length_m=700.0,
            device=PHONE_MID,
            outages=((10.0, 20.0),),
            seed=17,
        )

        def inspect_inputs(odometer, imu, *, a_long=None, speed_hint=None):
            assert imu is drive.log.imu
            assert a_long is None, "The spectral frontend must not receive an unmasked GNSS prior"
            assert speed_hint is None
            raise RuntimeError("spectral inputs inspected")

        monkeypatch.setattr("setu.pipeline.SpectralOdometer.estimate", inspect_inputs)
        with pytest.raises(RuntimeError, match="spectral inputs inspected"):
            run_pipeline(drive.log, config=PipelineConfig(warmup_s=5.0))

    def test_unavailable_gnss_velocity_cannot_change_the_solution(self):
        drive = simulate_drive(
            "curvy_a_road",
            route_length_m=700.0,
            device=PHONE_MID,
            outages=((10.0, 20.0),),
            seed=17,
        )
        unavailable = ~drive.log.gnss.available
        assert unavailable.any()
        poisoned_velocity = drive.log.gnss.vel_enu.copy()
        poisoned_velocity[unavailable] = [4000.0, -3000.0, 0.0]
        poisoned_log = replace(drive.log, gnss=replace(drive.log.gnss, vel_enu=poisoned_velocity))
        config = PipelineConfig(warmup_s=5.0, use_cts=False, use_csa=False)
        original = run_pipeline(drive.log, config=config)
        poisoned = run_pipeline(poisoned_log, config=config)
        assert np.array_equal(original.pos_enu, poisoned.pos_enu)
        assert np.array_equal(original.vel_enu, poisoned.vel_enu)

    def test_measurements_are_accepted_not_gated_out(self, solution):
        """The symptom every pipeline bug so far has produced.

        A filter whose gate rejects its own measurements is diverging even when
        the final number happens to look reasonable.
        """
        gating = solution.gating
        for kind in ("gnss_pos", "gnss_vel", "nhc"):
            accepted, total = gating.get(kind, (0, 0))
            assert total > 0, f"{kind} never ran"
            assert accepted / total > 0.85, f"{kind} accepted only {accepted}/{total}"

    def test_tracks_the_truth_while_gnss_is_present(self, solution, drive):
        err = horizontal_error(solution, drive.truth)
        have_gnss = solution.gnss_available
        assert float(np.percentile(err[have_gnss], 90)) < 6.0

    def test_survives_the_blackout(self, solution, drive):
        err = horizontal_error(solution, drive.truth)
        out = (solution.t >= OUTAGE[0]) & (solution.t <= OUTAGE[1])
        assert out.sum() > 100
        assert not solution.gnss_available[out].any(), "outage must withhold all GNSS"
        assert float(np.percentile(err[out], 90)) < 25.0

    def test_reports_its_tier_and_notes(self, solution):
        assert solution.tier in ("A", "B", "C", "D")
        assert solution.notes
        assert any("mount" in n for n in solution.notes)

    def test_channels_are_recorded(self, solution):
        assert solution.channels
        for _name, (t, valid) in solution.channels.items():
            assert len(t) == len(valid)

    def test_runs_without_a_map(self, drive):
        """No map is a supported mode, not an error."""
        sol = run_pipeline(drive.log, path=None)
        assert len(sol) > 100
        assert not sol.anchors

    def test_rejects_a_log_that_is_too_short(self, drive):
        from setu.sensors.types import ImuStream, SensorLog

        tiny = SensorLog(
            imu=ImuStream(
                t=drive.log.imu.t[:5],
                accel=drive.log.imu.accel[:5],
                gyro=drive.log.imu.gyro[:5],
            ),
            gnss=drive.log.gnss,
        )
        with pytest.raises(ValueError, match="too short"):
            run_pipeline(tiny)

    def test_determinism(self, drive, the_map):
        a = run_pipeline(drive.log, path=the_map)
        b = run_pipeline(drive.log, path=the_map)
        assert np.array_equal(a.pos_enu, b.pos_enu)


class TestAblations:
    """Turning a channel off must degrade the result without destabilising it."""

    @pytest.fixture(scope="class")
    def traces(self, drive, the_map):
        out = {}
        for label in ("B1_ins", "B2_ins_nhc_zupt", "SETU"):
            out[label] = run_outage(
                drive,
                the_map,
                BASELINES[label],
                start_s=OUTAGE[0],
                end_s=OUTAGE[1],
                label=label,
            )
        return out

    def test_setu_beats_the_classical_baseline(self, traces):
        assert traces["SETU"].metrics.fpe_m < traces["B2_ins_nhc_zupt"].metrics.fpe_m

    def test_setu_beats_pure_inertial_by_an_order_of_magnitude(self, traces):
        assert traces["SETU"].metrics.fpe_m < 0.1 * traces["B1_ins"].metrics.fpe_m

    def test_pure_inertial_diverges(self, traces):
        """B1 exists to show the t^2 growth; if it does not, the test is wrong."""
        assert traces["B1_ins"].metrics.drift_ratio > 0.02

    def test_setu_passes_the_sih_gate_with_margin(self, traces):
        """G-1: p90 drift ratio below 10 % of distance travelled."""
        assert traces["SETU"].metrics.drift_ratio < 0.10
        assert traces["SETU"].metrics.fpe_m < 100.0  # G-2

    def test_only_setu_registers_anchors(self, traces):
        assert traces["SETU"].metrics.n_anchors > 0
        assert traces["B2_ins_nhc_zupt"].metrics.n_anchors == 0


class TestFalsification:
    def test_sawtooth_is_positive_when_error_resets(self, drive, the_map):
        """The central claim, measured: error is given back at landmarks."""
        tr = run_outage(
            drive, the_map, BASELINES["SETU"], start_s=OUTAGE[0], end_s=OUTAGE[1], label="SETU"
        )
        assert len(tr.anchor_distance_m) >= 3
        assert sawtooth_score(tr) > 0.05

    def test_sawtooth_is_undefined_without_anchors(self, drive, the_map):
        tr = run_outage(
            drive,
            the_map,
            BASELINES["B2_ins_nhc_zupt"],
            start_s=OUTAGE[0],
            end_s=OUTAGE[1],
            label="B2_ins_nhc_zupt",
        )
        assert np.isnan(sawtooth_score(tr))

    def test_monotone_growth_scores_zero(self):
        """A curve that only ever grows must not score as a sawtooth."""
        from setu.eval.experiment import OutageTrace
        from setu.eval.metrics import evaluate_outage as ev

        d = np.linspace(0, 800, 400)
        e = 0.03 * d
        t = np.linspace(0, 60, 400)
        xy = np.stack([d, np.zeros_like(d)], axis=1)
        tr = OutageTrace(
            label="synthetic",
            t=t,
            distance_m=d,
            error_m=e,
            sigma_m=np.ones_like(d),
            anchor_distance_m=np.array([200.0, 500.0]),
            metrics=ev(t, xy, xy, true_heading=np.zeros_like(d)),
        )
        assert sawtooth_score(tr) < 0.05


class TestReport:
    @pytest.fixture(scope="class")
    def result(self, drive, the_map):
        from setu.eval.experiment import ExperimentResult

        traces = [
            run_outage(drive, the_map, BASELINES[lb], start_s=OUTAGE[0], end_s=OUTAGE[1], label=lb)
            for lb in ("B1_ins", "B2_ins_nhc_zupt", "SETU")
        ]
        return ExperimentResult(
            route="curvy_a_road",
            tier=traces[0].metrics.tier,
            outage_s=60.0,
            traces=traces,
            scores={t.label: sawtooth_score(t) for t in traces},
            verdict="supported: test fixture",
        )

    def test_renders_valid_standalone_html(self, result):
        from setu.report import render_report
        from setu.report.page import SWEEP_SCRIPT

        html = render_report(result)
        assert html.startswith("<!doctype html>")
        assert html.count("<svg") >= 3  # hero, coverage, trajectory
        assert "</html>" in html
        assert SWEEP_SCRIPT in html
        assert "<script" not in html.replace(SWEEP_SCRIPT, "")
        injected = render_report(replace(result, route='<script src="https://invalid.test"></script>'))
        assert "<script" not in injected.replace(SWEEP_SCRIPT, "")
        assert "&lt;script" in injected
        assert html.count("<link") == 3  # two preconnects plus the font stylesheet

    def test_reports_the_conditions_with_the_numbers(self, result):
        """docs/08-evaluation.md 8.1: no figure without tier, protocol, baseline."""
        from setu.report import render_report

        html = render_report(result)
        assert "tier" in html.lower()
        assert "8.1" in html or "withheld" in html
        assert "B2" in html

    def test_writes_a_file(self, result, tmp_path):
        from setu.report import write_report

        p = write_report(result, tmp_path / "nested" / "r.html")
        assert p.exists() and p.stat().st_size > 20_000

    def test_charts_escape_their_inputs(self):
        from setu.report.charts import coverage_strip

        svg = coverage_strip([("<script>x</script>", np.arange(10.0), np.ones(10, bool))])
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg
