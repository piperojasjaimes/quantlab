"""Streamlit Dashboard — real-time monitoring of QuantLab."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timezone

st.set_page_config(page_title="QuantLab Dashboard", layout="wide", page_icon="📊")

from database.connection import get_connection
from core.config import config


async def _fetch(query: str, params=()):
    conn = await get_connection()
    cursor = await conn.execute(query, params)
    return [dict(r) for r in await cursor.fetchall()]


def run_async(coro):
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ── Header ───────────────────────────────────────────────────────────────────
st.title("🔬 QuantLab Dashboard")
st.caption("Autonomous Quantitative Research Laboratory for MT5")

# ── Metrics Row ──────────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)

strategies = run_async(_fetch("SELECT COUNT(*) as cnt FROM strategies"))
backtests = run_async(_fetch("SELECT COUNT(*) as cnt FROM backtest_results"))
passed = run_async(_fetch("SELECT COUNT(*) as cnt FROM backtest_results WHERE status='passed'"))
rankings = run_async(_fetch("SELECT COUNT(*) as cnt FROM rankings"))
tasks = run_async(_fetch("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"))

col1.metric("Strategies", strategies[0]["cnt"])
col2.metric("Backtests", backtests[0]["cnt"])
col3.metric("Passed", passed[0]["cnt"])
col4.metric("Ranked", rankings[0]["cnt"])
col5.metric("Pass Rate", f"{passed[0]['cnt']/max(backtests[0]['cnt'],1)*100:.1f}%")

st.divider()

# ── Task Status ──────────────────────────────────────────────────────────────
st.subheader("📋 Task Queue")
if tasks:
    task_df = pd.DataFrame(tasks)
    st.bar_chart(task_df.set_index("status"))
else:
    st.info("No tasks yet")

# ── Top Rankings ─────────────────────────────────────────────────────────────
st.subheader("🏆 Top Strategies")
top = run_async(_fetch("SELECT r.*, s.name, s.pattern, s.timeframe FROM rankings r LEFT JOIN strategies s ON r.strategy_id = s.id ORDER BY r.score DESC LIMIT 20"))
if top:
    df = pd.DataFrame([{
        "Rank": r["rank"],
        "Name": r.get("name", r.get("strategy_id", "?")),
        "Pattern": r.get("pattern", "?"),
        "Timeframe": r.get("timeframe", "?"),
        "Score": round(r.get("score", 0), 4),
    } for r in top])
    st.dataframe(df, use_container_width=True)
else:
    st.info("No rankings yet")

# ── Recent Backtests ─────────────────────────────────────────────────────────
st.subheader("📊 Recent Backtests")
recent = run_async(_fetch(
    "SELECT br.id, s.name, s.pattern, br.status, br.created_at FROM backtest_results br "
    "LEFT JOIN strategies s ON br.strategy_id = s.id ORDER BY br.created_at DESC LIMIT 20"
))
if recent:
    df = pd.DataFrame([{
        "ID": r["id"][:8],
        "Strategy": r.get("name", "?"),
        "Pattern": r.get("pattern", "?"),
        "Status": "✅" if r["status"] == "passed" else "❌",
        "Created": r.get("created_at", "?")[:19],
    } for r in recent])
    st.dataframe(df, use_container_width=True)
else:
    st.info("No backtests yet")

# ── Strategy Distribution ────────────────────────────────────────────────────
st.subheader("📈 Strategy Distribution")
patterns = run_async(_fetch("SELECT pattern, COUNT(*) as cnt FROM strategies GROUP BY pattern"))
if patterns:
    df = pd.DataFrame(patterns)
    st.bar_chart(df.set_index("pattern"))

# ── Auto-refresh ─────────────────────────────────────────────────────────────
auto_refresh = config.get("dashboard", "auto_refresh_seconds", default=10)
st_autorefresh = st.empty()
try:
    from streamlit_autorefresh import st_autorefresh as _autorefresh
    _autorefresh(interval=auto_refresh * 1000, key="refresh")
except ImportError:
    pass
