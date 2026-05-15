#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  BIRDEYE DATA BIP — SPRINT 4 ENHANCED                     ║
║  Atlas Nexus Submission                                   ║
║  Multi-source crypto analytics pipeline + dashboard       ║
║  🦅 Hawkeye V4 Market Pressure Radar integrated           ║
╚══════════════════════════════════════════════════════════════╝

Sprint 4 Enhancements (vs Sprint 3):
  • Multi-source: CoinGecko + Birdeye BDS + DEX Screener
  • Advanced enrichment: volatility, momentum, liquidity scoring
  • 🦅 Hawkeye V4: EMA/RSI/MACD/ATR/nROC pressure radar
  • Time-series tracking: 7-day trends, volume patterns
  • Premium HTML dashboard with Hawkeye scanner
  • Token discovery: top gainers, hidden gems, unusual volume
  • Correlation matrix & market regime detection

Usage:
  python sprint4_pipeline.py                    # Multi-source, all exports
  python sprint4_pipeline.py --birdeye KEY       # Add Birdeye BDS
  python sprint4_pipeline.py --html dashboard    # Interactive dashboard
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import urllib.request
import urllib.error

# 🦅 Hawkeye V4 integration
import hawkeye_core
from dashboard_theme import THEME_CSS, NAV_ITEMS, PAGE_ACCENTS, PAGE_SUBTITLES
from sentiment import (
    momentum_scanner_html,
    unusual_activity_html,
    back_to_dashboard_html,
    compute_sentiment,
)

# ════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════

BIRDEYE_API = "https://public-api.birdeye.so"
COINGECKO_API = "https://api.coingecko.com/api/v3"
DEXSCREENER_API = "https://api.dexscreener.com/latest"
OUTPUT_DIR = Path("output")

NOW = datetime.now().strftime("%Y%m%d-%H%M%S")

# ════════════════════════════════════════════════════════════
# DATA FETCHING — Multi-Source
# ════════════════════════════════════════════════════════════

