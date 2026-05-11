from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class Patient(BaseModel):
    id: str
    name: str | None = None
    created_at: datetime


class ParameterReading(BaseModel):
    date: datetime
    value: float
    status: Literal["normal", "high", "low"]


class Parameter(BaseModel):
    name: str
    raw_name: str
    unit: str
    organ: str
    reference_min: float
    reference_max: float
    readings: list[ParameterReading]
    trend: Literal["improving", "declining", "stable"] | None = None


class LabResult(BaseModel):
    id: str
    patient_id: str
    source_file: str
    ingested_at: datetime
    parameters: list[Parameter]


class OrganSummary(BaseModel):
    organ: str
    score: int
    flagged_count: int
    parameter_count: int
    rank: Literal["Optimal", "Good", "At Risk", "Critical"]
