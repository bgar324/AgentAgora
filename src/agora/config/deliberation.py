from typing import Literal

from pydantic import BaseModel, Field


class DeliberationConfig(BaseModel):
    search_method: Literal[
        "vector",
        "keyword",
        "hybrid",
    ] = "hybrid"
    evidence_limit: int = Field(default=2, ge=1)
    max_parallel: int = Field(default=3, ge=1)
