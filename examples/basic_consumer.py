"""
Basic x402 Consumer Example

This script demonstrates the simplest way to use x402:
1. Create a client with your wallet
2. Make a request to an x402 API
3. Payment is handled automatically

Run with:
    AGENT_WALLET_KEY=0x... python basic_consumer.py
"""

import os
import asyncio
import httpx
from x402.clients.httpx import x402HttpxClient

# Your wallet private key (funded with USDC on Base)
WALLET_KEY = os.environ.get("AGENT_WALLET_KEY")

# Example x402 API endpoint
EXAMPLE_API = "https://api.example.com/search"


async def main():
    if not WALLET_KEY:
        print("Set AGENT_WALLET_KEY environment variable")
        print("Example: export AGENT_WALLET_KEY=0x...")
        return

    # Create x402-enabled HTTP client
    async with httpx.AsyncClient() as base_client:
        client = x402HttpxClient(base_client, WALLET_KEY)

        # Make request - payment happens automatically if API returns 402
        response = await client.get(
            EXAMPLE_API,
            params={"q": "prediction markets"}
        )

        if response.status_code == 200:
            print("Success!")
            print(response.json())
        else:
            print(f"Error: {response.status_code}")
            print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
