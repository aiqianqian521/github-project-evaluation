"""TEST ONLY data containers. Not a Loop engine, scheduler, or integration proof."""

from dataclasses import dataclass, field
import sys
import types


@dataclass
class TaskInput:
    task_type: str = ""
    signals: list = field(default_factory=list)


@dataclass
class TaskResult:
    status: str = "error"
    execution: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    business: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    raw_output: dict = field(default_factory=dict)


def install():
    if "adapters.task_runner" in sys.modules:
        raise RuntimeError("refusing to override an existing Loop import")
    package = types.ModuleType("adapters")
    contract = types.ModuleType("adapters.task_runner")
    contract.TaskInput = TaskInput
    contract.TaskResult = TaskResult
    contract.TaskRunner = object
    sys.modules["adapters"] = package
    sys.modules["adapters.task_runner"] = contract
