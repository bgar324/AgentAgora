from pydantic import BaseModel, Field


class ClusterConfig(BaseModel):
    min_cluster_size: int = 30
    min_samples: int = 1
    cluster_selection_method: str = "leaf"

    n_neighbors: int = 15
    n_components: int = 10
    min_dist: float = 0.0
    random_state: int = 42


class TopicConfig(BaseModel):
    ngram_range: tuple[int, int] = (1, 3)
    min_papers: int = 3
    n_terms: int = 10
    stop_words: str | list[str] | None = "english"


class RepresentativeConfig(BaseModel):
    n_central: int = 3
    n_diverse: int = 2


class LiteratureConfig(BaseModel):
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    topic: TopicConfig = Field(default_factory=TopicConfig)
    representatives: RepresentativeConfig = Field(
        default_factory=RepresentativeConfig
    )
