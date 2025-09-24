# defi_scanner_top10_fixed.py
from __future__ import annotations
import json
import requests
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Set
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import time

# ================== CONFIG ================== #
MIN_APY: float = 5.0
MIN_TVL: float = 500_000
MIN_LIQUIDITY: float = 100_000
RESCAN_INTERVAL = 15 * 60  # 15 minutes

FOCUS_PROTOCOLS: Set[str] = {
    "beefy", "yearn", "radiant", "aave", "aave-v3", "venus", "morpho",
    "pancakeswap", "raydium", "lido", "marinade", "eigenlayer",
    "kamino", "krystal", "turbo"
}

LAYER2_CHAINS: Set[str] = {"arbitrum", "optimism", "zksync", "base", "scroll", "linea"}

CHAIN_ID_MAP = {
    1: "eth", 56: "bsc", 101: "sol", 1001: "sui", 108: "tao",
    42161: "arbitrum", 10: "optimism", 8453: "base"
}

MEME_CHAINS: Set[str] = {"sui", "tao", "eth", "bsc", "sol", "base", "optimism", "arbitrum"}

# ================== DATA MODELS ================== #
@dataclass(frozen=True)
class YieldEntry:
    chain: str
    protocol: str
    symbol: str
    type: str
    apy_str: str
    ror: float
    tvl_str: str
    risk: str
    vol_1h_str: str = ""   # optional 1h volume
    vol_24h_str: str = ""  # optional 24h volume

@dataclass(frozen=True)
class MemeEntry:
    symbol: str
    chain: str
    price_usd: str
    liquidity_usd: str
    volume_24h_usd: str
    change_24h_pct: str
    risk: str
    vol_1h_str: str = ""  
    vol_24h_str: str = ""  

# ================== UTILITIES ================== #
def safe_request(url: str) -> Dict[str, Any]:
    try:
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        return {"error": str(e)}

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def risk_score(apy: float, tvl: float, project: str) -> str:
    pj = project.lower()
    if pj in FOCUS_PROTOCOLS:
        return "Low"
    if tvl > 50_000_000 and apy < 15:
        return "Low"
    if 5_000_000 <= tvl <= 50_000_000 and 15 <= apy <= 50:
        return "Medium"
    if tvl < 5_000_000 or apy > 50:
        return "High"
    return "Medium"

def calc_ror(apy: float, score: str) -> float:
    risk_factor: Dict[str, float] = {"Low": 1.0, "Medium": 0.6, "High": 0.3}
    return apy * risk_factor.get(score, 0.5)

# ================== SCANNERS ================== #
def classify_yield_opportunities() -> List[YieldEntry]:
    data = safe_request("https://yields.llama.fi/pools")
    results: List[YieldEntry] = []

    if "error" in data:
        print(f"Yields API error: {data['error']}")
        return results

    pools = data.get("data", [])
    for raw in pools:
        if not isinstance(raw, dict):
            continue
        apy_val = raw.get("apy")
        tvl_val = raw.get("tvlUsd", 0)
        project = str(raw.get("project", "") or "")
        chain = str(raw.get("chain", "N/A") or "N/A").lower()
        symbol = str(raw.get("symbol", "N/A") or "N/A")
        if not isinstance(apy_val, (int, float)) or not isinstance(tvl_val, (int, float)):
            continue
        apy = float(apy_val)
        tvl = float(tvl_val)
        if apy < MIN_APY or tvl < MIN_TVL:
            continue
        score = risk_score(apy, tvl, project)
        ror = calc_ror(apy, score)

        pj = project.lower()
        if pj in FOCUS_PROTOCOLS:
            type_str = "Vault / Auto-compounding"
        elif any(k in pj for k in ["aave", "venus", "morpho", "radiant"]):
            type_str = "Lending / Borrowing"
        elif any(k in pj for k in ["farm", "swap", "raydium", "pancakeswap", "turbo"]):
            type_str = "Yield Farming"
        elif any(k in pj for k in ["stake", "lido", "marinade", "eigenlayer"]):
            type_str = "Staking / Restaking"
        elif "stable" in symbol.lower():
            type_str = "Stablecoin"
        else:
            type_str = "Vault / Auto-compounding"

        entry = YieldEntry(
            chain=chain,
            protocol=project,
            symbol=symbol,
            type=type_str,
            apy_str=f"{apy:.2f}%",
            ror=ror,
            tvl_str=f"${tvl:,.0f}",
            risk=score
        )
        results.append(entry)

    # Deduplicate
    seen: Set[str] = set()
    unique_results = []
    for e in results:
        key = f"{e.chain}_{e.protocol}_{e.symbol}"
        if key not in seen:
            unique_results.append(e)
            seen.add(key)
    return unique_results

# ================== MEME COINS ================== #
def get_meme_coins() -> List[YieldEntry]:
    queries = ["pepe", "doge", "shiba", "floki", "bonk"]
    results: List[YieldEntry] = []

    for q in queries:
        data = safe_request(f"https://api.dexscreener.com/latest/dex/search?q={q}")
        if "error" in data:
            continue
        pairs = data.get("pairs", [])
        for p in pairs:
            if not isinstance(p, dict):
                continue

            chain_id = p.get("chainId", 0)
            chain = CHAIN_ID_MAP.get(chain_id, str(chain_id)).lower()
            if chain not in MEME_CHAINS:
                continue

            base_token = p.get("baseToken", {}) if isinstance(p.get("baseToken", {}), dict) else {}
            symbol = str(base_token.get("symbol", "?") or "?")
            price_usd = safe_float(p.get("priceUsd"))

            liq = safe_float(p.get("liquidity", {}).get("usd"))
            change24h = safe_float(p.get("priceChange", {}).get("h24"))
            holder_spike = safe_int(p.get("holdersChange1h"))

            # Safe volume parsing
            volume_data = p.get("volume", {})
            vol1h = safe_float(volume_data.get("h1"))
            vol24h = safe_float(volume_data.get("h24"))

            if liq < 50_000 or vol24h < 50_000 or price_usd <= 0:
                continue

            risk = "Medium"
            if holder_spike > 100:
                risk = "Low"
            elif change24h < -30:
                risk = "High"

            estimated_apy = max(change24h * 365, 0)
            ror = calc_ror(estimated_apy, risk)

            results.append(YieldEntry(
                chain=chain,
                protocol=symbol,
                symbol=symbol,
                type="Meme Coin",
                apy_str=f"{estimated_apy:.2f}%",
                ror=ror,
                tvl_str=f"${liq:,.0f}",
                risk=risk,
                vol_1h_str=f"${vol1h:,.0f}",
                vol_24h_str=f"${vol24h:,.0f}"
            ))

    results.sort(key=lambda x: x.ror, reverse=True)
    return results[:15]

