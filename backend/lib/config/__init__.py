"""Configuration management package."""

__all__ = ["ConfigResolver"]


def __getattr__(name: str):
    if name == "ConfigResolver":
        from lib.config.resolver import ConfigResolver

        return ConfigResolver
    raise AttributeError(name)
