# x402-prediction-trading-agent

**Trading agents that pay for their own intelligence.**

This repository demonstrates how to build AI trading agents that autonomously pay for data feeds using the [x402 protocol](https://www.x402.org/). It's a reference implementation extracted from [Simmer](https://simmer.markets), showing the patterns for both **consuming** and **providing** x402 APIs.

## What is x402?

x402 is an HTTP-native micropayment protocol. When an AI agent requests a resource, the server can return a `402 Payment Required` response with payment details. The agent pays (on Base mainnet with USDC) and immediately gets the data.

```
Agent Request → 402 Response (price, address) → Payment → Data
```

No API keys. No subscriptions. No human approval needed.

## Architecture

This implementation has two sides:

### Consumer: Agents Paying for Data

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Trading Agent  │────▶│  BaseOnlyTransport│────▶│   x402 API      │
│  (has wallet)   │     │  (handles 402s)   │     │  (weather, news)│
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                        │
        │                        ▼
        │               ┌──────────────────┐
        └──────────────▶│  Tool Discovery  │
                        │  (ZAUTHX402)     │
                        └──────────────────┘
```

### Provider: Selling Forecasts

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  External Agent │────▶│  x402 Middleware │────▶│  Simmer API     │
│  (pays USDC)    │     │  (@x402/express) │     │  (forecasts)    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Key Components

### 1. Agent Wallet System (`simmer_v3/agent_wallet.py`)

Each trading agent gets its own wallet on Base:

```python
from eth_account import Account
from cryptography.fernet import Fernet

# Generate wallet for agent
account = Account.create()
private_key = account.key.hex()

# Encrypt at rest (AES-128)
fernet = Fernet(os.environ['AGENT_KEY_ENCRYPTION_SECRET'])
encrypted_key = fernet.encrypt(private_key.encode())

# Store encrypted key in database
# Agent can now pay for x402 APIs autonomously
```

### 2. x402 Consumer (`simmer_v3/agentic_tools.py`)

The `BaseOnlyTransport` handles 402 responses automatically:

```python
class BaseOnlyTransport(httpx.AsyncHTTPTransport):
    """Custom transport that handles x402 payment flow."""

    async def handle_async_request(self, request):
        response = await super().handle_async_request(request)

        if response.status_code == 402:
            # Parse payment requirements
            body = json.loads(await response.aread())
            price = body['accepts'][0]['maxAmountRequired']
            address = body['accepts'][0]['resource']

            # Pay via Base mainnet USDC
            payment = await self.pay_x402(price, address)

            # Retry with payment proof
            request.headers['X-PAYMENT'] = payment
            return await super().handle_async_request(request)

        return response
```

### 3. Tool Discovery (`consumer/x402_consumer.py`)

Discovers available x402 tools from [ZAUTHX402](https://zauthx402.com) - a live registry of verified x402 endpoints:

```python
DISCOVERY_URL = "https://back.zauthx402.com/api/x402/endpoints"

async def discover_tools() -> List[Tool]:
    """Fetch available x402 tools from ZAUTHX402."""
    params = {
        "status": "WORKING",  # Only verified working endpoints
        "network": "base",     # Base mainnet only
        "limit": 100
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(DISCOVERY_URL, params=params)
        data = resp.json()

    return [Tool(
        id=t['id'],
        name=t['title'],
        url=t['url'],
        price_usd=float(t['lastPriceUsdc']),  # Already in USD
        method=t['method'],
        network=t['network']
    ) for t in data['endpoints']]
```

### 4. x402 Provider (`website/x402-provider/`)

Express middleware that gates API endpoints:

```javascript
import { paymentMiddleware } from '@x402/express';
import { x402facilitator } from '@coinbase/x402';

const facilitator = new x402facilitator({
  payToAddress: process.env.SIMMER_TREASURY_ADDRESS,
  network: 'base-mainnet',
});

// Gate the forecast endpoint
app.get('/api/forecast/:marketId',
  paymentMiddleware(facilitator, {
    price: '$0.01',
    currency: 'USDC',
  }),
  async (req, res) => {
    const forecast = await getMarketForecast(req.params.marketId);
    res.json(forecast);
  }
);
```

### 5. Trading Loop (`simmer_v3/scheduler.py`)

The agent cycle that ties it together:

```python
async def run_agent_cycle(agent_id: str, market_id: str):
    # 1. Load agent with wallet
    agent = load_agent(agent_id)
    wallet = decrypt_wallet(agent.encrypted_private_key)

    # 2. Discover available tools for this market
    tools = await discover_tools_for_market(market_id)

    # 3. Let LLM decide which tools to call
    tool_calls = await llm_decide_tools(agent, market, tools)

    # 4. Execute tools (agent pays via x402)
    results = await execute_tools(tool_calls, wallet)

    # 5. LLM reasons about data → trading decision
    decision = await llm_trade_decision(agent, market, results)

    # 6. Execute trade
    if decision.action != 'hold':
        execute_trade(market_id, decision)
```

## Can I Fork and Run This?

**Short answer: Not directly.** This is a reference implementation, not a standalone tool.

The x402 integration is tightly coupled with Simmer's:
- Database schema (agents, markets, positions)
- Scheduler system (APScheduler)
- Agent wallet encryption
- Market/trading engine

**What you CAN do:**

1. **Study the patterns** - The code shows exactly how to implement x402 consumer + provider
2. **Extract components** - `BaseOnlyTransport` and tool discovery are relatively portable
3. **Build your own** - Use this as a blueprint for your x402-enabled application

If you want to experiment with x402 directly:

```bash
# Install x402 SDK
pip install x402-python

# Basic x402 consumer
from x402 import X402Client

client = X402Client(private_key="0x...")
response = await client.get("https://some-x402-api.com/data")
```

## Environment Variables

```bash
# Agent wallet encryption
AGENT_KEY_ENCRYPTION_SECRET=<fernet-key>

# x402 provider treasury
SIMMER_TREASURY_ADDRESS=0x...

# LLM for agent reasoning
OPENROUTER_API_KEY=<key>
```

## Technologies

- **x402 Python SDK** - Consumer payments
- **@x402/express + @coinbase/x402** - Provider middleware
- **eth_account** - Wallet generation
- **cryptography (Fernet)** - Key encryption at rest
- **Base mainnet** - USDC payments
- **httpx** - Async HTTP with custom transport

## Links

- **Live app**: https://simmer.markets
- **x402 Protocol**: https://www.x402.org/
- **x402 SDK**: https://github.com/coinbase/x402
- **ZAUTHX402 Registry**: https://zauthx402.com (tool discovery database)

## License

MIT
