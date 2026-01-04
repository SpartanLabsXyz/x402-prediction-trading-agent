"""
x402 Consumer Implementation

This module demonstrates how to build an x402-enabled HTTP client that:
1. Discovers available x402 tools from a discovery API
2. Handles 402 Payment Required responses automatically
3. Pays for API calls using USDC on Base mainnet

Reference implementation from Simmer (simmer.markets)
"""

import os
import json
import httpx
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timezone

# x402 SDK for payments
try:
    from x402.clients.httpx import x402HttpxClient
    X402_AVAILABLE = True
except ImportError:
    X402_AVAILABLE = False
    x402HttpxClient = None

from eth_account import Account


# ==========================================
# CONFIGURATION
# ==========================================

# Tool discovery endpoint (x402 Manager - aggregates x402 tools)
DISCOVERY_URL = "https://x402-manager-backend.vercel.app/api/discovery"
DISCOVERY_CACHE_TTL = 3600  # 1 hour

# Tool categories useful for trading agents
USEFUL_CATEGORIES = ["search", "news", "social", "market", "research", "weather", "crypto"]


# ==========================================
# BASE-ONLY TRANSPORT
# ==========================================

class BaseOnlyTransport(httpx.AsyncHTTPTransport):
    """
    Custom HTTP transport that filters x402 402 responses to only include
    payment options for supported networks (Base, Avalanche).

    The x402 Python SDK only supports Base/Avalanche networks, but some tools
    return multi-chain payment options including Solana. This transport
    intercepts 402 responses and removes unsupported options before the SDK
    tries to parse them.

    Also normalizes non-compliant x402 responses (e.g., missing x402Version).
    """

    SUPPORTED_NETWORKS = {'base', 'base-sepolia', 'avalanche', 'avalanche-fuji'}

    def _filter_accepts(self, accepts: list) -> tuple[list, bool]:
        """Filter accepts to only include supported networks."""
        original_count = len(accepts)
        filtered = [
            opt for opt in accepts
            if opt.get('network') in self.SUPPORTED_NETWORKS
        ]
        return filtered, len(filtered) < original_count

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)

        # Only process 402 Payment Required responses
        if response.status_code != 402:
            return response

        modified = False
        new_headers = httpx.Headers(response.headers)
        new_content = None

        # Try header-based filtering (x-payment header with base64-encoded JSON)
        x_payment = response.headers.get('x-payment')
        if x_payment:
            try:
                import base64
                payment_info = json.loads(base64.b64decode(x_payment).decode('utf-8'))
                if 'accepts' in payment_info and isinstance(payment_info['accepts'], list):
                    payment_info['accepts'], was_filtered = self._filter_accepts(payment_info['accepts'])
                    if was_filtered:
                        new_payment = base64.b64encode(json.dumps(payment_info).encode('utf-8')).decode('utf-8')
                        new_headers['x-payment'] = new_payment
                        modified = True
                        print(f"[BaseOnlyTransport] Filtered x-payment header (removed unsupported networks)")
            except Exception as e:
                print(f"[BaseOnlyTransport] Failed to parse x-payment header: {e}")

        # Try body-based filtering (JSON body with accepts array)
        content = await response.aread()
        try:
            body = json.loads(content.decode('utf-8'))

            # Normalize non-standard 402 responses (some servers omit x402Version)
            if 'x402Version' not in body:
                body['x402Version'] = 1
                modified = True
                print(f"[BaseOnlyTransport] Added missing x402Version field")

            if 'accepts' in body and isinstance(body['accepts'], list):
                body['accepts'], was_filtered = self._filter_accepts(body['accepts'])
                if was_filtered:
                    modified = True
                    print(f"[BaseOnlyTransport] Filtered response body (removed unsupported networks)")

            if modified:
                new_content = json.dumps(body).encode('utf-8')
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        if modified:
            from httpx._content import ByteStream
            return httpx.Response(
                status_code=response.status_code,
                headers=new_headers,
                stream=ByteStream(new_content if new_content else content),
                extensions=response.extensions,
            )

        # Return original response with consumed content restored
        from httpx._content import ByteStream
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=ByteStream(content),
            extensions=response.extensions,
        )


