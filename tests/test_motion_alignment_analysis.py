import numpy as np

from tools.analyze_motion_alignment import fit_heading, rolling_fits


def fixture(moving=True):
    generator = np.random.default_rng(2467)
    yaw = np.radians(70)
    rotation = np.array([[np.cos(yaw), -np.sin(yaw)], [np.sin(yaw), np.cos(yaw)]])
    acceleration = generator.normal(size=(20, 2)) if moving else np.zeros((20, 2))
    measured = acceleration + [.12, -.07]
    gps = acceleration @ rotation.T
    return np.column_stack([np.arange(20)*2, np.full(20, 2), measured*2, gps*2, np.full(20, .2)])


def test_pooled_heading_removes_constant_horizontal_bias():
    result = fit_heading(fixture())
    assert result["accepted"]
    assert abs(np.degrees(result["yawRadians"]) - 70) < 1e-8
    assert np.allclose(result["biasMps2"], [.12, -.07])


def test_no_excitation_cannot_determine_heading():
    assert fit_heading(fixture(False)) is None


def test_future_samples_cannot_change_past_alignment():
    rows = fixture()
    before = rolling_fits(rows)
    rows[-1, 4:6] += 500
    after = rolling_fits(rows)
    assert before[:-1] == after[:-1]
    assert not after[-1]["accepted"]


def test_constant_acceleration_cannot_separate_heading_from_bias():
    rows = fixture(False)
    rows[:, 4:6] = [.3, .2]
    assert fit_heading(rows) is None


def test_declared_noise_without_motion_does_not_initialize_heading():
    for seed in range(20):
        generator = np.random.default_rng(seed)
        rows = np.column_stack([
            np.arange(30) * 2, np.full(30, 2), generator.normal(0, .3, (30, 2)),
            generator.normal(0, 1, (30, 2)), np.full(30, 1),
        ])
        assert not any(row["accepted"] for row in rolling_fits(rows))
