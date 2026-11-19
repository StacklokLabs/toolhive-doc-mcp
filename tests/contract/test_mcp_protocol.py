"""Contract tests for the MCP tool definitions exposed by the server"""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from src.config import config
from src.mcp_server import mcp

EXPECTED_TITLES = {
    "query_docs": "Search Stacklok Docs",
    "get_chunk": "Get Documentation Chunk",
}


@pytest.fixture
async def client():
    async with Client(mcp) as client:
        yield client


@pytest.fixture
async def tools(client):
    return {tool.name: tool for tool in await client.list_tools()}


async def test_server_reports_configured_version(client):
    """serverInfo carries the configured version, not a hardcoded one"""
    assert client.server_info.version == config.server_version


class TestToolDefinitions:
    """Verify what clients see in tools/list"""

    async def test_expected_tools(self, tools):
        assert set(tools) == set(EXPECTED_TITLES)

    @pytest.mark.parametrize("name", sorted(EXPECTED_TITLES))
    async def test_annotations(self, tools, name):
        tool = tools[name]
        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is True
        assert annotations.idempotent_hint is True
        assert annotations.open_world_hint is False
        assert tool.title == EXPECTED_TITLES[name]
        assert annotations.title == EXPECTED_TITLES[name]

    async def test_query_docs_input_schema_bounds(self, tools):
        props = tools["query_docs"].input_schema["properties"]
        assert props["query"]["minLength"] == 1
        assert props["limit"]["minimum"] == 1
        assert props["limit"]["maximum"] == 50
        assert props["query_type"]["enum"] == ["semantic", "keyword", "hybrid"]
        min_score = next(s for s in props["min_score"]["anyOf"] if s.get("type") == "number")
        assert min_score["minimum"] == 0.0
        assert min_score["maximum"] == 1.0

    async def test_query_docs_has_output_schema(self, tools):
        assert tools["query_docs"].output_schema is not None


class TestInputValidation:
    """Out-of-bounds input is rejected before the tool touches the database"""

    @pytest.mark.parametrize(
        "arguments",
        [
            {"query": ""},
            {"query": "toolhive", "limit": 0},
            {"query": "toolhive", "limit": 51},
            {"query": "toolhive", "query_type": "fuzzy"},
            {"query": "toolhive", "min_score": 1.5},
        ],
    )
    async def test_query_docs_rejects_invalid_input(self, client, arguments):
        with pytest.raises(ToolError, match="validation error"):
            await client.call_tool("query_docs", arguments)
