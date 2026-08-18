from app.config import Settings


def test_release_debug_environment_value_is_treated_as_disabled():
    settings = Settings(_env_file=None, debug="release")
    assert settings.debug is False


def test_development_debug_environment_value_is_treated_as_enabled():
    settings = Settings(_env_file=None, debug="development")
    assert settings.debug is True
