from pydantic import BaseModel


class DiscoveryConfig(BaseModel):
    n_seeds: int = 2
    max_fields: int = 2
    passage_limit: int = 12


class SearchConfig(BaseModel):
    search_limit: int = 1_000
    corpus_size: int = 1_000
    batch_size: int = 500

    year: str | None = "2022-"
    min_citations: int = 0
