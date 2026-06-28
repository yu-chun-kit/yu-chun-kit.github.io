#!/usr/bin/env python3
"""Compatibility wrapper for the new chatblog CLI.

Usage:
  python tools/convert_chat.py <chat_id> [output_file]

Preferred:
  uv run chatblog publish <chat_id> [--output output_file]
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chatblog.legacy import convert_chat_main


if __name__ == "__main__":
    convert_chat_main()
