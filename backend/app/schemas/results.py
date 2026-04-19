from typing import Any

from pydantic import BaseModel, Field


class Metric(BaseModel):
    key: str
    label: str
    value: float
    format: str = Field(
        default="number",
        description="'number' | 'percent' | 'ratio' — hint for UI formatting",
    )


class ChartSpec(BaseModel):
    id: str = Field(description="Stable per-strategy chart identifier")
    title: str
    description: str | None = Field(
        default=None,
        description="Short markdown caption shown under the chart title",
    )
    guide_md: str | None = Field(
        default=None,
        description="Collapsible long-form markdown ('Plain-language guide')",
    )
    figure: dict[str, Any] = Field(
        description="Plotly figure JSON (data + layout)"
    )


class ColumnSpec(BaseModel):
    key: str
    label: str
    format: str = Field(
        default="text",
        description="'text' | 'number' | 'percent' | 'ratio' | 'date'",
    )
    align: str = Field(default="left", description="'left' | 'right'")


class TableSpec(BaseModel):
    id: str
    title: str
    description: str | None = None
    columns: list[ColumnSpec]
    rows: list[dict[str, Any]]


class TabSpec(BaseModel):
    id: str
    title: str
    icon: str | None = None
    intro_md: str | None = Field(
        default=None,
        description="Top-of-tab markdown (usually the 'Plain-language summary' guide)",
    )
    metrics: list[Metric] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    tables: list[TableSpec] = Field(default_factory=list)


class StrategyResult(BaseModel):
    overview_md: str | None = Field(
        default=None,
        description="Strategy-level markdown shown above all tabs",
    )
    metrics: list[Metric] = Field(
        default_factory=list,
        description="Global metric strip shown above tabs",
    )
    tabs: list[TabSpec] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StrategyMeta(BaseModel):
    id: str
    name: str
    description: str
    instrument_kind: str = Field(description="'vol' or 'trend' — what to pick")
    has_summary: bool = Field(
        default=False,
        description="True if this strategy exposes a multi-instrument summary endpoint",
    )


class StrategyListResponse(BaseModel):
    strategies: list[StrategyMeta]
