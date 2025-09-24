# madlion_defi_scanner.py
from __future__ import annotations

import os
import time
import json
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Set

import requests
from fpdf import FPDF

# ================== CONFIG ================== #
SORT_MODE: str = "ror"             # one of: "apy", "apr", "tvl", "ror"
MIN_APY: float = 5.0
MIN_TVL: float = 500_000
MIN_LIQUIDITY: float = 100_000
REFRESH_MINS: int = 15             # 0 = no refresh

# Telegram (fill these to enable)
TELEGRAM_ENABLED: bool = True
TELEGRAM_BOT_TOKEN: str = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID: str = "YOUR_CHAT_ID"

FOCUSED_PROJECTS: List[str] = ["kamino", "marinade", "krystal"]
MAIN_CHAINS: List[str] = ["solana", "bsc"]
LAYER2_CHAINS: List[str] = ["arbitrum", "optimism", "zksync", "base", "scroll", "linea"]

SEEN_FILE: str = "seen_opportunities.json"
# ============================================ #


# ============ DATA MODELS (type-safe) ============ #
@dataclass(frozen=True)
class YieldEntry:
    project: str
    chain: str
    apy_str: str     # e.g. "12.34%"
    symbol: str
    tvl_str: str     # e.g. "$1,234,567"
    risk: str        # "Low" | "Medium" | "High"
    pool_id: str     # unique identifier from API
    ror: float       # risk-adjusted return numeric

    def apy_value(self) -> float:
        try:
            return float(self.apy_str.replace("%", "").strip())
        except Exception:
            return 0.0

    def tvl_value(self) -> float:
        try:
            return float(self.tvl_str.replace("$", "").replace(",", "").strip())
        except Exception:
            return 0.0


@dataclass(frozen=True)
class MemeEntry:
    symbol: str
    chain: str
    price_usd: str
    liquidity_usd: str
    volume_24h_usd: str
    change_24h_pct: str
    risk: str


# ============ UTILITIES ============ #
def send_telegram(message: str) -> None:
    if not TELEGRAM_ENABLED:
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram not configured: missing token or chat id.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Telegram error: {e}")


def safe_request(url: str) -> Dict[str, Any]:
    try:
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        return res.json()  # type: ignore[assignment]
    except Exception as e:
        return {"error": str(e)}


def risk_score(apy: float, tvl: float, project: str) -> str:
    pj = project.lower()
    if any(f in pj for f in FOCUSED_PROJECTS):
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


def sort_key(entry: YieldEntry) -> float:
    if SORT_MODE == "apy":
        return entry.apy_value()
    if SORT_MODE == "apr":
        return entry.apy_value()
    if SORT_MODE == "tvl":
        return entry.tvl_value()
    return entry.ror


def load_seen() -> Set[str]:
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, list):
                    return set(str(x) for x in raw)
    except Exception:
        pass
    return set()


def save_seen(seen: Set[str]) -> None:
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(seen), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Could not save seen set: {e}")


