"""Performance intelligence (§33-38, §88-97, §148-155, §168-169)."""

from forge_doctor_api.perf.baseline import (
    RequestBaseline,
    build_baselines,
    split_windows,
)
from forge_doctor_api.perf.budget import (
    ApiLatencyBudget,
    BudgetHop,
    BudgetReport,
    evaluate_budget,
)
from forge_doctor_api.perf.capacity import (
    ApiCapacitySignal,
    ApiCostDriver,
    Saturation,
    ThresholdProvenance,
    capacity_signals,
    cost_drivers,
)
from forge_doctor_api.perf.correlation import (
    ChangeEvent,
    RuntimeCorrelation,
    correlate_changes,
)
from forge_doctor_api.perf.criticalpath import (
    CriticalPathSegment,
    RequestCriticalPath,
    critical_path,
)
from forge_doctor_api.perf.experiments import (
    Constraint,
    Experiment,
    ExperimentReport,
    ExperimentVerdict,
    RequestScenario,
    evaluate_experiment,
)
from forge_doctor_api.perf.payload import PayloadShape, payload_shape_from_schema
from forge_doctor_api.perf.signals import (
    ApiPerformanceSignal,
    PerformanceFamily,
    performance_signals,
)
from forge_doctor_api.perf.stats import (
    MIN_SAMPLES,
    RobustStats,
    mad,
    median,
    percentile,
    robust_stats,
)

__all__ = [
    "MIN_SAMPLES",
    "ApiCapacitySignal",
    "ApiCostDriver",
    "ApiLatencyBudget",
    "ApiPerformanceSignal",
    "BudgetHop",
    "BudgetReport",
    "ChangeEvent",
    "Constraint",
    "CriticalPathSegment",
    "Experiment",
    "ExperimentReport",
    "ExperimentVerdict",
    "PayloadShape",
    "PerformanceFamily",
    "RequestBaseline",
    "RequestCriticalPath",
    "RequestScenario",
    "RobustStats",
    "RuntimeCorrelation",
    "Saturation",
    "ThresholdProvenance",
    "build_baselines",
    "capacity_signals",
    "correlate_changes",
    "cost_drivers",
    "critical_path",
    "evaluate_budget",
    "evaluate_experiment",
    "mad",
    "median",
    "payload_shape_from_schema",
    "percentile",
    "performance_signals",
    "robust_stats",
    "split_windows",
]
