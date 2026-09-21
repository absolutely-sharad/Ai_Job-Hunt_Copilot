"""Structured representation of a parsed job description."""

from typing import Literal

from pydantic import BaseModel, Field

Seniority = Literal["intern", "entry", "mid", "senior", "staff", "unknown"]


class SkillRequirement(BaseModel):
    skill: str = Field(description="A single concrete skill or technology.")
    importance: Literal["required", "preferred"] = "required"
    context: str = Field(
        default="",
        description="Short phrase describing how the role uses this skill.",
    )


class JobDescription(BaseModel):
    """LLM-extracted structure from raw job description text."""

    title: str = "Unknown Role"
    company: str = "Unknown Company"
    seniority: Seniority = "unknown"
    location: str = ""
    responsibilities: list[str] = Field(default_factory=list, max_length=15)
    requirements: list[SkillRequirement] = Field(default_factory=list, max_length=25)
    ats_keywords: list[str] = Field(
        default_factory=list,
        max_length=30,
        description="Exact keywords an ATS would scan for in a resume.",
    )
