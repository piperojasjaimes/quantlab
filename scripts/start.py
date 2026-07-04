"""Start QuantLab — main entry point."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.orchestrator.orchestrator import run_orchestrator
from core.logger import setup_logging


def main() -> None:
    setup_logging()
    print("=" * 60)
    print("  QuantLab — Autonomous Quantitative Research Laboratory")
    print("  Starting orchestrator...")
    print("=" * 60)
    try:
        asyncio.run(run_orchestrator())
    except KeyboardInterrupt:
        print("\nShutdown requested.")


if __name__ == "__main__":
    main()
