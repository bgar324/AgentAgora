from pydantic import BaseModel, Field


class LiteratureAnnotation(BaseModel):
    summary: str = Field(
        description=(
            "The contribution the papers share and the boundary on it. Where "
            "they share no single contribution, say that the literature is "
            "mixed and give the common concern that remains."
        )
    )
    subthemes: list[str] = Field(
        min_length=1,
        max_length=2,
        description=(
            "The separate lines of work inside this literature, each covering "
            "several papers. One subtheme means the papers form a single line."
        ),
    )
    findings: list[str] = Field(
        min_length=2,
        max_length=4,
        description=(
            "What recurs across several papers, carrying the populations, "
            "settings, comparisons, and conditions it was reported under, "
            "along with any uncertainty, null, or mixed result."
        ),
    )
    methods: list[str] = Field(
        min_length=1,
        max_length=3,
        description=(
            "The families of study design, data source, measure, or analysis "
            "that set what this literature can establish. Name the family "
            "rather than the particular instrument, system, dataset, or "
            "benchmark one study used."
        ),
    )
    gaps: list[str] = Field(
        min_length=1,
        max_length=3,
        description=(
            "The specific boundaries where this literature runs out of "
            "evidence, each named as the thing left unestablished rather than "
            "as a general call for future work."
        ),
    )


class ResearchDomain(BaseModel):
    cluster_id: str
    label: str
    literature: LiteratureAnnotation


class Observation(BaseModel):
    id: str
    text: str
    source_id: str
    location: str | None = None


class PerspectiveFacets(BaseModel):
    scope: str | None = None
    explanation: str | None = None
    approach: str | None = None
    significance: str | None = None


class Perspective(BaseModel):
    framing: str
    position: str


class ResearcherProfile(BaseModel):
    name: str = ""
    focus: str
    facets: PerspectiveFacets
    perspective: Perspective


class PerspectiveFormationResult(BaseModel):
    cluster_id: str
    domain: ResearchDomain | None = None
    profile: ResearcherProfile | None = None
