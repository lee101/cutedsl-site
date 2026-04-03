## Overview
CuteDSL Site - A fairy-themed AI model platform powered exclusively by $CUTE token on Solana. Users connect their Solana wallet, deposit $CUTE tokens, and use AI services (image generation, time series forecasting, TTS, STT) with credits deducted based on current $CUTE valuation.

## Architecture

### Frontend (Next.js)
- `frontend/` - Next.js 15 + React 19 + Tailwind CSS 4
- Wallet connect (Phantom or manual address entry)
- Live $CUTE pricing from backend API
- Deposit flow with Solana Pay URLs + SSE status updates
- Service pricing cards with live conversion

### Backend (Go + FastHTTP)
- `server/` - Go server with SQLite database
- Crypto-only payment system (no Stripe) - $CUTE token on Solana
- HD wallet derivation for unique deposit addresses per payment
- Price feeds from CoinGecko (SOL) and Bags API ($CUTE)
- Background services: payment poller, sweeper, expired checkout cleaner
- AI service proxying with credit deduction and automatic refunds on failure

### Key Files
- `server/main.go` - Entry point, routes, static file serving
- `server/crypto.go` - $CUTE payments, HD wallet, price feeds, Solana RPC
- `server/services.go` - AI service handlers, pricing, backend proxying
- `server/db.go` - SQLite database (users, billing events, checkout intents)
- `server/models.go` - Data models
- `frontend/app/page.tsx` - Main page with wallet connect, pricing, deposit UI

## Key Commands

### Development
```bash
# Install dependencies
make install

# Run frontend (port 3000)
make frontend

# Run backend (port 8080)
make server

# Build everything
make build
```

### API Endpoints
- `POST /api/auth/wallet` - Register/login by wallet address
- `GET /api/balance?wallet=...` - Get $CUTE balance
- `POST /api/crypto-checkout` - Create deposit intent
- `GET /api/crypto-checkout/:id` - Get checkout status
- `GET /api/crypto-checkout/:id/events` - SSE stream for payment status
- `GET /api/cute-price` - Current $CUTE and SOL prices
- `GET /api/pricing` - All service pricing in USD and $CUTE
- `POST /api/service` - Use an AI service (deducts credits)
- `GET /api/billing-history?wallet=...` - Transaction history

## Environment Variables
See `.env` for all configuration. Key vars:
- `SOLANA_PRIVATE_KEY`, `SOL_ADDR`, `HD_WALLET_SEED` - Solana wallet
- `HELIUS_API_KEY` - Solana RPC (high rate limit)
- `BAGS_API_KEY` - $CUTE price feed
- `CUTE_TOKEN_MINT` - $CUTE SPL token address
- `*_BACKEND_URL` - AI service backend URLs
- `*_PRICE_USD` - Service pricing in USD

## Related Projects
- `../cutedsl` - CuteDSL ML acceleration framework (cutechronos, cutezimage, etc.)
- `../codex-infinity-site` - Reference for crypto payment patterns
