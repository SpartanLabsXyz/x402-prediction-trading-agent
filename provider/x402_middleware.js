/**
 * x402 Provider Middleware
 *
 * This module shows how to gate API endpoints with x402 payments.
 * Agents calling your API will automatically pay USDC on Base mainnet.
 *
 * Reference implementation from Simmer (simmer.markets)
 */

import express from 'express';
import { paymentMiddleware } from '@x402/express';
import { Resource } from '@coinbase/x402';

// Your treasury address on Base mainnet (receives payments)
const TREASURY_ADDRESS = process.env.SIMMER_TREASURY_ADDRESS;

if (!TREASURY_ADDRESS) {
  throw new Error('SIMMER_TREASURY_ADDRESS not set');
}

const app = express();
app.use(express.json());

// ==========================================
// PAYMENT CONFIGURATION
// ==========================================

/**
 * Create a payment resource for an endpoint.
 *
 * @param {string} price - Price in USD (e.g., "$0.01")
 * @param {string} description - What the agent is paying for
 */
function createPaymentResource(price, description) {
  return new Resource({
    network: 'base-mainnet',
    payTo: TREASURY_ADDRESS,
    maxAmount: price,
    asset: 'USDC',
    description: description,
  });
}

// ==========================================
// PROTECTED ENDPOINTS
// ==========================================

/**
 * Example: Market forecast endpoint
 *
 * Agents pay $0.01 to get the current forecast for a market.
 */
app.get(
  '/api/forecast/:marketId',
  paymentMiddleware(createPaymentResource('$0.01', 'Market forecast')),
  async (req, res) => {
    const { marketId } = req.params;

    // Your forecast logic here
    const forecast = await getMarketForecast(marketId);

    res.json({
      market_id: marketId,
      p_yes: forecast.probability,
      confidence: forecast.confidence,
      reasoning: forecast.reasoning,
      updated_at: new Date().toISOString(),
    });
  }
);

/**
 * Example: Ensemble forecast (higher value, higher price)
 *
 * Agents pay $0.05 for a multi-model ensemble forecast.
 */
app.get(
  '/api/ensemble/:marketId',
  paymentMiddleware(createPaymentResource('$0.05', 'Ensemble forecast')),
  async (req, res) => {
    const { marketId } = req.params;

    const ensemble = await getEnsembleForecast(marketId);

    res.json({
      market_id: marketId,
      p_yes: ensemble.probability,
      confidence: ensemble.confidence,
      model_forecasts: ensemble.models,
      agreement_score: ensemble.agreement,
      updated_at: new Date().toISOString(),
    });
  }
);

/**
 * Example: Search endpoint
 *
 * Agents pay $0.001 per search query.
 */
app.get(
  '/api/search',
  paymentMiddleware(createPaymentResource('$0.001', 'Search query')),
  async (req, res) => {
    const { q, limit = 10 } = req.query;

    const results = await searchMarkets(q, parseInt(limit));

    res.json({
      query: q,
      results: results,
      count: results.length,
    });
  }
);

// ==========================================
// FREE ENDPOINTS (no payment required)
// ==========================================

/**
 * Health check (free)
 */
app.get('/health', (req, res) => {
  res.json({ status: 'ok', treasury: TREASURY_ADDRESS });
});

/**
 * List available markets (free - discovery)
 */
app.get('/api/markets', async (req, res) => {
  const markets = await listMarkets();
  res.json({ markets });
});

// ==========================================
// MOCK IMPLEMENTATIONS
// ==========================================

async function getMarketForecast(marketId) {
  // Replace with your actual forecast logic
  return {
    probability: 0.65,
    confidence: 0.8,
    reasoning: 'Based on current market data and sentiment analysis...',
  };
}

async function getEnsembleForecast(marketId) {
  // Replace with your actual ensemble logic
  return {
    probability: 0.62,
    confidence: 0.85,
    models: [
      { model: 'gpt-4', p_yes: 0.60 },
      { model: 'claude-3', p_yes: 0.65 },
      { model: 'llama-3', p_yes: 0.61 },
    ],
    agreement: 0.92,
  };
}

async function searchMarkets(query, limit) {
  // Replace with your actual search logic
  return [
    { id: 'market_1', title: 'Will BTC reach $100k?', p_yes: 0.45 },
    { id: 'market_2', title: 'Will ETH flip BTC?', p_yes: 0.12 },
  ].slice(0, limit);
}

async function listMarkets() {
  // Replace with your actual market listing
  return [
    { id: 'market_1', title: 'Will BTC reach $100k?', status: 'active' },
    { id: 'market_2', title: 'Will ETH flip BTC?', status: 'active' },
  ];
}

// ==========================================
// SERVER
// ==========================================

const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
  console.log(`x402 Provider running on port ${PORT}`);
  console.log(`Treasury: ${TREASURY_ADDRESS}`);
  console.log('\nProtected endpoints:');
  console.log('  GET /api/forecast/:marketId  ($0.01)');
  console.log('  GET /api/ensemble/:marketId  ($0.05)');
  console.log('  GET /api/search?q=...        ($0.001)');
});

export default app;
