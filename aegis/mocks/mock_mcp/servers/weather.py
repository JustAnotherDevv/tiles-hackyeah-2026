"""`weather` (third_party): clean contrast server - get_weather(city), add(a, b)."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from mocks.mock_mcp.state import STATE

_WEATHER = {"krakow": "14°C, light rain", "kraków": "14°C, light rain", "warsaw": "12°C, cloudy",
            "warszawa": "12°C, cloudy", "gdansk": "11°C, windy", "london": "13°C, drizzle"}


def build() -> MCPServer:
    srv = MCPServer("weather", instructions="Benign demo tools: weather and arithmetic.")

    @srv.tool()
    def get_weather(city: Annotated[str, Field(description="City name, e.g. Krakow")]) -> str:
        """Current weather for a city."""
        STATE.log_call("weather", "get_weather", {"city": city})
        return f"{city}: {_WEATHER.get(city.strip().lower(), '15°C, partly cloudy')}"

    @srv.tool()
    def add(a: int, b: int) -> int:
        """Adds two numbers."""
        STATE.log_call("weather", "add", {"a": a, "b": b})
        return a + b

    return srv
