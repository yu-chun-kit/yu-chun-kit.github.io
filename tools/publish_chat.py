#!/usr/bin/env python3
"""Compatibility wrapper for the new chatblog CLI.

Usage:
  python tools/publish_chat.py
  python tools/publish_chat.py <chat_id>
  python tools/publish_chat.py --date 2026-01-15 <chat_id>

Preferred:
  uv run chatblog interactive
  uv run chatblog publish <chat_id> --date 2026-01-15
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chatblog.legacy import publish_chat_main


if __name__ == "__main__":
    publish_chat_main()
