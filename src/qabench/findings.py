"""The bug report contract shared by the agent, the scorer, and saved result files."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from qabench.repro import ReproStep


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=5, max_length=200)
    severity: Severity
    category: str = Field(min_length=2, max_length=40)
    spec_rule: str = Field(description="The requirement from the spec that is violated.")
    expected: str
    actual: str
    repro_steps: list[ReproStep] = Field(min_length=1, max_length=20)


class FindingsFile(BaseModel):
    """On-disk format for a set of findings, so runs can be re-scored without the API.

    Extra keys are ignored, so a full ``result.json`` from a run is also a valid input.
    """

    model_config = ConfigDict(extra="ignore")

    exam: str | None = Field(
        default=None, description="Exam version the findings were produced on (None = v0.1)."
    )
    bugs: list[str] = Field(description="Seeded bug IDs enabled in the build under test.")
    findings: list[Finding]
