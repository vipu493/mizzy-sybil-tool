# Mizzy Tool — CT Sybil Research Dashboard

On-chain sybil detection for the Concrete ($CT) airdrop.

**Research · Build · Impact** — [@mizzy_web3](https://x.com/mizzy_web3)

## Features

- Fetch **all** CT claims (block-range, bypasses Etherscan 10k cap)
- Multi-claim **sybil collectors**
- **Big single claims**
- ETH **funding chains** (common gas sponsors)
- CT **withdrawal destinations** (many claimers → same wallet = consolidation)
- Skips burn/zero address (`0x000…000`) automatically
- Interactive **network graph**
- English UI · mobile-friendly · CSV exports

## Contracts

| Role | Address |
|------|---------|
| CT Token | `0x5A642BE07e166C3F23EFAb23E47972a68d3E220a` |
| Merkl Distributor | `0x3Ef3D8bA38EBe18DB133cEc108f4D14CE00Dd9Ae` |

## Setup

```bash
pip install streamlit pandas requests networkx pyvis plotly numpy
```

## Run

```bash
python -m streamlit run ct_sybil_dashboard.py --server.port 8015 --server.headless true
```

Open: http://localhost:8015

## Usage

1. Paste your Etherscan API key (or use the default field)
2. Set start block (~`26085000` for CT claims)
3. Enable **funding** + **withdrawal** traces
4. Click **FETCH & ANALYZE**
5. Explore tabs: Top Sybil · Big Claims · Funding · Withdrawals · Graph · Raw

## Notes

- Free Etherscan keys are rate-limited (~3–5 calls/sec). Deep trace takes time.
- Withdrawal tab flags destinations that receive CT from **2+** claim wallets.
- Zero/burn address is excluded from withdrawal clustering.

## License

MIT — use freely, credit appreciated.
