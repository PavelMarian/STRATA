"""STRATA: layered point-in-time checks for ML pipelines written by coding agents."""
from .checks import Runner, anonymize, check_agent, check_features, check_history, check_task
from .infer import infer_schema
from .schema import Schema, TemporalDB
from .verdict import CLEAN, ERROR, LEAK, UNCHECKABLE, Report

__version__ = "0.1.0"
__all__ = ["Schema", "TemporalDB", "Runner", "Report", "check_task", "check_features",
           "check_history", "check_agent", "anonymize", "infer_schema",
           "LEAK", "CLEAN", "UNCHECKABLE", "ERROR"]
