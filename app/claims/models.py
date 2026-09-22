from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

Role = Literal['policy', 'claim', 'invoice']


class Evidence(BaseModel):
    page: int
    passage: str
    start: int
    end: int


class ExtractedField(BaseModel):
    value: str | None = None
    status: Literal['known', 'missing', 'unparseable', 'ambiguous'] = 'missing'
    evidence: list[Evidence] = Field(default_factory=list)


class Document(BaseModel):
    role: Role
    filename: str
    sha256: str | None = None
    status: Literal['ready', 'missing', 'unsupported', 'invalid', 'partial']
    issues: list[str] = Field(default_factory=list)
    pages: list[str] = Field(default_factory=list)
    fields: dict[str, ExtractedField] = Field(default_factory=dict)


class Finding(BaseModel):
    code: str
    title: str
    status: Literal['consistent', 'conflict', 'unknown']
    detail: str
    inputs: list[str]
    uses_reviewer_input: bool = False


class Correction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Role
    field: str = Field(min_length=1, max_length=80)
    value: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=3, max_length=1000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)
    reviewer: str = Field(min_length=1, max_length=100)
    notes: str = Field(default='', max_length=5000)
    status: Literal['in_review', 'needs_information', 'review_recorded'] = 'in_review'
    corrections: list[Correction] = Field(default_factory=list, max_length=100)


class ReviewSnapshot(BaseModel):
    rules_version: str = 'claims-consistency-1.0'
    revision: int
    created_at: str
    reviewer: str
    notes: str
    status: str
    corrections: list[Correction]
    findings: list[Finding]


class CaseView(BaseModel):
    id: str
    title: str
    fictional: bool
    created_at: str
    revision: int
    documents: list[Document]
    findings: list[Finding]
    review: ReviewSnapshot | None = None
    limitations: str = ('Document consistency checks only. No coverage, fraud, eligibility, or claim approval/rejection decision. '
                       'Text extraction is not proof of authenticity. Reviewer inputs are not document-verified facts.')
