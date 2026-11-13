from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScopeItem(BaseModel):
    description: str = Field(description="One buildable scope item, e.g. 'supply and place 25MPa concrete for slab'")
    qty: float = Field(gt=0)
    unit: str = Field(description="Unit as written in the tender: m2, m3, m, hour, each, week, day")


class Scope(BaseModel):
    job_summary: str = Field(description="One sentence describing the whole job")
    items: list[ScopeItem]


class Choice(BaseModel):
    item_index: int = Field(description="Index of the scope item this choice answers")
    price_item_id: int | None = Field(description="id of one of the offered candidates, or null if none fits")
    confidence: Literal["high", "medium", "low"]
    reason: str


class Choices(BaseModel):
    choices: list[Choice]


class QuoteLine(BaseModel):
    description: str
    qty: float
    unit: str
    price_item_id: int | None
    sku: str | None
    item_name: str | None
    unit_price: float | None
    line_total: float
    confidence: str
    flags: list[str] = []


class Draft(BaseModel):
    job_summary: str
    lines: list[QuoteLine]
    subtotal: float
    margin_pct: float
    total: float
    flags: list[str]
    needs_attention: bool
    comparables: list[dict]


class BoundedScopeItem(ScopeItem):
    description: str = Field(max_length=200, description="One buildable scope item")
    qty: float = Field(gt=0, le=100000)


class BoundedScope(Scope):
    items: list[BoundedScopeItem] = Field(max_length=40)
