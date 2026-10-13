"""Every cog imports: a broken import is found here instead of when the bot starts."""

import importlib
import pkgutil

import pytest

import cogs


def _modules():
    return sorted(
        info.name for info in pkgutil.walk_packages(cogs.__path__, prefix="cogs.") if not info.ispkg
    )


@pytest.mark.parametrize("name", _modules())
def test_cog_imports_and_has_setup(name):
    module = importlib.import_module(name)
    assert callable(getattr(module, "setup", None)), f"{name} has no setup(bot)"
