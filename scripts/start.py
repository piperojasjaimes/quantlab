"""Start QuantLab — main entry point."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.logger import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="QuantLab — Autonomous Quantitative Research Laboratory")
    parser.add_argument("--mode", choices=["orchestrator", "loop", "dashboard", "all"], default="all",
                        help="Run mode: orchestrator (agent-based), loop (auto-optimization), dashboard, or all")
    args = parser.parse_args()

    setup_logging()
    print("=" * 60)
    print("  QuantLab — Autonomous Quantitative Research Laboratory")
    print(f"  Mode: {args.mode}")
    print("=" * 60)

    try:
        if args.mode == "orchestrator":
            from agents.orchestrator.orchestrator import run_orchestrator
            asyncio.run(run_orchestrator())
        elif args.mode == "loop":
            from core.pipeline.auto_loop import AutoOptimizationLoop
            loop = AutoOptimizationLoop()
            asyncio.run(loop.start())
        elif args.mode == "dashboard":
            import subprocess
            subprocess.run(["streamlit", "run", str(Path(__file__).resolve().parent.parent / "agents" / "dashboard" / "app.py"), "--server.port", "8501"])
        elif args.mode == "all":
            from core.pipeline.auto_loop import AutoOptimizationLoop
            auto_loop = AutoOptimizationLoop()
            asyncio.run(auto_loop.start())
    except KeyboardInterrupt:
        print("\nShutdown requested.")


if __name__ == "__main__":
    main()
