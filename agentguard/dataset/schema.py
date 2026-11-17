"""Dataset rows and labels, per data/labeling_rules.md.

A Row is what a guard sees (an ActionProposal) plus bookkeeping. Labels live separately in
an append-only file, so relabeling never rewrites the rows and history is kept.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentguard.agent.tools import TOOL_SCHEMAS
from agentguard.guard.schemas import ActionProposal, RiskCategory

ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"
VERSION_PATTERN = r"^\d+\.\d+$"
MAX_HISTORY = 5

TOOL_INPUTS: dict[str, dict[str, Any]] = {t["name"]: t["input_schema"] for t in TOOL_SCHEMAS}

Label = Literal["safe", "unsafe", "excluded"]


def _type_ok(value: Any, spec: dict[str, Any]) -> bool:
    if spec.get("type") == "string":
        return isinstance(value, str) and ("enum" not in spec or value in spec["enum"])
    if spec.get("type") == "array":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    return True


class Row(BaseModel):
    """One proposed action, unlabeled. Stored in data/raw/<source>.jsonl."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    source: str = Field(pattern=r"^[a-z0-9-]+$")
    task: str = Field(min_length=1)
    history: list[str] = Field(default_factory=list, max_length=MAX_HISTORY)
    tool: str
    args: dict[str, Any]
    # Source details and any suggested label. Never shown while labeling.
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool")
    @classmethod
    def _known_tool(cls, tool: str) -> str:
        if tool not in TOOL_INPUTS:
            raise ValueError(f"unknown tool {tool!r}; expected one of {sorted(TOOL_INPUTS)}")
        return tool

    @model_validator(mode="after")
    def _args_match_tool(self) -> Self:
        schema = TOOL_INPUTS[self.tool]
        properties = schema["properties"]
        missing = set(schema["required"]) - set(self.args)
        unknown = set(self.args) - set(properties)
        if missing or unknown:
            raise ValueError(
                f"{self.tool} args: missing {sorted(missing)}, unknown {sorted(unknown)}"
            )
        bad = [k for k, v in self.args.items() if not _type_ok(v, properties[k])]
        if bad:
            raise ValueError(f"{self.tool} args with wrong type or value: {sorted(bad)}")
        return self

    def proposal(self) -> ActionProposal:
        """Exactly what a guard backend is given."""
        return ActionProposal(task=self.task, history=self.history, tool=self.tool, args=self.args)

    def fingerprint(self) -> str:
        """Identical actions in identical context share a fingerprint (duplicate check)."""
        content = json.dumps(self.proposal().model_dump(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()


class LabelRecord(BaseModel):
    """One labeling decision. Stored in data/labeled/labels.jsonl; the latest per id wins."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    label: Label
    category: RiskCategory | None = None
    secondary_category: RiskCategory | None = None
    imitates: RiskCategory | None = None
    ambiguous: bool = False
    notes: str = ""
    rules_version: str = Field(pattern=VERSION_PATTERN)
    labeled_at: str

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.label == "unsafe":
            if self.category is None:
                raise ValueError("unsafe rows need a category")
            if self.imitates is not None:
                raise ValueError("imitates is for safe rows only")
            if self.secondary_category == self.category:
                raise ValueError("secondary_category must differ from category")
        else:
            if self.category is not None or self.secondary_category is not None:
                raise ValueError(f"{self.label} rows take no category or secondary_category")
        if self.label == "excluded":
            if self.imitates is not None or self.ambiguous:
                raise ValueError("excluded rows take no imitates or ambiguous")
            if not self.notes.strip():
                raise ValueError("excluded rows need a reason in notes (rules section 7)")
        if self.ambiguous and not self.notes.strip():
            raise ValueError("ambiguous rows need a note")
        return self

    @property
    def hard_negative(self) -> bool:
        return self.label == "safe" and self.imitates is not None


class LabeledRow(Row):
    """A row merged with its latest label. This is what goes into the splits."""

    label: Label
    category: RiskCategory | None = None
    secondary_category: RiskCategory | None = None
    imitates: RiskCategory | None = None
    ambiguous: bool = False
    notes: str = ""
    rules_version: str
    labeled_at: str

    @classmethod
    def merge(cls, row: Row, record: LabelRecord) -> LabeledRow:
        fields = record.model_dump(exclude={"id"})
        return cls(**row.model_dump(), **fields)

    @property
    def hard_negative(self) -> bool:
        return self.label == "safe" and self.imitates is not None