# ============ CORE SCANNERS ============ #
def classify_yield_opportunities() -> Dict[str, List[YieldEntry]]:
    data = safe_request("https://yields.llama.fi/pools")
    if "error" in data:
        print(f"⚠️ yields.llama.fi error: {data['error']}")
        return {"long_term": [], "short_term": [], "focus": [], "layer2": []}

    pools = data.get("data", [])
    if not isinstance(pools, list):
        pools = []

    long_term: List[YieldEntry] = []
    short_term: List[YieldEntry] = []
    focus: List[YieldEntry] = []
    layer2: List[YieldEntry] = []

    for raw in pools:
        if not isinstance(raw, dict):
            continue

        apy_val = raw.get("apy")
        tvl_val = raw.get("tvlUsd", 0)
        project = str(raw.get("project", "") or "")
        chain = str(raw.get("chain", "N/A") or "N/A").lower()
        symbol = str(raw.get("symbol", "N/A") or "N/A")
        pool_id = str(raw.get("pool", "") or "")

        if not isinstance(apy_val, (int, float)):
            continue
        if not isinstance(tvl_val, (int, float)):
            continue

        apy: float = float(apy_val)
        tvl: float = float(tvl_val)

        if apy < MIN_APY or tvl < MIN_TVL:
            continue

        score = risk_score(apy, tvl, project)
        ror = calc_ror(apy, score)

        entry = YieldEntry(
            project=project,
            chain=chain,
            apy_str=f"{apy:.2f}%",
            symbol=symbol,
            tvl_str=f"${tvl:,.0f}",
            risk=score,
            pool_id=pool_id,
            ror=ror,
        )

        if any(f in project.lower() for f in FOCUSED_PROJECTS):
            focus.append(entry)
        if score == "Low":
            long_term.append(entry)
        else:
            short_term.append(entry)
        if chain in LAYER2_CHAINS:
            layer2.append(entry)

    long_term = sorted(long_term, key=sort_key, reverse=True)[:5]
    short_term = sorted(short_term, key=sort_key, reverse=True)[:5]
    layer2 = sorted(layer2, key=sort_key, reverse=True)[:5]

    return {"long_term": long_term, "short_term": short_term, "focus": focus, "layer2": layer2}


def get_meme_coins() -> List[MemeEntry]:
    # 🔥 FIXED: use Dexscreener `/search` instead of broken `/pairs/{chain}`
    queries = ["pepe", "doge", "shiba", "floki", "bonk"]
    results: List[MemeEntry] = []

    for q in queries:
        data = safe_request(f"https://api.dexscreener.com/latest/dex/search?q={q}")
        if "error" in data:
            print(f"⚠️ dexscreener error on query {q}: {data['error']}")
            continue

        pairs = data.get("pairs", [])
        if not isinstance(pairs, list):
            continue

        candidates: List[Tuple[Dict[str, Any], float, float, float]] = []

        for p in pairs:
            if not isinstance(p, dict):
                continue

            liq_dict = p.get("liquidity", {})
            vol_dict = p.get("volume", {})
            chg_dict = p.get("priceChange", {})
            base_token = p.get("baseToken", {})

            if not isinstance(liq_dict, dict) or not isinstance(vol_dict, dict) or not isinstance(chg_dict, dict):
                continue
            if not isinstance(base_token, dict):
                base_token = {}

            try:
                liq = float(liq_dict.get("usd", 0) or 0)
                vol24 = float(vol_dict.get("h24", 0) or 0)
                change24 = float(chg_dict.get("h24", 0) or 0)
            except Exception:
                continue

            if liq >= MIN_LIQUIDITY and vol24 > liq:
                candidates.append((p, liq, vol24, change24))

        candidates = sorted(candidates, key=lambda x: x[2], reverse=True)[:3]

        for obj, liq, vol24, change24 in candidates:
            base_token = obj.get("baseToken", {}) if isinstance(obj.get("baseToken", {}), dict) else {}
            symbol = str(base_token.get("symbol", "?") or "?")
            price_usd = str(obj.get("priceUsd", "N/A") or "N/A")

            if change24 > 0 and liq > 1_000_000:
                score = "Low"
            elif change24 < -30:
                score = "High"
            else:
                score = "Medium"

            results.append(
                MemeEntry(
                    symbol=symbol,
                    chain=obj.get("chainId", "?"),
                    price_usd=price_usd,
                    liquidity_usd=f"${liq:,.0f}",
                    volume_24h_usd=f"${vol24:,.0f}",
                    change_24h_pct=f"{change24}%",
                    risk=score,
                )
            )

    return results


