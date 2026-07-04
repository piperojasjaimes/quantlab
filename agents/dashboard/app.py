"""Streamlit Dashboard — real-time monitoring of QuantLab."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timezone

st.set_page_config(page_title="QuantLab Dashboard", layout="wide", page_icon="🔬")

from database.connection import get_connection
from core.config import config


async def _fetch(query: str, params=()):
    conn = await get_connection()
    cursor = await conn.execute(query, params)
    return [dict(r) for r in await cursor.fetchall()]


async def _fetch_one(query: str, params=()):
    conn = await get_connection()
    cursor = await conn.execute(query, params)
    row = await cursor.fetchone()
    return dict(row) if row else {}


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

# ── System State ─────────────────────────────────────────────────────────────
sys_state = run_async(_fetch_one("SELECT value, updated_at FROM system_state WHERE key = 'pipeline_stats'"))
if sys_state and sys_state.get("value"):
    try:
        stats = json.loads(sys_state["value"])
    except Exception:
        stats = {}
else:
    stats = {}

# ── Metrics Row ──────────────────────────────────────────────────────────────
strategies_c = run_async(_fetch_one("SELECT COUNT(*) as cnt FROM strategies"))
backtests_c = run_async(_fetch_one("SELECT COUNT(*) as cnt FROM backtest_results"))
passed_c = run_async(_fetch_one("SELECT COUNT(*) as cnt FROM backtest_results WHERE status='passed'"))
rankings_c = run_async(_fetch_one("SELECT COUNT(*) as cnt FROM rankings"))
tasks_c = run_async(_fetch("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"))

col1, col2, col3, col4, col5, col6 = st.columns(6)

total_strats = strategies_c.get("cnt", 0) + stats.get("strategies_generated", 0)
total_bts = backtests_c.get("cnt", 0) + stats.get("backtests_run", 0)
total_passed = passed_c.get("cnt", 0) + stats.get("validations_passed", 0)
total_opt = stats.get("optimizations_run", 0)
total_mut = stats.get("mutations_created", 0)
best_sharpe = stats.get("best_sharpe", 0)

col1.metric("Total Strategies", total_strats)
col2.metric("Total Backtests", total_bts)
col3.metric("Passed Validation", total_passed)
col4.metric("Optimizations", total_opt)
col5.metric("Mutations", total_mut)
col6.metric("Best Sharpe", f"{best_sharpe:.2f}")

st.divider()

# ── Agent Status Panel ───────────────────────────────────────────────────────
st.subheader("🤖 Agent Status")

agent_names = ["strategy", "coding", "backtest", "optimization", "validation", "mutation", "ranking", "memory", "report"]
agent_cols = st.columns(len(agent_names))

for i, name in enumerate(agent_names):
    with agent_cols[i]:
        tasks_for_agent = run_async(_fetch(
            "SELECT status, COUNT(*) as cnt FROM tasks WHERE agent = ? GROUP BY status",
            (name,)
        ))
        status_map = {r["status"]: r["cnt"] for r in tasks_for_agent}
        running = status_map.get("running", 0)
        completed = status_map.get("completed", 0)
        failed = status_map.get("failed", 0)

        if running > 0:
            st.success(f"**{name.upper()}**\n🔄 Running")
        elif failed > 0:
            st.error(f"**{name.upper()}**\n❌ {failed} failed")
        elif completed > 0:
            st.info(f"**{name.upper()}**\n✅ {completed} done")
        else:
            st.warning(f"**{name.upper()}**\n💤 Idle")

# ── Current Activity ─────────────────────────────────────────────────────────
st.subheader("⚡ Current Activity")
running_tasks = run_async(_fetch(
    "SELECT t.id, t.type, t.agent, t.strategy_id, t.created_at, t.updated_at "
    "FROM tasks t WHERE t.status = 'running' ORDER BY t.updated_at DESC LIMIT 10"
))
if running_tasks:
    df = pd.DataFrame([{
        "ID": r["id"][:8],
        "Type": r["type"],
        "Agent": r["agent"],
        "Strategy": r["strategy_id"][:20] if r["strategy_id"] else "-",
        "Started": r.get("updated_at", "?")[:19],
    } for r in running_tasks])
    st.dataframe(df, use_container_width=True)
else:
    st.info("No active tasks — system idle or all tasks completed")

st.divider()

# ── Task Queue ───────────────────────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("📋 Task Queue")
    if tasks_c:
        task_df = pd.DataFrame(tasks_c)
        st.bar_chart(task_df.set_index("status"))
    else:
        st.info("No tasks yet")

with col_b:
    st.subheader("📊 Backtest Results by Status")
    bt_status = run_async(_fetch("SELECT status, COUNT(*) as cnt FROM backtest_results GROUP BY status"))
    if bt_status:
        bt_df = pd.DataFrame(bt_status)
        st.bar_chart(bt_df.set_index("status"))
    else:
        st.info("No backtest results yet")

# ── Top Rankings ─────────────────────────────────────────────────────────────
st.subheader("🏆 Top Strategies")
top = run_async(_fetch(
    "SELECT r.rank, r.score, s.name, s.pattern, s.timeframe, s.symbol "
    "FROM rankings r LEFT JOIN strategies s ON r.strategy_id = s.id "
    "ORDER BY r.score DESC LIMIT 20"
))
if top:
    df = pd.DataFrame([{
        "Rank": r["rank"],
        "Name": r.get("name", "?")[:30],
        "Pattern": r.get("pattern", "?"),
        "TF": r.get("timeframe", "?"),
        "Symbol": r.get("symbol", "?"),
        "Score": round(r.get("score", 0), 4),
    } for r in top])
    st.dataframe(df, use_container_width=True)
else:
    st.info("No rankings yet — run the optimization loop first")

# ── Recent Backtests ─────────────────────────────────────────────────────────
st.subheader("📊 Recent Backtests")
recent = run_async(_fetch(
    "SELECT br.id, br.strategy_name, br.status, br.created_at, br.metrics "
    "FROM backtest_results br ORDER BY br.created_at DESC LIMIT 20"
))
if recent:
    rows = []
    for r in recent:
        try:
            m = json.loads(r.get("metrics", "{}"))
        except Exception:
            m = {}
        rows.append({
            "ID": r["id"][:8],
            "Strategy": (r.get("strategy_name", "?") or "?")[:30],
            "Status": "✅" if r["status"] == "passed" else "❌",
            "Sharpe": m.get("sharpe_ratio", "-"),
            "PF": m.get("profit_factor", "-"),
            "MaxDD%": m.get("max_drawdown_pct", "-"),
            "Trades": m.get("total_trades", "-"),
            "Created": (r.get("created_at", "?") or "?")[:16],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
else:
    st.info("No backtests yet — start the loop with run_loop.bat")

# ── Strategy Distribution ────────────────────────────────────────────────────
st.subheader("📈 Strategy Distribution")
col_p1, col_p2 = st.columns(2)

with col_p1:
    patterns = run_async(_fetch("SELECT pattern, COUNT(*) as cnt FROM strategies GROUP BY pattern ORDER BY cnt DESC"))
    if patterns:
        st.bar_chart(pd.DataFrame(patterns).set_index("pattern"))
    else:
        st.info("No strategies yet")

with col_p2:
    tf_dist = run_async(_fetch("SELECT timeframe, COUNT(*) as cnt FROM strategies GROUP BY timeframe ORDER BY cnt DESC"))
    if tf_dist:
        st.bar_chart(pd.DataFrame(tf_dist).set_index("timeframe"))
    else:
        st.info("No timeframe data yet")

# ── Logs ─────────────────────────────────────────────────────────────────────
st.subheader("📝 Recent Logs")
log_file = Path(__file__).resolve().parent.parent.parent / "logs" / "quantlab.log"
if log_file.exists():
    lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    recent_logs = lines[-20:]
    log_text = "\n".join(recent_logs)
    st.code(log_text, language=None)
else:
    st.info("No log file found")

# ── Auto-refresh ─────────────────────────────────────────────────────────────
try:
    from streamlit_autorefresh import st_autorefresh as _autorefresh
    auto_refresh = config.get("dashboard", "auto_refresh_seconds", default=10)
    _autorefresh(interval=auto_refresh * 1000, key="dashboard_refresh")
except ImportError:
    st.caption("Auto-refresh disabled (install streamlit-autorefresh)")
