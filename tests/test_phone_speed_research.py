import numpy as np
import pytest

from notebooks.research_phone_speed import fold_indices, metrics


def test_entire_rides_are_held_out_without_window_overlap():
    for index in range(3):
        training, held_out = fold_indices(3, index)
        assert held_out not in training
        assert sorted([*training, held_out]) == [0, 1, 2]
    with pytest.raises(ValueError):
        fold_indices(2, 0)


def test_speed_metrics_count_stationary_failures_without_claiming_position_accuracy():
    report = metrics(np.array([0., .1, 10.]), np.array([30., 20., 10.]))
    assert report["stationaryWindows"] == 2
    assert report["stationaryPredictedSpeedP90Mps"] > 20
    assert report["within1Mps"] == pytest.approx(1 / 3)
    with pytest.raises(ValueError):
        metrics(np.array([0.]), np.array([np.nan]))