# ==========================================
# DATA CLASSES
# ==========================================

@dataclass
class Tool:
    """A callable x402 tool."""
    id: str
    name: str
    description: str
    url: str
    method: str
    price_usd: float
    network: str
    parameters: Dict[str, Any]  # JSON schema for params
    category: str = "other"

    def to_openai_function(self) -> Dict[str, Any]:
        """Convert to OpenAI/OpenRouter function calling format."""
        properties = {}
        required = []

        for param_name, param_info in self.parameters.items():
            prop = {
                "type": param_info.get("type", "string"),
                "description": param_info.get("description", ""),
            }
            if "enum" in param_info:
                prop["enum"] = param_info["enum"]
            if "default" in param_info:
                prop["default"] = param_info["default"]
            if param_info.get("type") == "array":
                prop["items"] = param_info.get("items", {"type": "string"})

            properties[param_name] = prop

            if param_info.get("required", False):
                required.append(param_name)

        return {
            "type": "function",
            "function": {
                "name": self.id,
                "description": f"{self.description} (${self.price_usd:.4f} via x402)",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        }


@dataclass
class ToolCallResult:
    """Result of executing a tool call."""
    tool_id: str
    tool_name: str
    arguments: Dict[str, Any]
    success: bool
    response: Any = None
    error: Optional[str] = None
    cost_usd: float = 0.0
    duration_ms: int = 0


# ==========================================
# TOOL DISCOVERY
# ==========================================

class ToolCatalog:
    """Fetches and caches x402 tools from discovery API."""

    _cache: Optional[List[Tool]] = None
    _cache_time: Optional[datetime] = None

    async def get_tools(self, force_refresh: bool = False) -> List[Tool]:
        """Fetch tools from discovery API with caching."""
        now = datetime.now(timezone.utc)

        # Check cache
        if not force_refresh and self._cache and self._cache_time:
            age = (now - self._cache_time).total_seconds()
            if age < DISCOVERY_CACHE_TTL:
                return self._cache

        # Fetch from discovery API
        tools = []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(DISCOVERY_URL, params={"limit": 100, "offset": 0})
                data = resp.json()

                for item in data.get("items", []):
                    tool = self._parse_tool(item)
                    if tool:
                        tools.append(tool)

            # Deduplicate by tool_id
            seen_ids = set()
            deduped_tools = []
            for tool in tools:
                if tool.id not in seen_ids:
                    seen_ids.add(tool.id)
                    deduped_tools.append(tool)
            tools = deduped_tools

            self._cache = tools
            self._cache_time = now
            print(f"[ToolCatalog] Fetched {len(tools)} tools from discovery API")

        except Exception as e:
            print(f"[ToolCatalog] Failed to fetch tools: {e}")
            if self._cache:
                return self._cache
            return []

        return tools

    def _parse_tool(self, item: dict) -> Optional[Tool]:
        """Parse a tool from discovery API response."""
        try:
            # Extract price (in USDC with 6 decimals)
            price_raw = item.get("price", "0")
            if isinstance(price_raw, str):
                price_raw = int(price_raw)
            price_usd = price_raw / 1_000_000  # USDC has 6 decimals

            # Extract parameters
            params = {}
            if "parameters" in item:
                for p in item["parameters"]:
                    params[p["name"]] = {
                        "type": p.get("type", "string"),
                        "description": p.get("description", ""),
                        "required": p.get("required", False),
                    }
                    if "enum" in p:
                        params[p["name"]]["enum"] = p["enum"]

            return Tool(
                id=item.get("id", item.get("name", "unknown")),
                name=item.get("name", "Unknown"),
                description=item.get("description", ""),
                url=item.get("url", ""),
                method=item.get("method", "GET"),
                price_usd=price_usd,
                network=item.get("network", "base"),
                parameters=params,
                category=item.get("category", "other"),
            )
        except Exception as e:
            print(f"[ToolCatalog] Failed to parse tool: {e}")
            return None


# ==========================================
# TOOL EXECUTOR
# ==========================================

class ToolExecutor:
    """Executes x402 tool calls with payment handling."""

    def __init__(self, wallet_private_key: str):
        """
        Initialize executor with a wallet for payments.

        Args:
            wallet_private_key: Hex-encoded private key (with or without 0x prefix)
        """
        if not X402_AVAILABLE:
            raise ImportError("x402 SDK not installed. Run: pip install x402-python")

        self.private_key = wallet_private_key
        self.account = Account.from_key(wallet_private_key)
        print(f"[ToolExecutor] Initialized with wallet: {self.account.address}")

    async def execute(self, tool: Tool, arguments: Dict[str, Any]) -> ToolCallResult:
        """
        Execute a tool call, handling x402 payment automatically.

        Args:
            tool: The tool to call
            arguments: Arguments to pass to the tool

        Returns:
            ToolCallResult with success status, response, and cost
        """
        import time
        start = time.time()

        try:
            # Build URL with query params for GET, body for POST
            if tool.method.upper() == "GET":
                url = tool.url
                params = arguments
                json_body = None
            else:
                url = tool.url
                params = None
                json_body = arguments

            # Create x402-enabled client with BaseOnlyTransport
            transport = BaseOnlyTransport()
            async with httpx.AsyncClient(transport=transport) as base_client:
                client = x402HttpxClient(
                    base_client,
                    self.private_key,
                )

                # Make the request (x402 SDK handles 402 payment automatically)
                if tool.method.upper() == "GET":
                    response = await client.get(url, params=params)
                else:
                    response = await client.post(url, json=json_body)

            duration_ms = int((time.time() - start) * 1000)

            if response.status_code == 200:
                return ToolCallResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    arguments=arguments,
                    success=True,
                    response=response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
                    cost_usd=tool.price_usd,
                    duration_ms=duration_ms,
                )
            else:
                return ToolCallResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    arguments=arguments,
                    success=False,
                    error=f"HTTP {response.status_code}: {response.text[:500]}",
                    duration_ms=duration_ms,
                )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return ToolCallResult(
                tool_id=tool.id,
                tool_name=tool.name,
                arguments=arguments,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )


