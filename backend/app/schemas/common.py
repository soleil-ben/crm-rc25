"""Shared response envelopes and enum payloads."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class ErrorResponse(BaseModel):
    code: str
    message: str
    field: str | None = None
    detail: dict = Field(default_factory=dict)


class EnumOption(BaseModel):
    value: str
    label: str
    description: str | None = None


class OkResponse(BaseModel):
    ok: bool = True
    message: str | None = None
