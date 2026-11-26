"""Tunable limits for retrieval, caching, and matching; overridable per environment.

Environment overrides use PYTHON_DOCS_<FIELD_NAME>; sizes are bytes.
"""

from typing import Annotated, NamedTuple, Self

from pydantic import (
    AllowInfNan,
    Field,
    NonNegativeFloat,
    PositiveFloat,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from python_agent_tools_core.exception import InvalidVersionError
from python_agent_tools_core.version import PythonVersion, create_python_version

from python_docs_mcp.core.exception import CapacityError

PositiveSeconds = Annotated[PositiveFloat, AllowInfNan(allow_inf_nan=False)]
NonNegativeSeconds = Annotated[NonNegativeFloat, AllowInfNan(allow_inf_nan=False)]
CacheTTL = Annotated[PositiveSeconds, Field(le=24 * 60 * 60)]
MatchScore = Annotated[float, Field(ge=0, le=100)]
Ratio = Annotated[float, Field(ge=0, le=1)]
PositiveCount = Annotated[int, Field(gt=0)]
NonNegativeCount = Annotated[int, Field(ge=0)]


class CapacityRule(NamedTuple):
    larger: str
    smaller: str


CAPACITY_RULES = (
    CapacityRule('page_cache_bytes', 'download_max_bytes'),
    CapacityRule('section_cache_characters', 'download_max_bytes'),
    CapacityRule('download_max_bytes', 'download_chunk_bytes'),
    CapacityRule('http_max_connections', 'http_max_keepalive_connections'),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='PYTHON_DOCS_', frozen=True, extra='forbid')

    download_max_bytes: PositiveCount = 8 * pow(1024, 2)
    inventory_max_bytes: PositiveCount = 16 * pow(1024, 2)
    inventory_max_entries: PositiveCount = 100_000
    max_malformed_entry_ratio: Ratio = 0.02
    indexed_sections: tuple[str, ...] = ('library', 'builtins', 'reference')
    download_chunk_bytes: PositiveCount = 64 * 1024
    inventory_cache_versions: PositiveCount = 8
    page_cache_bytes: PositiveCount = 32 * pow(1024, 2)
    section_cache_characters: PositiveCount = 16 * pow(1024, 2)
    cache_ttl_seconds: CacheTTL = 24 * 60 * 60
    missing_version_ttl_seconds: CacheTTL = 5 * 60
    fuzzy_score_cutoff: MatchScore = 80
    suggestion_count: PositiveCount = 3
    download_concurrency: PositiveCount = 4
    parse_concurrency: PositiveCount = 2
    request_timeout_seconds: PositiveSeconds = 20
    connect_timeout_seconds: PositiveSeconds = 5
    fill_timeout_seconds: PositiveSeconds = 40
    call_timeout_seconds: PositiveSeconds = 45
    shutdown_timeout_seconds: PositiveSeconds = 5
    http_max_connections: PositiveCount = 4
    http_max_keepalive_connections: NonNegativeCount = 4
    http_keepalive_expiry_seconds: NonNegativeSeconds = 5
    pool_timeout_seconds: PositiveSeconds = 5
    completion_floor_version: str = '3.10'
    completion_ceiling_version: str = '3.15'

    @field_validator('completion_floor_version', 'completion_ceiling_version')
    @classmethod
    def validate_version(cls, text: str) -> str:
        created = create_python_version(text)
        if isinstance(created, InvalidVersionError):
            raise created
        return created.text

    @model_validator(mode='after')
    def validate_capacity(self) -> Self:
        if (broken := next(filter(self.breaks, CAPACITY_RULES), None)) is not None:
            raise CapacityError(broken.larger, broken.smaller)
        return self

    @model_validator(mode='after')
    def validate_completion_window(self) -> Self:
        floor = PythonVersion(text=self.completion_floor_version)
        ceiling = PythonVersion(text=self.completion_ceiling_version)
        if floor.minor > ceiling.minor:
            larger = 'completion_ceiling_version'
            raise CapacityError(larger, 'completion_floor_version')
        return self

    def breaks(self, rule: CapacityRule) -> bool:
        return int(getattr(self, rule.larger)) < int(getattr(self, rule.smaller))