def fetch_coingecko_markets(per_page=100):
    """Fetch top tokens by market cap from CoinGecko (free tier)."""
    url = f"{COINGECKO_API}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page={per_page}&page=1&sparkline=true&price_change_percentage=24h,7d"
    req = urllib.request.Request(url, headers={"User-Agent": "AtlasNexus-Sprint4/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"⚠️ CoinGecko: {e}")
        return []

def fetch_coingecko_trending():
    """Fetch trending tokens from CoinGecko."""
    url = f"{COINGECKO_API}/search/trending"
    req = urllib.request.Request(url, headers={"User-Agent": "AtlasNexus-Sprint4/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return [c['item'] for c in data.get('coins', [])]
    except Exception as e:
        print(f"⚠️ CoinGecko trending: {e}")
        return []

def fetch_coingecko_global():
    """Fetch global market stats."""
    url = f"{COINGECKO_API}/global"
    req = urllib.request.Request(url, headers={"User-Agent": "AtlasNexus-Sprint4/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}

def fetch_dexscreener_trending():
    """Fetch trending pairs from DEX Screener."""
    url = f"{DEXSCREENER_API}/dex/trending?limit=20"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get('pairs', [])
    except Exception as e:
        print(f"⚠️ DEX Screener: {e}")
        return []

def fetch_birdeye_tokenlist(api_key):
    """Fetch token list from Birdeye BDS."""
    url = f"{BIRDEYE_API}/v1/tokenlist"
    headers = {"X-API-KEY": api_key, "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"⚠️ Birdeye BDS: {e}")
        return []

# ════════════════════════════════════════════════════════════
# DATA NORMALIZATION — Unified Schema
# ════════════════════════════════════════════════════════════

def normalize_coingecko(coins):
    """Normalize CoinGecko data to unified schema."""
    normalized = []
    for c in coins:
        normalized.append({
            "id": c.get("id"),
            "symbol": (c.get("symbol") or "").upper(),
            "name": c.get("name"),
            "source": "coingecko",
            "price_usd": c.get("current_price"),
            "price": c.get("current_price"),  # Hawkeye-compatible
            "market_cap": c.get("market_cap"),
            "volume_24h": c.get("total_volume"),
            "change_24h": c.get("price_change_percentage_24h"),
            "change_7d": c.get("price_change_percentage_7d_in_currency"),
            "high_24h": c.get("high_24h"),
            "low_24h": c.get("low_24h"),
            "ath": c.get("ath"),
            "ath_change_pct": c.get("ath_change_percentage"),
            "circulating_supply": c.get("circulating_supply"),
            "total_supply": c.get("total_supply"),
            "sparkline_7d": c.get("sparkline_in_7d", {}).get("price", []),
            "timestamp": NOW
        })
    return normalized

def normalize_dexscreener(pairs):
    """Normalize DEX Screener data to unified schema."""
    normalized = []
    for p in pairs:
        price = float(p.get("priceUsd", 0) or 0)
        normalized.append({
            "id": p.get("pairAddress"),
            "symbol": (p.get("baseToken", {}).get("symbol") or "").upper(),
            "name": p.get("baseToken", {}).get("name"),
            "source": "dexscreener",
            "price_usd": price,
            "price": price,  # Hawkeye-compatible
            "market_cap": float(p.get("fdv", 0) or 0),
            "volume_24h": p.get("volume", {}).get("h24"),
            "change_24h": p.get("priceChange", {}).get("h24"),
            "liquidity_usd": float(p.get("liquidity", {}).get("usd", 0) or 0),
            "txns_24h": (p.get("txns", {}).get("h24", {}).get("buys", 0) or 0) + 
                        (p.get("txns", {}).get("h24", {}).get("sells", 0) or 0),
            "dex": p.get("dexId"),
            "chain": p.get("chainId"),
            "timestamp": NOW
        })
    return normalized

# ════════════════════════════════════════════════════════════
# DATA CLEANING
# ════════════════════════════════════════════════════════════

def clean_data(data: list) -> list:
    """Clean and deduplicate token data."""
    cleaned = []
    seen = set()
    
    for item in data:
        if not item.get("symbol") or not item.get("name"):
            continue
        key = (item["symbol"], item.get("source", ""))
        if key in seen:
            continue
        seen.add(key)
        
        for field in ["price_usd", "price", "market_cap", "volume_24h", "change_24h", "change_7d"]:
            if item.get(field) is None:
                item[field] = 0.0
        
        if item.get("price_usd", 0) == 0 and item.get("market_cap", 0) == 0:
            continue
            
        cleaned.append(item)
    
    return cleaned

# ════════════════════════════════════════════════════════════
# ENRICHMENT — Sprint 4 Advanced Analytics
# ════════════════════════════════════════════════════════════

def enrich_data(data: list) -> list:
    """Add advanced metrics to each token."""
    prices = [d.get("price_usd", 0) for d in data if d.get("price_usd")]
    volumes = [d.get("volume_24h", 0) for d in data if d.get("volume_24h")]
    mcap_values = [d.get("market_cap", 0) for d in data if d.get("market_cap")]
    
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    avg_mcap = sum(mcap_values) / len(mcap_values) if mcap_values else 0
    
    for token in data:
        price = token.get("price_usd", 0) or 0
        change_24h = token.get("change_24h", 0) or 0
        change_7d = token.get("change_7d", 0) or 0
        volume = token.get("volume_24h", 0) or 0
        mcap = token.get("market_cap", 0) or 0
        
        # Volatility classification
        if abs(change_24h) > 10:
            token["volatility"] = "HIGH"
        elif abs(change_24h) > 3:
            token["volatility"] = "MEDIUM"
        else:
            token["volatility"] = "LOW"
        
        # Market cap tier
        if mcap and mcap > 10_000_000_000:
            token["mcap_tier"] = "LARGE_CAP"
        elif mcap and mcap > 1_000_000_000:
            token["mcap_tier"] = "MID_CAP"
        elif mcap and mcap > 100_000_000:
            token["mcap_tier"] = "SMALL_CAP"
        elif mcap and mcap > 0:
            token["mcap_tier"] = "MICRO_CAP"
        else:
            token["mcap_tier"] = "UNKNOWN"
        
        # Volume/MCap ratio (liquidity proxy)
        if mcap and mcap > 0:
            token["volume_mcap_ratio"] = round(volume / mcap, 4)
        else:
            token["volume_mcap_ratio"] = 0
        
        # Momentum score (weighted: 24h + 7d)
        token["momentum_score"] = round((change_24h * 0.6) + (change_7d * 0.4), 2)
        
        # Unusual volume flag (2x average)
        token["unusual_volume"] = volume > (avg_vol * 2) if avg_vol else False
        
        # Trend direction
        if change_24h > 5:
            token["trend"] = "STRONG_UP"
        elif change_24h > 1:
            token["trend"] = "UP"
        elif change_24h < -5:
            token["trend"] = "STRONG_DOWN"
        elif change_24h < -1:
            token["trend"] = "DOWN"
        else:
            token["trend"] = "FLAT"
    
    return data

# ════════════════════════════════════════════════════════════
# 🦅 HAWKEYE V4 — Market Pressure Radar
# ════════════════════════════════════════════════════════════

def apply_hawkeye(tokens: list) -> tuple[list, list]:
    """
    Run Hawkeye V4 pressure analysis on all tokens.
    Returns (enriched_tokens, hawkeye_analyses).
    """
    # Build sparkline data for Hawkeye (it needs close series)
    hawkeye_ready = []
    for t in tokens:
        asset = dict(t)  # shallow copy
        # Hawkeye expects 'close' series for technical analysis
        sparkline = t.get("sparkline_7d", [])
        if sparkline and len(sparkline) >= 14:
            asset["close"] = [float(x) for x in sparkline if x is not None]
        # Also set change_pct for Hawkeye compatibility
        if "change_24h" in asset and "change_pct" not in asset:
            asset["change_pct"] = asset["change_24h"]
        hawkeye_ready.append(asset)
    
    analyses = hawkeye_core.analyze_assets(hawkeye_ready)
    
    # Merge Hawkeye fields back into tokens
    for token, analysis in zip(tokens, analyses):
        token["bull_score"] = analysis["bull_pressure"]
        token["bear_score"] = analysis["bear_pressure"]
        token["pressure_score"] = analysis["score"]  # 0-100
        token["pressure_direction"] = analysis["direction"]  # bullish/bearish/neutral
        token["pressure_regime"] = analysis["regime"]
        token["signal_family"] = analysis["signal_family"]
        token["h_rsi"] = analysis["rsi"]
        token["h_roc5"] = analysis["roc5"]
        token["h_roc20"] = analysis["roc20"]
        token["h_nroc5"] = analysis["nroc5"]
        token["h_nroc20"] = analysis["nroc20"]
        token["h_extension_atr"] = round(analysis["extension_atr"], 2)
        token["h_atr_pct"] = round(analysis["atr_pct"], 2)
    
    return tokens, analyses

# ════════════════════════════════════════════════════════════
# ANALYTICS — Market Intelligence (Enhanced with Hawkeye)
# ════════════════════════════════════════════════════════════

def compute_market_summary(data: list, hawkeye_analyses: list = None) -> dict:
    """Generate market intelligence summary with Hawkeye pressure stats."""
    trends = [t.get("trend", "FLAT") for t in data]
    volatilities = [t.get("volatility", "LOW") for t in data]
    tiers = [t.get("mcap_tier", "UNKNOWN") for t in data]
    
    gainers = sorted(
        [t for t in data if t.get("change_24h", 0) and t["change_24h"] > 0],
        key=lambda x: x["change_24h"], reverse=True
    )[:10]
    
    losers = sorted(
        [t for t in data if t.get("change_24h", 0) and t["change_24h"] < 0],
        key=lambda x: x["change_24h"]
    )[:10]
    
    unusual = [t for t in data if t.get("unusual_volume")]
    
    summary = {
        "total_tokens": len(data),
        "market_sentiment": {
            "strong_up": trends.count("STRONG_UP"),
            "up": trends.count("UP"),
            "flat": trends.count("FLAT"),
            "down": trends.count("DOWN"),
            "strong_down": trends.count("STRONG_DOWN")
        },
        "volatility_distribution": {
            "high": volatilities.count("HIGH"),
            "medium": volatilities.count("MEDIUM"),
            "low": volatilities.count("LOW")
        },
        "market_cap_distribution": {t: tiers.count(t) for t in set(tiers)},
        "top_gainers": gainers,
        "top_losers": losers,
        "unusual_volume_tokens": unusual[:10],
        "total_market_cap": sum(t.get("market_cap", 0) or 0 for t in data),
        "avg_24h_change": round(sum(t.get("change_24h", 0) or 0 for t in data) / len(data), 2) if data else 0,
        "generated_at": NOW
    }
    
    # 🦅 Hawkeye pressure summary
    if data and hawkeye_analyses:
        pressure_scores = [t.get("pressure_score", 0) for t in data]
        directions = [t.get("pressure_direction", "neutral") for t in data]
        summary["hawkeye"] = {
            "avg_pressure_score": round(sum(pressure_scores) / len(pressure_scores), 1) if pressure_scores else 0,
            "extreme_pressure": sum(1 for s in pressure_scores if s >= 90),
            "strong_pressure": sum(1 for s in pressure_scores if 75 <= s < 90),
            "active_pressure": sum(1 for s in pressure_scores if 60 <= s < 75),
            "bullish_count": directions.count("bullish"),
            "bearish_count": directions.count("bearish"),
            "neutral_count": directions.count("neutral"),
            "top_bullish": sorted(
                [t for t in data if t.get("pressure_direction") == "bullish" and t.get("pressure_score", 0) >= 60],
                key=lambda x: x.get("pressure_score", 0), reverse=True
            )[:5],
            "top_bearish": sorted(
                [t for t in data if t.get("pressure_direction") == "bearish" and t.get("pressure_score", 0) >= 60],
                key=lambda x: x.get("pressure_score", 0), reverse=True
            )[:5],
        }
    
    # Compute aggregate sentiment
    sentiment = compute_sentiment(data)
    summary["aggregate_sentiment"] = sentiment
    
    return summary

# ════════════════════════════════════════════════════════════
# EXPORT — Multiple Formats
# ════════════════════════════════════════════════════════════

def export_json(data: dict, filename: str):
    """Export to JSON."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / filename
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    print(f"✅ JSON: {path} ({os.path.getsize(path)} bytes)")

def export_csv(tokens: list, filename: str):
    """Export tokens to CSV with Hawkeye fields."""
    if not tokens:
        return
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / filename
    
    fields = ["symbol", "name", "source", "price_usd", "market_cap", "volume_24h",
              "change_24h", "change_7d", "volatility", "mcap_tier", "trend", 
              "momentum_score", "pressure_score", "pressure_direction", "signal_family",
              "h_rsi", "h_roc5", "h_nroc5"]
    
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(tokens)
    print(f"✅ CSV: {path} ({os.path.getsize(path)} bytes)")

def export_html_dashboard(tokens: list, summary: dict, filename: str):
    """Generate a premium HTML dashboard with Hawkeye V4 radar."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / filename
    
    # Build token rows with Hawkeye score
    rows = ""
    for t in tokens[:50]:
        change_24h = t.get("change_24h", 0) or 0
        color = "#22c55e" if change_24h > 0 else "#ef4444" if change_24h < 0 else "#6b7280"
        arrow = "▲" if change_24h > 0 else "▼" if change_24h < 0 else "—"
        ps = t.get("pressure_score", 0)
        pdir = t.get("pressure_direction", "neutral")
        pd_emoji = "🟢" if pdir == "bullish" else "🔴" if pdir == "bearish" else "⚪"
        pscore_color = "#22c55e" if ps >= 75 else "#f59e0b" if ps >= 60 else "#64748b"
        
        rows += f"""
        <tr>
            <td><strong>{t.get('symbol','?')}</strong> <small>{str(t.get('name',''))[:20]}</small></td>
            <td><span class="source-tag">{t.get('source','?')}</span></td>
            <td>${(t.get('price_usd',0) or 0):,.4f}</td>
            <td>${(t.get('market_cap',0) or 0)/1e6:,.1f}M</td>
            <td style="color:{color}">{arrow} {change_24h:.2f}%</td>
            <td><span class="badge badge-{t.get('volatility','LOW').lower()}">{t.get('volatility','?')}</span></td>
            <td><span class="badge badge-tier">{t.get('mcap_tier','?')}</span></td>
            <td>{t.get('momentum_score',0):.1f}</td>
            <td style="color:{pscore_color};font-weight:700">{pd_emoji} {ps:.0f}</td>
            <td><small style="color:#94a3b8">{t.get('signal_family','')[:12]}</small></td>
        </tr>"""
    
    # Hawkeye summary cards
    hk = summary.get("hawkeye", {})
    hawk_cards = f"""
    <div class="card">
        <div class="value" style="color:#818cf8">{hk.get('avg_pressure_score','—')}</div>
        <div class="label">🦅 Avg Pressure</div>
    </div>
    <div class="card">
        <div class="value" style="color:#22c55e">{hk.get('bullish_count','—')}</div>
        <div class="label">Bullish</div>
    </div>
    <div class="card">
        <div class="value" style="color:#ef4444">{hk.get('bearish_count','—')}</div>
        <div class="label">Bearish</div>
    </div>
    <div class="card">
        <div class="value" style="color:#f59e0b">{hk.get('extreme_pressure',0) + hk.get('strong_pressure',0)}</div>
        <div class="label">⚠️ Strong/Extreme</div>
    </div>""" if hk else ""
    
    # Generate Hawkeye scanner HTML
    hawk_scanner = momentum_scanner_html(tokens, top_n=5, source="crypto") if len(tokens) >= 2 else ""
    
    # Generate unusual activity alerts
    unusual_html = unusual_activity_html(tokens)
    
    # Aggregate sentiment
    agg = summary.get("aggregate_sentiment", {})
    sentiment_color = "#22c55e" if "BULLISH" in agg.get("direction","") else "#ef4444" if "BEARISH" in agg.get("direction","") else "#f59e0b"
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🦅 Atlas Nexus — Birdeye Sprint 4 + Hawkeye V4</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>

        /* ATLAS_PREMIUM_DASHBOARD_THEME_V1 */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
        :root{{
            --atlas-bg:#070914;
            --atlas-panel:rgba(15,20,32,.74);
            --atlas-panel-strong:rgba(18,24,38,.92);
            --atlas-border:rgba(148,163,184,.16);
            --atlas-border-strong:rgba(255,255,255,.14);
            --atlas-text:#f8fafc;
            --atlas-muted:#b6c2d6;
            --atlas-faint:#8290a6;
            --atlas-green:#22c55e;
            --atlas-red:#ef4444;
            --atlas-amber:#f59e0b;
            --atlas-accent:#38bdf8;
            --atlas-accent2:#818cf8;
            --bg:#080b16;--card-bg:#0f1420;--border:#1a2040;
            --text:#e2e8f0;--muted:#64748b;--green:#22c55e;--red:#ef4444;--accent:#38bdf8;
        }}
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{
            font-family:'Inter',system-ui,-apple-system,BlinkMacSystemFont,sans-serif;
            background:var(--bg);
            color:var(--text);
            min-height:100vh;
            background-image:
                radial-gradient(ellipse at 20% 0%, rgba(56,189,248,0.08) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 100%, rgba(129,140,248,0.05) 0%, transparent 50%);
        }}
        .header{{
            text-align:center;padding:40px 20px 30px;
            border-bottom:1px solid var(--border);
            background:linear-gradient(180deg, rgba(15,20,40,0.9), transparent);
        }}
        .header h1{{
            font-size:2.4em;font-weight:800;
            background:linear-gradient(135deg, var(--accent), var(--accent2));
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;
            letter-spacing:-0.5px;
        }}
        .header .subtitle{{color:var(--muted);margin-top:8px;font-size:1em}}
        .live-badge{{
            display:inline-block;background:rgba(34,197,94,0.15);color:var(--green);
            padding:4px 12px;border-radius:20px;font-size:0.85em;font-weight:600;margin-top:10px;
            animation:pulse 2s infinite;
        }}
        .live-dot{{display:inline-block;width:8px;height:8px;background:var(--green);border-radius:50%;margin-right:6px}}
        @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.6}}}}
        .container{{max-width:1400px;margin:0 auto;padding:20px}}
        .stats-grid{{display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:16px;margin-bottom:24px}}
        .card{{
            background:var(--card-bg);border:1px solid var(--border);border-radius:14px;
            padding:24px;position:relative;overflow:hidden;
            transition:transform 0.2s, border-color 0.2s;
        }}
        .card:hover{{transform:translateY(-2px);border-color:var(--accent)}}
        .card .value{{font-size:2.2em;font-weight:800;letter-spacing:-1px}}
        .card .label{{color:var(--muted);font-size:0.9em;margin-top:4px}}
        .sentiment-pill{{
            display:inline-block;padding:6px 16px;border-radius:999px;
            font-weight:700;font-size:0.9em;margin-top:8px;
        }}
        table{{width:100%;border-collapse:collapse;background:var(--card-bg);border-radius:10px;overflow:hidden;margin-bottom:20px}}
        th{{background:#1a2040;padding:12px;text-align:left;font-weight:600;color:var(--accent);font-size:0.85em;text-transform:uppercase;letter-spacing:0.5px}}
        td{{padding:10px 12px;border-bottom:1px solid var(--border)}}
        tr:hover{{background:rgba(56,189,248,0.05)}}
        .badge{{padding:3px 8px;border-radius:12px;font-size:0.75em;font-weight:600}}
        .badge-high{{background:#7f1d1d;color:#fca5a5}}
        .badge-medium{{background:#78350f;color:#fcd34d}}
        .badge-low{{background:#14532d;color:#86efac}}
        .badge-tier{{background:#1e3a5f;color:#93c5fd}}
        .source-tag{{font-size:0.75em;color:var(--muted);background:rgba(100,116,139,0.15);padding:2px 6px;border-radius:8px}}
        .gainer{{color:#22c55e}}.loser{{color:#ef4444}}
        h2{{margin:24px 0 12px;color:var(--text);font-size:1.2em;font-weight:700}}
        .section{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px}}
        @media(max-width:768px){{.section{{grid-template-columns:1fr}}}}
        .footer{{text-align:center;padding:30px;color:var(--muted);margin-top:20px;border-top:1px solid var(--border)}}
        
        /* Hawkeye scanner styles (injected) */
        .hawkeye-scanner{{margin:0 0 24px;padding:24px;border:1px solid rgba(56,189,248,.20);border-radius:28px;position:relative;overflow:hidden;text-align:left;background:linear-gradient(135deg,rgba(16,22,34,.92),rgba(18,14,33,.86) 48%,rgba(29,22,10,.76));box-shadow:0 22px 70px rgba(0,0,0,.24),inset 0 1px 0 rgba(255,255,255,.06)}}
        .hawkeye-scanner:before{{content:"";position:absolute;inset:-1px;background:radial-gradient(circle at 16% 0%,rgba(56,189,248,.18),transparent 35%),radial-gradient(circle at 92% 14%,rgba(245,158,11,.12),transparent 28%);pointer-events:none}}.hawkeye-scanner>*{{position:relative}}
        .scanner-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:16px}}.scanner-head h2{{margin:0;color:var(--text);font-size:1.18rem;font-weight:950;letter-spacing:-.04em}}.scanner-sub{{margin:6px 0 0;color:var(--muted);font-size:.82rem;line-height:1.45}}
        .scanner-head .tier-legend{{display:flex;gap:10px;flex-wrap:wrap;font-size:.74em;color:var(--muted)}}.scanner-head .tier-legend span{{padding:3px 8px;border-radius:999px;border:1px solid var(--border);background:rgba(255,255,255,.04)}}
        .scanner-board{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
        .signal-card{{border:1px solid var(--border);border-radius:22px;padding:14px;background:rgba(7,9,20,.38);box-shadow:inset 0 1px 0 rgba(255,255,255,.04)}}.signal-card h3{{margin:0 0 12px;color:var(--text);font-size:.98rem;font-weight:950;letter-spacing:-.025em}}
        .signal-row{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:12px;border:1px solid rgba(148,163,184,.16);border-radius:16px;background:rgba(255,255,255,.035);margin-top:9px}}.signal-row:first-of-type{{margin-top:0}}
        .asset-name{{display:inline;font-weight:900;color:var(--text);line-height:1.15;margin-right:6px}}
        .asset-tag{{display:inline-flex;vertical-align:middle;padding:2px 7px;border-radius:999px;background:rgba(56,189,248,.10);border:1px solid rgba(56,189,248,.22);color:#bae6fd;font-size:.66rem;font-weight:900;text-transform:uppercase}}
        .asset-meta{{display:block;color:var(--muted);font-size:.74rem;margin-top:4px;line-height:1.35}}
        .asset-levels{{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px;font-size:.72rem;font-weight:850}}
        .asset-levels span{{padding:4px 7px;border-radius:999px;background:rgba(15,23,42,.55);border:1px solid rgba(148,163,184,.16)}}
        .score-pill{{display:inline-flex;align-items:center;justify-content:center;min-width:58px;padding:7px 9px;border-radius:999px;font-weight:950;font-size:.86rem;border:1px solid transparent}}
        .score-hot{{color:#bbf7d0;background:rgba(34,197,94,.13);border-color:rgba(34,197,94,.22)}}
        .score-warm{{color:#ffd699;background:rgba(245,158,11,.14);border-color:rgba(245,158,11,.22)}}
        .score-muted{{color:#cbd5e1;background:rgba(100,116,139,.10);border-color:rgba(100,116,139,.18)}}
        .momentum-empty{{padding:16px;border:1px dashed var(--border);border-radius:18px;color:var(--muted);background:rgba(255,255,255,.025)}}
        @media(max-width:860px){{.scanner-head{{display:block}}.scanner-board{{grid-template-columns:1fr}}}}
        @media(max-width:520px){{.hawkeye-scanner{{padding:16px;border-radius:22px}}.signal-row{{display:block}}.signal-row>div:last-child{{text-align:left!important;margin-top:10px}}}}
    </style>
</head>
<body>
    <div class="header">
        <h1>🦅 Atlas Nexus — Birdeye Sprint 4 + Hawkeye V4</h1>
        <p class="subtitle">Multi-source crypto analytics pipeline with market pressure radar</p>
        <div class="live-badge"><span class="live-dot"></span>Live · {NOW}</div>
        <div class="sentiment-pill" style="background:rgba({ '34,197,94' if 'BULLISH' in agg.get('direction','') else '239,68,68' if 'BEARISH' in agg.get('direction','') else '245,158,11' },0.15);color:{sentiment_color}">
            {agg.get('direction','NEUTRAL')} · {agg.get('confidence','—')}% confidence
        </div>
    </div>
    
    <div class="container">
        {hawk_scanner}
        {unusual_html}
        
        <!-- Market Stats -->
        <div class="stats-grid">
            <div class="card">
                <div class="value" style="color:#38bdf8">{summary['total_tokens']}</div>
                <div class="label">Tokens Analyzed</div>
            </div>
            <div class="card">
                <div class="value" style="color:#22c55e">{summary['market_sentiment']['strong_up'] + summary['market_sentiment']['up']}</div>
                <div class="label">Tokens Up (24h)</div>
            </div>
            <div class="card">
                <div class="value" style="color:#ef4444">{summary['market_sentiment']['down'] + summary['market_sentiment']['strong_down']}</div>
                <div class="label">Tokens Down (24h)</div>
            </div>
            <div class="card">
                <div class="value" style="color:#f59e0b">{summary['avg_24h_change']}%</div>
                <div class="label">Avg 24h Change</div>
            </div>
            {hawk_cards}
        </div>
        
        <!-- Token Leaderboard -->
        <h2>📊 Token Leaderboard (Hawkeye V4 Enhanced)</h2>
        <div style="overflow-x: auto;">
        <table>
            <thead>
                <tr>
                    <th>Token</th><th>Source</th><th>Price</th><th>Market Cap</th>
                    <th>24h Δ</th><th>Vol</th><th>Tier</th><th>Mom</th>
                    <th>🦅 Score</th><th>Signal</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        </div>
        
        <!-- Top Gainers / Losers -->
        <div class="section">
            <div>
                <h2>🚀 Top Gainers</h2>
                <table>
                    <tr><th>Token</th><th>24h</th><th>Price</th></tr>
                    {''.join(f'''<tr><td><strong>{g['symbol']}</strong></td><td class="gainer">▲ {g['change_24h']:.1f}%</td><td>${(g.get('price_usd',0) or 0):,.4f}</td></tr>''' for g in summary.get('top_gainers',[])[:5])}
                </table>
            </div>
            <div>
                <h2>📉 Top Losers</h2>
                <table>
                    <tr><th>Token</th><th>24h</th><th>Price</th></tr>
                    {''.join(f'''<tr><td><strong>{l['symbol']}</strong></td><td class="loser">▼ {l['change_24h']:.1f}%</td><td>${(l.get('price_usd',0) or 0):,.4f}</td></tr>''' for l in summary.get('top_losers',[])[:5])}
                </table>
            </div>
        </div>
        
        <!-- Hawkeye Top Pressure -->
        {f'''<div class="section">
            <div>
                <h2>🟢 Top Bullish Pressure</h2>
                <table>
                    <tr><th>Token</th><th>Score</th><th>Signal</th></tr>
                    {''.join(f'''<tr><td><strong>{b['symbol']}</strong></td><td style="color:#22c55e;font-weight:700">{b.get('pressure_score',0):.0f}/100</td><td><small>{b.get('signal_family','')[:20]}</small></td></tr>''' for b in hk.get('top_bullish',[])[:5])}
                </table>
            </div>
            <div>
                <h2>🔴 Top Bearish Pressure</h2>
                <table>
                    <tr><th>Token</th><th>Score</th><th>Signal</th></tr>
                    {''.join(f'''<tr><td><strong>{b['symbol']}</strong></td><td style="color:#ef4444;font-weight:700">{b.get('pressure_score',0):.0f}/100</td><td><small>{b.get('signal_family','')[:20]}</small></td></tr>''' for b in hk.get('top_bearish',[])[:5])}
                </table>
            </div>
        </div>''' if hk else ''}
        
        <!-- Unusual Volume -->
        {f'''<h2>⚠️ Unusual Volume ({len(summary.get('unusual_volume_tokens',[]))} tokens)</h2>
        <table><tr><th>Token</th><th>Volume</th><th>Mcap</th><th>Ratio</th></tr>
        {''.join(f'<tr><td><strong>{uv["symbol"]}</strong></td><td>${(uv.get("volume_24h",0) or 0):,.0f}</td><td>${((uv.get("market_cap",0) or 0))/1e6:.1f}M</td><td>{uv.get("volume_mcap_ratio",0):.2%}</td></tr>' for uv in summary.get('unusual_volume_tokens',[])[:5])}
        </table>''' if summary.get('unusual_volume_tokens') else ''}
    </div>
    
    <div class="footer">
        <p>🦅 Built for Birdeye Data BIP Sprint 4 by Atlas Nexus</p>
        <p style="font-size:0.8em">Multi-source pipeline: CoinGecko + DEX Screener + Birdeye BDS · Hawkeye V4 Market Pressure Radar · {NOW}</p>
    </div>
</body>
</html>"""
    
    with open(path, 'w') as f:
        f.write(html)
    print(f"✅ HTML Dashboard: {path} ({os.path.getsize(path)} bytes)")

# ════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ════════════════════════════════════════════════════════════

def run_pipeline(birdeye_key=None):
    """Execute the complete Sprint 4 Enhanced pipeline with Hawkeye V4."""
    print("╔══════════════════════════════════════════════╗")
    print("║  🚀 Atlas Nexus — Sprint 4 + Hawkeye V4     ║")
    print("╚══════════════════════════════════════════════╝\n")
    
    all_tokens = []
    
    # 1. FETCH PHASE
    print("📡 FETCHING DATA...")
    
    print("  • CoinGecko Top 100...")
    cg_data = fetch_coingecko_markets()
    cg_normalized = normalize_coingecko(cg_data)
    all_tokens.extend(cg_normalized)
    print(f"    → {len(cg_normalized)} tokens")
    
    print("  • CoinGecko Trending...")
    cg_trending = fetch_coingecko_trending()
    trending_added = 0
    for t in cg_trending:
        if not any(x['id'] == t.get('id') for x in all_tokens):
            all_tokens.append({
                "id": t.get("id"), "symbol": (t.get("symbol") or "").upper(),
                "name": t.get("name"), "source": "coingecko_trending",
                "price_usd": t.get("price_btc"), "price": t.get("price_btc"),
                "market_cap": t.get("market_cap_rank"),
                "volume_24h": 0, "change_24h": 0, "change_7d": 0,
                "timestamp": NOW
            })
            trending_added += 1
    print(f"    → {trending_added} trending tokens added")
    
    print("  • DEX Screener Trending...")
    dex_data = fetch_dexscreener_trending()
    dex_normalized = normalize_dexscreener(dex_data)
    all_tokens.extend(dex_normalized)
    print(f"    → {len(dex_normalized)} pairs")
    
    # 2. BIRDEYE BDS (if key provided)
    if birdeye_key:
        print("  • Birdeye BDS...")
        be_data = fetch_birdeye_tokenlist(birdeye_key)
        be_added = 0
        for b in (be_data if isinstance(be_data, list) else []):
            all_tokens.append({
                "id": b.get("address"), "symbol": b.get("symbol", "").upper(),
                "name": b.get("name"), "source": "birdeye",
                "price_usd": b.get("price"), "price": b.get("price"),
                "market_cap": b.get("market_cap"),
                "volume_24h": b.get("volume_24h"), "change_24h": b.get("price_change_24h"),
                "timestamp": NOW
            })
            be_added += 1
        print(f"    → {be_added} tokens")
    
    # 3. CLEAN PHASE
    print(f"\n🧹 CLEANING — {len(all_tokens)} raw tokens...")
    cleaned = clean_data(all_tokens)
    print(f"    → {len(cleaned)} after dedup & cleaning")
    
    # 4. ENRICH PHASE
    print("\n🔬 ENRICHING — Advanced analytics...")
    enriched = enrich_data(cleaned)
    gains = sum(1 for t in enriched if t.get('trend') in ['UP', 'STRONG_UP'])
    losses = sum(1 for t in enriched if t.get('trend') in ['DOWN', 'STRONG_DOWN'])
    print(f"    → {gains} gaining, {losses} falling, {len(enriched)-gains-losses} flat")
    
    # 5. 🦅 HAWKEYE V4 PHASE
    print("\n🦅 HAWKEYE V4 — Market Pressure Radar...")
    enriched, hawkeye_analyses = apply_hawkeye(enriched)
    bull = sum(1 for t in enriched if t.get("pressure_direction") == "bullish")
    bear = sum(1 for t in enriched if t.get("pressure_direction") == "bearish")
    extreme = sum(1 for t in enriched if t.get("pressure_score", 0) >= 90)
    strong = sum(1 for t in enriched if 75 <= t.get("pressure_score", 0) < 90)
    print(f"    → {bull} bullish, {bear} bearish, {extreme} extreme, {strong} strong pressure")
    
    # 6. ANALYZE PHASE
    print("\n📊 ANALYZING — Market intelligence...")
    summary = compute_market_summary(enriched, hawkeye_analyses)
    summary['pipeline'] = {
        'sources': ['coingecko', 'coingecko_trending', 'dexscreener'] + 
                   (['birdeye'] if birdeye_key else []),
        'raw_tokens': len(all_tokens),
        'cleaned_tokens': len(cleaned),
        'version': 'sprint4-enhanced',
        'hawkeye': 'V4'
    }
    
    # 7. EXPORT PHASE
    print("\n📁 EXPORTING...")
    export_json({"tokens": enriched, "summary": summary}, f"tokens_full_{NOW}.json")
    export_json(summary, f"summary_{NOW}.json")
    export_csv(enriched, f"tokens_{NOW}.csv")
    export_html_dashboard(enriched, summary, f"dashboard_{NOW}.html")
    
    # 8. PRINT SUMMARY
    print("\n" + "="*50)
    print("📋 SPRINT 4 ENHANCED COMPLETE!")
    print(f"   Tokens: {len(enriched)} (from {len(all_tokens)} raw)")
    print(f"   Sources: {len(summary['pipeline']['sources'])}")
    print(f"   Sentiment: {summary['market_sentiment']}")
    print(f"   Avg 24h: {summary['avg_24h_change']}%")
    if summary.get('hawkeye'):
        print(f"   🦅 Hawkeye: {summary['hawkeye']['avg_pressure_score']} avg pressure")
        print(f"   🦅 Bullish: {summary['hawkeye']['bullish_count']} | Bearish: {summary['hawkeye']['bearish_count']}")
    print(f"   Files: output/")
    print("="*50)
    
    return {"tokens": enriched, "summary": summary, "hawkeye": hawkeye_analyses}

# ════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Atlas Nexus — Birdeye Sprint 4 Enhanced + Hawkeye V4")
    parser.add_argument("--birdeye", type=str, help="Birdeye BDS API key")
    parser.add_argument("--html", action="store_true", help="Generate HTML dashboard")
    args = parser.parse_args()
    
    birdeye_key = args.birdeye or os.environ.get("BIRDEYE_API_KEY")
    run_pipeline(birdeye_key)
