from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


ALLOWED_ACTIVE_FEATURE_TYPES: tuple[str, ...] = (
    "Sketch",
    "Extrude",
    "Revolve",
    "Sweep",
    "Loft",
    "Chamfer",
    "Fillet",
    "Plane",
    "CPlane",
)


class CandidateStatus(str, Enum):
    PASSED = "passed"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class PublicCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    document_name: str | None = None
    document_id: str | None = None


class Feature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    raw_text: str
    feature_name: str
    feature_type: str
    is_suppressed: bool = False
    has_error: bool = False
    is_import: bool = False
    is_derived: bool = False
    suppression_state_known: bool = True


class FeatureTreeParseResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    features: list[Feature] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def reliable(self) -> bool:
        return not self.warnings


class UnsupportedFeature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    feature_name: str
    feature_type: str
    raw_text: str


class CandidateResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    document_name: str | None = None
    part_studio_name: str | None = None
    status: CandidateStatus
    reason: str
    active_feature_histogram: dict[str, int]
    active_unsupported_features: list[UnsupportedFeature] = Field(default_factory=list)
    suppressed_unsupported_features: list[UnsupportedFeature] = Field(default_factory=list)
    has_active_import: bool = False
    has_active_derived: bool = False
    has_active_error: bool = False
    has_feature_folders: bool = False
    feature_folders: list[str] = Field(default_factory=list)
    screenshot_path: str | None = None

    def to_output_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
