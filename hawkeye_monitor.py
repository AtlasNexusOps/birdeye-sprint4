#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  🦅 HAWKEYE MONITOR — Veille Actions Monétisables         ║
║  Atlas Nexus — Automated opportunity scanner              ║
╚══════════════════════════════════════════════════════════════╝

Scanne en continu les opportunités monétisables :
  1. Hawkeye V4 — pression forte (score ≥ 75)
  2. Breakouts — changement 24h > 10% + pression haussière
  3. Volume anormal — volume 2x moyenne + pression ≥ 50
  4. Tokens trending — CoinGecko trending avec pression haussière
  5. Extensions ATR — warning de surachat/survente
  6. RSI extrêmes — < 20 ou > 80
  7. Convergences — plusieurs signaux sur le même token

Output : rapport texte + JSON dans output/monitor/
Usage  : python hawkeye_monitor.py          # Run once
         python hawkeye_monitor.py --cron   # Cron mode (compact output)
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Imports from sprint4 pipeline ─────────────────────────
import hawkeye_core
from sentiment import compute_sentiment

# ════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════

COINGECKO_API = "https://api.coingecko.com/api/v3"
OUTPUT_DIR = Path("output/monitor")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NOW_TS = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
NOW_ISO = datetime.now(timezone.utc).isoformat()

# Seuils monétisables
PRESSURE_STRONG = 75      # Hawkeye score ≥ 75 = pression forte
PRESSURE_ACTIVE = 60      # Hawkeye score ≥ 60 = pression active
BREAKOUT_PCT = 10         # 24h change ≥ 10%
UNUSUAL_VOL_MULT = 2.0    # volume > 2x moyenne
RSI_OVERBOUGHT = 78       # RSI > 78 = surachat
RSI_OVERSOLD = 22         # RSI < 22 = survente
ATR_EXTREME = 2.5         # Extension ATR > 2.5 = anormal
VOL_MCAP_HIGH = 0.05      # Volume/Mcap > 5% = liquidité anormale

# ════════════════════════════════════════════════════════════
# DATA FETCHING
# ════════════════════════════════════════════════════════════

