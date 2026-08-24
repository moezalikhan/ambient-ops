"""Shared request/response shapes.

`SegmentScore` is the frozen interface between the agent loop (Moez) and
`scoring/model.py` (Minqi) — spec section 12. Agreed day 2; neither side changes
it unilaterally after that.
"""

from typing import Literal

from pydantic import BaseModel, Field

from backend.config import DEFAULT_WEIGHTS

CostTier = Literal["Low", "Medium", "High"]


class Coordinate(BaseModel):
    lon: float
    lat: float


class Route(BaseModel):
    id: str
    name: str
    city: str
    origin_name: str
    destination_name: str
    origin: Coordinate
    destination: Coordinate
    distance_m: float | None = None
    # "placeholder" until Minqi confirms the city and the two real routes.
    status: Literal["placeholder", "confirmed"] = "placeholder"


class Segment(BaseModel):
    id: str
    route_id: str
    index: int
    start: Coordinate
    end: Coordinate
    midpoint: Coordinate
    length_m: float


class Weights(BaseModel):
    HEI: float = Field(default=DEFAULT_WEIGHTS["HEI"], ge=0, le=1)
    DTF: float = Field(default=DEFAULT_WEIGHTS["DTF"], ge=0, le=1)
    SVI: float = Field(default=DEFAULT_WEIGHTS["SVI"], ge=0, le=1)
    PSI: float = Field(default=DEFAULT_WEIGHTS["PSI"], ge=0, le=1)

    def normalised(self) -> "Weights":
        """Sliders move independently, so weights rarely sum to 1. Rescale so
        HPS stays on a 0-100 scale regardless of where the user drags them."""
        total = self.HEI + self.DTF + self.SVI + self.PSI
        if total == 0:
            return Weights()
        return Weights(
            HEI=self.HEI / total,
            DTF=self.DTF / total,
            SVI=self.SVI / total,
            PSI=self.PSI / total,
        )


class SegmentScore(BaseModel):
    """One scored segment. The contract with scoring/model.py."""

    id: str
    HEI: float = Field(ge=0, le=1, description="Heat Exposure Index")
    DTF: float = Field(ge=0, le=1, description="Dwell Time Factor")
    SVI: float = Field(ge=0, le=1, description="Surface Vulnerability Index")
    PSI: float = Field(ge=0, le=1, description="Population Sensitivity Index")
    HPS: float = Field(ge=0, le=100, description="Heat Priority Score")
    rank: int = Field(ge=1, description="1 = highest priority")


class Intervention(BaseModel):
    intervention: str
    rationale: str
    cost_tier: CostTier
    time_to_effect: str


class AnalyzeRequest(BaseModel):
    route_id: str
    weights: Weights = Field(default_factory=Weights)


class SimulateRequest(BaseModel):
    segment_id: str
    intervention: str


class ToolCall(BaseModel):
    """One entry in the agent trace shown live during judging (spec section 9)."""

    seq: int
    tool: str
    arguments: dict
    result_summary: str
    duration_ms: int
    cache_hit: bool = False
