from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_desktop_usage(tmp_path_factory):
    """Keep a real Claude Desktop install on the dev machine out of the tests."""
    missing = tmp_path_factory.mktemp("desktop") / "plan-usage-history.json"
    with (
        patch("claude_usage.DESKTOP_USAGE_HISTORY", missing),
        patch("claude_usage_cli.DESKTOP_USAGE_HISTORY", missing),
    ):
        yield