# ================== FULL SCAN ================== #
def full_defi_scan() -> Dict[str, Any]:
    opportunities = classify_yield_opportunities()
    meme_data = get_meme_coins()

    top_10_ror = sorted(opportunities, key=lambda x: x.ror, reverse=True)[:10]

    categorized: Dict[str, List[YieldEntry]] = {
        "Yield Farming": [], "Vaults / Auto-compounding": [],
        "Staking / Restaking": [], "Lending/Borrowing": [], "Stablecoin": []
    }
    for y in opportunities:
        categorized.setdefault(y.type, []).append(y)

    return {
        "Top 10 ROR": [asdict(e) for e in top_10_ror],
        **{k: [asdict(e) for e in v] for k, v in categorized.items()},
        "Meme Coins": [asdict(m) for m in meme_data]
    }

# ================== PDF GENERATOR ================== #
def generate_pdf(scan_results: Dict[str, Any], filename: str = "defi_report_top10.pdf"):
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    y_pos = height - inch
    c.setFont("Helvetica-Bold", 14)
    c.drawString(inch, y_pos, "DeFi Scan Report")
    y_pos -= 0.5 * inch
    c.setFont("Helvetica", 11)

    # Top 10
    if "Top 10 ROR" in scan_results:
        c.drawString(inch, y_pos, "=== Top 10 by ROR ===")
        y_pos -= 0.25*inch
        for i, item in enumerate(scan_results["Top 10 ROR"]):
            line = f"{i+1}. {item['chain']} | {item['protocol']} | {item['symbol']} | {item.get('type','')} | APY: {item.get('apy_str','')} | ROR: {item.get('ror',0):.2f} | TVL: {item.get('tvl_str','')} | Risk: {item.get('risk','')}"
            c.drawString(inch + 0.25*inch, y_pos, line)
            y_pos -= 0.2*inch
            if y_pos < inch:
                c.showPage()
                y_pos = height - inch
        y_pos -= 0.2*inch

    # Other categories
    for category, items in scan_results.items():
        if category == "Top 10 ROR":
            continue
        c.drawString(inch, y_pos, f"{category} ({len(items)})")
        y_pos -= 0.25*inch
        for i, item in enumerate(items[:10]):
            line = f"{i+1}. {item['chain']} | {item['symbol']} | {item.get('type','')} | APY: {item.get('apy_str','')} | ROR: {item.get('ror',0):.2f} | TVL: {item.get('tvl_str','')} | Risk: {item.get('risk','')}"
            c.drawString(inch + 0.25*inch, y_pos, line)
            y_pos -= 0.2*inch
            if y_pos < inch:
                c.showPage()
                y_pos = height - inch
        y_pos -= 0.2*inch

    # WhatsApp-style summary
    c.showPage()
    y_pos = height - inch
    c.setFont("Helvetica-Bold", 14)
    c.drawString(inch, y_pos, "WhatsApp-style Summary")
    y_pos -= 0.5*inch
    c.setFont("Helvetica", 12)
    summary_lines = [f"{cat}: {len(lst)}" for cat, lst in scan_results.items()]
    for line in summary_lines:
        c.drawString(inch, y_pos, line)
        y_pos -= 0.25*inch
    c.save()

# ================== MAIN ================== #
if __name__ == "__main__":
    while True:
        results = full_defi_scan()
        with open("defi_scan_results_top10.json", "w") as f:
            json.dump(results, f, indent=2)

        # Print Top 10
        print("\n=== TOP 10 by ROR ===")
        for item in results.get("Top 10 ROR", []):
            print(f"{item['chain']} | {item['protocol']} | {item['symbol']} | APY: {item.get('apy_str','')} | ROR: {item.get('ror',0):.2f} | TVL: {item.get('tvl_str','')} | Risk: {item.get('risk','')}")

        # Print other categories
        for category, items in results.items():
            if category == "Top 10 ROR" or not items:
                continue
            print(f"\n=== {category} ({len(items)}) ===")
            for i, item in enumerate(items[:10]):  # limit 10 per category for readability
                print(f"{i+1}. {item['chain']} | {item['symbol']} | {item.get('type','')} | APY: {item.get('apy_str','')} | ROR: {item.get('ror',0):.2f} | TVL: {item.get('tvl_str','')} | Risk: {item.get('risk','')}")

        generate_pdf(results)
        print("\nPDF report generated: defi_report_top10.pdf")

        # Countdown
        print(f"\nNext scan in {RESCAN_INTERVAL // 60} minutes...\n")
        for remaining in range(RESCAN_INTERVAL, 0, -1):
            mins, secs = divmod(remaining, 60)
            print(f"\rRescanning in {mins:02d}:{secs:02d}", end="")
            time.sleep(1)
        print("\nRescanning now...\n")