# ==========================================
# EXAMPLE USAGE
# ==========================================

async def example_usage():
    """Example: Discover tools and execute a search."""

    # 1. Discover available tools
    catalog = ToolCatalog()
    tools = await catalog.get_tools()

    print(f"\nDiscovered {len(tools)} x402 tools:")
    for tool in tools[:5]:
        print(f"  - {tool.name}: ${tool.price_usd:.4f} ({tool.category})")

    # 2. Find a search tool
    search_tools = [t for t in tools if "search" in t.category.lower()]
    if not search_tools:
        print("No search tools available")
        return

    tool = search_tools[0]
    print(f"\nUsing tool: {tool.name}")
    print(f"  URL: {tool.url}")
    print(f"  Price: ${tool.price_usd:.4f}")

    # 3. Execute with payment (requires funded wallet)
    wallet_key = os.environ.get("AGENT_WALLET_KEY")
    if not wallet_key:
        print("\nSet AGENT_WALLET_KEY to execute paid calls")
        return

    executor = ToolExecutor(wallet_key)
    result = await executor.execute(tool, {"query": "prediction market news"})

    if result.success:
        print(f"\nSuccess! Cost: ${result.cost_usd:.4f}")
        print(f"Response: {str(result.response)[:200]}...")
    else:
        print(f"\nFailed: {result.error}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())