def fetch_coingecko_markets(per_page=100):
    url = f"{COINGECKO_API}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page={per_page}&page=1&sparkline=true&price_change_percentage=24h,7d"
    req = urllib.request.Request(url, headers={"User-Agent": "AtlasNexus-Monitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"⚠️ CoinGecko: {e}", file=sys.stderr)
        return []

def fetch_coingecko_trending():
    url = f"{COINGECKO_API}/search/trending"
    req = urllib.request.Request(url, headers={"User-Agent": "AtlasNexus-Monitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return [c['item'] for c in data.get('coins', [])]
    except Exception as e:
        print(f"⚠️ Trending: {e}", file=sys.stderr)
        return []

# ════════════════════════════════════════════════════════════
# NORMALIZATION
# ════════════════════════════════════════════════════════════

def normalize_coingecko(coins):
    normalized = []
    for c in coins:
        normalized.append({
            "id": c.get("id"),
            "symbol": (c.get("symbol") or "").upper(),
            "name": c.get("name"),
            "source": "coingecko",
            "price_usd": c.get("current_price") or 0,
            "price": c.get("current_price") or 0,
            "market_cap": c.get("market_cap") or 0,
            "volume_24h": c.get("total_volume") or 0,
            "change_24h": c.get("price_change_percentage_24h") or 0,
            "change_7d": c.get("price_change_percentage_7d_in_currency") or 0,
            "high_24h": c.get("high_24h"),
            "low_24h": c.get("low_24h"),
            "sparkline_7d": c.get("sparkline_in_7d", {}).get("price", []),
            "market_cap_rank": c.get("market_cap_rank"),
            "timestamp": NOW_ISO
        })
    return normalized

# ════════════════════════════════════════════════════════════
# SCANNING — Monetizable Signals
# ════════════════════════════════════════════════════════════

def scan_signals(tokens, trending_symbols=None):
    """
    Scan all tokens for monetizable signals.
    Returns list of alerts sorted by priority.
    """
    if not tokens:
        return []
    
    # Run Hawkeye V4 on all tokens
    hawkeye_ready = []
    for t in tokens:
        asset = dict(t)
        sparkline = t.get("sparkline_7d", [])
        if sparkline and len(sparkline) >= 14:
            asset["close"] = [float(x) for x in sparkline if x is not None]
        if "change_24h" in asset and "change_pct" not in asset:
            asset["change_pct"] = asset["change_24h"]
        hawkeye_ready.append(asset)
    
    analyses = hawkeye_core.analyze_assets(hawkeye_ready)
    
    # Merge Hawkeye fields
    for token, analysis in zip(tokens, analyses):
        token["pressure_score"] = analysis["score"]
        token["pressure_direction"] = analysis["direction"]
        token["pressure_regime"] = analysis["regime"]
        token["signal_family"] = analysis["signal_family"]
        token["h_rsi"] = analysis["rsi"]
        token["h_nroc5"] = analysis["nroc5"]
        token["h_extension_atr"] = round(analysis["extension_atr"], 2)
        token["h_atr_pct"] = round(analysis["atr_pct"], 2)
    
    # Compute volume baseline
    volumes = [t.get("volume_24h", 0) or 0 for t in tokens if t.get("volume_24h")]
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    
    alerts = []
    
    for t in tokens:
        ps = t.get("pressure_score", 0)
        pd = t.get("pressure_direction", "neutral")
        ch24 = t.get("change_24h", 0) or 0
        vol = t.get("volume_24h", 0) or 0
        mcap = t.get("market_cap", 0) or 0
        rsi = t.get("h_rsi", 50)
        ext = t.get("h_extension_atr", 0)
        nroc5 = t.get("h_nroc5", 0)
        symbol = t.get("symbol", "?")
        name = t.get("name", "?")
        price = t.get("price_usd", 0) or 0
        
        vol_mcap = (vol / mcap) if mcap > 0 else 0
        is_trending = trending_symbols and symbol in trending_symbols
        is_unusual_vol = vol > (avg_vol * UNUSUAL_VOL_MULT) if avg_vol else False
        
        reasons = []
        priority = 0
        
        # 1. Hawkeye strong pressure
        if ps >= PRESSURE_STRONG:
            reasons.append(f"🦅 Hawkeye {ps:.0f}/100 {pd}")
            priority += 30
        
        # 2. Breakout: >10% + bullish pressure
        if ch24 >= BREAKOUT_PCT and pd == "bullish" and ps >= PRESSURE_ACTIVE:
            reasons.append(f"🚀 Breakout +{ch24:.1f}% + pression {ps:.0f}")
            priority += 25
        
        # 3. Crash: <-10% + bearish pressure
        if ch24 <= -BREAKOUT_PCT and pd == "bearish" and ps >= PRESSURE_ACTIVE:
            reasons.append(f"📉 Crash {ch24:.1f}% + pression {ps:.0f}")
            priority += 20
        
        # 4. Unusual volume + bullish pressure
        if is_unusual_vol and pd == "bullish" and ps >= PRESSURE_ACTIVE:
            reasons.append(f"📊 Volume anormal ({vol/1e6:.0f}M) + bullish")
            priority += 20
        
        # 5. Trending + bullish pressure
        if is_trending and pd == "bullish" and ps >= PRESSURE_ACTIVE:
            reasons.append(f"🔥 Trending CoinGecko + bullish")
            priority += 18
        
        # 6. RSI extreme
        if rsi >= RSI_OVERBOUGHT:
            reasons.append(f"⚠️ RSI {rsi:.0f} surachat")
            priority += 10
        elif rsi <= RSI_OVERSOLD:
            reasons.append(f"💡 RSI {rsi:.0f} survente potentielle")
            priority += 12
        
        # 7. ATR extension
        if ext >= ATR_EXTREME:
            reasons.append(f"📏 Extension {ext:.1f} ATR")
            priority += 8
        
        # 8. Volume/MCap anormal
        if vol_mcap >= VOL_MCAP_HIGH:
            reasons.append(f"💧 Vol/Mcap {vol_mcap:.1%}")
            priority += 8
        
        # 9. Strong nROC
        if abs(nroc5) > 2.5:
            reasons.append(f"📐 nROC5 {nroc5:+.1f}")
            priority += 8
        
        if reasons:
            alerts.append({
                "symbol": symbol,
                "name": name,
                "price_usd": price,
                "change_24h": ch24,
                "pressure_score": ps,
                "pressure_direction": pd,
                "signal_family": t.get("signal_family", ""),
                "pressure_regime": t.get("pressure_regime", ""),
                "rsi": rsi,
                "extension_atr": ext,
                "nroc5": nroc5,
                "volume_mcap_ratio": round(vol_mcap, 4),
                "market_cap": mcap,
                "is_trending": is_trending,
                "is_unusual_vol": is_unusual_vol,
                "reasons": reasons,
                "priority": priority,
                "timestamp": NOW_ISO
            })
    
    alerts.sort(key=lambda x: x["priority"], reverse=True)
    return alerts

# ════════════════════════════════════════════════════════════
# REPORTING
# ════════════════════════════════════════════════════════════

def format_alert(alert, idx=None):
    """Format a single alert as a readable line."""
    prefix = f"{idx}. " if idx else ""
    symbol = alert["symbol"]
    ps = alert.get("pressure_score", 0)
    pd = alert.get("pressure_direction", "?")
    emoji = "🟢" if pd == "bullish" else "🔴" if pd == "bearish" else "⚪"
    ch24 = alert.get("change_24h", 0) or 0
    price = alert.get("price_usd", 0) or 0
    
    line = f"{prefix}{emoji} **{symbol}** | score={ps:.0f}/100 | {pd} | 24h={ch24:+.1f}% | ${price:,.4f}"
    if alert.get("is_trending"):
        line += " | 🔥 TRENDING"
    if alert.get("is_unusual_vol"):
        line += " | 📊 VOL+"
    
    reasons_str = " · ".join(alert.get("reasons", []))
    line += f"\n   └─ {reasons_str}"
    return line

def generate_report(alerts, stats):
    """Generate full monitoring report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    lines = []
    lines.append("╔══════════════════════════════════════════════╗")
    lines.append("║  🦅 HAWKEYE MONITOR — Rapport de Veille     ║")
    lines.append(f"║  {now}                     ║")
    lines.append("╚══════════════════════════════════════════════╝")
    lines.append("")
    
    # Market overview
    lines.append("📊 **APERÇU MARCHÉ**")
    lines.append(f"   Tokens scannés : {stats.get('total_tokens', 0)}")
    lines.append(f"   Trending       : {stats.get('trending_count', 0)}")
    lines.append(f"   Pression moy   : {stats.get('avg_pressure', 0):.1f}/100")
    lines.append(f"   Bullish        : {stats.get('bullish', 0)} | Bearish : {stats.get('bearish', 0)}")
    lines.append("")
    
    if not alerts:
        lines.append("✅ **Aucune alerte** — marché calme, pas d'opportunité forte détectée.")
        lines.append("")
        lines.append("💤 Prochain scan automatique dans 15 minutes.")
        return "\n".join(lines)
    
    # Alerts by category
    high_priority = [a for a in alerts if a["priority"] >= 30]
    medium_priority = [a for a in alerts if 15 <= a["priority"] < 30]
    low_priority = [a for a in alerts if a["priority"] < 15]
    
    if high_priority:
        lines.append(f"🚨 **PRIORITÉ HAUTE ({len(high_priority)})** — Signaux forts")
        for i, a in enumerate(high_priority, 1):
            lines.append(format_alert(a, i))
        lines.append("")
    
    if medium_priority:
        lines.append(f"⚠️ **PRIORITÉ MOYENNE ({len(medium_priority)})** — À surveiller")
        for i, a in enumerate(medium_priority, len(high_priority) + 1):
            lines.append(format_alert(a, i))
        lines.append("")
    
    if low_priority:
        lines.append(f"👁️ **VEILLE ({len(low_priority)})** — Signaux faibles")
        for i, a in enumerate(low_priority, len(high_priority) + len(medium_priority) + 1):
            lines.append(format_alert(a, i))
        lines.append("")
    
    lines.append("─" * 50)
    lines.append(f"🦅 Hawkeye V4 Monitor · {now}")
    lines.append("Prochain scan : 15 min")
    
    return "\n".join(lines)

def generate_compact(alerts, stats):
    """Generate compact report for cron/Telegram."""
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    
    if not alerts:
        return f"🦅 {now} | {stats.get('total_tokens',0)} tokens | pression {stats.get('avg_pressure',0):.0f} | ✅ calme"
    
    high = [a for a in alerts if a["priority"] >= 30]
    med = [a for a in alerts if 15 <= a["priority"] < 30]
    
    lines = [f"🦅 **Veille {now}** | {len(alerts)} alertes"]
    
    if high:
        lines.append(f"\n🚨 **HAUTE PRIORITÉ ({len(high)})**")
        for a in high[:5]:
            ps = a.get("pressure_score", 0)
            ch = a.get("change_24h", 0) or 0
            lines.append(f"  {'🟢' if a['pressure_direction']=='bullish' else '🔴'} {a['symbol']} | {ps:.0f}/100 | 24h={ch:+.1f}% | {' · '.join(a['reasons'][:2])}")
    
    if med:
        lines.append(f"\n⚠️ **SURVEILLANCE ({len(med)})**")
        for a in med[:3]:
            ps = a.get("pressure_score", 0)
            lines.append(f"  ⚡ {a['symbol']} | {ps:.0f}/100 | {' · '.join(a['reasons'][:2])}")
    
    return "\n".join(lines)

# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════

def run(cron_mode=False):
    """Execute one monitoring cycle."""
    
    # 1. Fetch data
    tokens_raw = fetch_coingecko_markets(per_page=100)
    trending_raw = fetch_coingecko_trending()
    trending_symbols = set(
        (t.get("symbol") or "").upper() for t in trending_raw
    )
    
    if not tokens_raw:
        print("❌ No data fetched", file=sys.stderr)
        return None
    
    # 2. Normalize
    tokens = normalize_coingecko(tokens_raw)
    
    # 3. Scan signals
    alerts = scan_signals(tokens, trending_symbols)
    
    # 4. Compute stats
    ps_scores = [t.get("pressure_score", 0) for t in tokens]
    directions = [t.get("pressure_direction", "neutral") for t in tokens]
    
    stats = {
        "total_tokens": len(tokens),
        "trending_count": len(trending_raw),
        "avg_pressure": round(sum(ps_scores) / len(ps_scores), 1) if ps_scores else 0,
        "bullish": directions.count("bullish"),
        "bearish": directions.count("bearish"),
        "neutral": directions.count("neutral"),
        "alerts_total": len(alerts),
        "alerts_high": len([a for a in alerts if a["priority"] >= 30]),
        "timestamp": NOW_ISO
    }
    
    # 5. Generate report
    report = generate_compact(alerts, stats) if cron_mode else generate_report(alerts, stats)
    
    # 6. Save outputs
    report_path = OUTPUT_DIR / f"monitor_{NOW_TS}.txt"
    report_path.write_text(report)
    
    data_path = OUTPUT_DIR / f"monitor_{NOW_TS}.json"
    with open(data_path, 'w') as f:
        json.dump({"alerts": alerts, "stats": stats}, f, indent=2, default=str)
    
    if not cron_mode:
        print(report)
        print(f"\n📁 Rapport: {report_path}")
        print(f"📁 Données: {data_path}")
    
    return {"alerts": alerts, "stats": stats, "report": report}

if __name__ == "__main__":
    cron_mode = "--cron" in sys.argv
    result = run(cron_mode=cron_mode)
    
    # Exit with code based on alert severity
    if result and result["stats"]["alerts_high"] > 0:
        sys.exit(2)  # High priority alerts
    elif result and result["stats"]["alerts_total"] > 0:
        sys.exit(1)  # Some alerts
    else:
        sys.exit(0)  # All clear
