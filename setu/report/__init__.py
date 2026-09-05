"""HTML report: the experiment result as a page someone can read and judge."""

from .charts import coverage_strip, error_vs_distance, trajectory
from .page import render_report, write_report
from .theme import SERIES, TOKENS

__all__ = [
    "render_report",
    "write_report",
    "error_vs_distance",
    "trajectory",
    "coverage_strip",
    "TOKENS",
    "SERIES",
]
