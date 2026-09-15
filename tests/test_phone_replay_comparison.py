import pytest

from tools.compare_phone_replays import compare_rows


def point(error, timestamp=1):
    return {"cycle": 0, "outageElapsedSeconds": timestamp, "recordingElapsedSeconds": timestamp,
            "available": error is not None, "errorMeters": error}


def test_more_output_does_not_hide_a_lost_success():
    result = compare_rows([point(2), point(None, 2)], [point(None), point(1, 2)])
    assert result["outputs"] == 2
    assert result["within10Before"] == result["within10After"] == 1
    assert result["previousSuccessesLost"] == result["previouslyAvailableLost"] == 1


def test_threshold_failure_is_not_misreported_as_an_availability_failure():
    result = compare_rows([point(2)], [point(30)])
    assert result["previousSuccessesLost"] == 1
    assert result["previouslyAvailableLost"] == 0
    assert result["maxCommonErrorIncreaseMeters"] == 28


def test_different_timelines_or_missing_rows_are_rejected():
    with pytest.raises(ValueError, match="timelines"):
        compare_rows([point(2)], [point(2, 3)])
    with pytest.raises(ValueError):
        compare_rows([point(2)], [])
