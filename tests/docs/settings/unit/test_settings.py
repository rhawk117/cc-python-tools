import pytest
from pydantic import ValidationError
from python_agent_tools_docs.errors import CapacityError
from python_agent_tools_docs.settings import Settings


def first_error(failure: pytest.ExceptionInfo[ValidationError]) -> object:
    return failure.value.errors()[0]['ctx']['error']


class TestDefaults:
    def test_source_defaults_apply_without_environment(self) -> None:
        settings = Settings()
        assert settings.cache_ttl_seconds == 24 * 60 * 60
        assert settings.inventory_cache_versions == 8
        assert settings.page_cache_bytes == 32 * 1024**2
        assert settings.section_cache_characters == 16 * 1024**2
        assert settings.missing_version_ttl_seconds == 5 * 60
        assert settings.download_max_bytes == 8 * 1024**2
        assert settings.inventory_max_bytes == 16 * 1024**2
        assert settings.call_timeout_seconds == 45

    def test_completion_window_defaults(self) -> None:
        settings = Settings()
        assert (settings.completion_floor_version, settings.completion_ceiling_version) == (
            '3.10',
            '3.15',
        )


class TestEnvironment:
    def test_environment_overrides_a_setting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTHON_DOCS_SUGGESTION_COUNT', '7')
        assert Settings().suggestion_count == 7

    def test_environment_moves_the_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTHON_DOCS_COMPLETION_FLOOR_VERSION', '3.12')
        monkeypatch.setenv('PYTHON_DOCS_COMPLETION_CEILING_VERSION', '3.20')
        settings = Settings()
        assert (settings.completion_floor_version, settings.completion_ceiling_version) == (
            '3.12',
            '3.20',
        )

    def test_invalid_environment_value_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTHON_DOCS_SUGGESTION_COUNT', 'many')
        with pytest.raises(ValidationError):
            Settings()


class TestValidation:
    def test_broken_capacity_rule_raises_capacity_error(self) -> None:
        with pytest.raises(ValidationError) as failure:
            Settings(download_max_bytes=1, download_chunk_bytes=2)
        assert isinstance(first_error(failure), CapacityError)

    @pytest.mark.parametrize('text', ['4.1', '3.x', 'latest', '3.', '2.7'])
    def test_malformed_window_end_is_rejected(self, text: str) -> None:
        with pytest.raises(ValidationError):
            Settings(completion_floor_version=text)
        with pytest.raises(ValidationError):
            Settings(completion_ceiling_version=text)

    def test_floor_above_ceiling_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(completion_floor_version='3.14', completion_ceiling_version='3.9')

    def test_equal_ends_are_accepted(self) -> None:
        assert Settings(completion_floor_version='3.9', completion_ceiling_version='3.9')