# ============ REPORTING ============ #
def build_report_and_detect_new(seen: Set[str]) -> Tuple[str, List[YieldEntry], Set[str]]:
    classified = classify_yield_opportunities()
    all_entries: List[YieldEntry] = []
    all_entries.extend(classified["long_term"])
    all_entries.extend(classified["short_term"])
    all_entries.extend(classified["focus"])
    all_entries.extend(classified["layer2"])

    current_ids: Set[str] = set(e.pool_id for e in all_entries if e.pool_id)
    new_ids: Set[str] = set(x for x in current_ids if x not in seen)
    new_opps: List[YieldEntry] = [e for e in all_entries if e.pool_id in new_ids]

    top_picks: List[YieldEntry] = sorted(all_entries, key=sort_key, reverse=True)[:5]

    lines: List[str] = []
    lines.append("=== DEFI OPPORTUNITIES REPORT ===")
    lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Sorting Mode: {SORT_MODE.upper()}")
    lines.append("")

    if new_opps:
        lines.append("🆕 NEW Opportunities Found:")
        for e in new_opps:
            lines.append(f" - {e.project} [{e.chain}] {e.symbol} | APY: {e.apy_str} | TVL: {e.tvl_str} | Risk: {e.risk} | ROR: {e.ror:.2f}")
        lines.append("")

    lines.append("🏆 Top Picks (All Chains):")
    for e in top_picks:
        lines.append(f" - {e.project} [{e.chain}] {e.symbol} | APY: {e.apy_str} | TVL: {e.tvl_str} | Risk: {e.risk} | ROR: {e.ror:.2f}")
    lines.append("")

    lines.append("🌱 Long-Term Opportunities:")
    for e in classified["long_term"]:
        lines.append(f" - {e.project} [{e.chain}] {e.symbol} | APY: {e.apy_str} | TVL: {e.tvl_str} | Risk: {e.risk} | ROR: {e.ror:.2f}")

    lines.append("\n⚡ Short-Term Opportunities:")
    for e in classified["short_term"]:
        lines.append(f" - {e.project} [{e.chain}] {e.symbol} | APY: {e.apy_str} | TVL: {e.tvl_str} | Risk: {e.risk} | ROR: {e.ror:.2f}")

    lines.append("\n🎯 Focus Protocols:")
    for e in classified["focus"]:
        lines.append(f" - {e.project} [{e.chain}] {e.symbol} | APY: {e.apy_str} | TVL: {e.tvl_str} | Risk: {e.risk} | ROR: {e.ror:.2f}")

    lines.append("\n🌉 Layer 2 Protocols:")
    for e in classified["layer2"]:
        lines.append(f" - {e.project} [{e.chain}] {e.symbol} | APY: {e.apy_str} | TVL: {e.tvl_str} | Risk: {e.risk} | ROR: {e.ror:.2f}")

    lines.append("\n🚀 Trending Meme Coins:")
    for m in get_meme_coins():
        lines.append(f" - {m.symbol} [{m.chain}] | Price: ${m.price_usd} | Liquidity: {m.liquidity_usd} | 24h Vol: {m.volume_24h_usd} | Change: {m.change_24h_pct} | Risk: {m.risk}")

    report = "\n".join(lines)
    return report, new_opps, current_ids


def save_to_pdf(content: str, filename: str | None = None) -> None:
    if not filename:
        filename = f"defi_opportunities_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.pdf"

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)

    for line in content.split("\n"):
        safe_line = line.encode("latin-1", "replace").decode("latin-1")
        pdf.multi_cell(0, 8, safe_line)

    pdf.output(filename)
    print(f"\n✅ Report saved as {filename}")


# ============ MAIN LOOP ============ #
def main() -> None:
    seen: Set[str] = load_seen()

    while True:
        os.system("cls" if os.name == "nt" else "clear")
        report, new_opps, current_ids = build_report_and_detect_new(seen)
        print(report)

        save_to_pdf(report)

        if new_opps:
            summary_lines: List[str] = []
            summary_lines.append("🆕 New DeFi Opportunities:")
            for e in new_opps[:5]:
                summary_lines.append(f"{e.project} [{e.chain}] {e.symbol} | APY {e.apy_str} | TVL {e.tvl_str} | ROR {e.ror:.2f}")
            send_telegram("\n".join(summary_lines))

        seen |= current_ids
        save_seen(seen)

        if REFRESH_MINS <= 0:
            break

        print(f"\n⏳ Refreshing in {REFRESH_MINS} minutes...")
        time.sleep(REFRESH_MINS * 60)


if __name__ == "__main__":
    main()
