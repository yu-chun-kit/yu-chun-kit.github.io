from __future__ import annotations

import sys
from pathlib import Path

from .cli import interactive_workflow, publish_conversation


def _pop_date_arg(args: list[str]) -> tuple[str | None, list[str]]:
    args = list(args)
    if "--date" not in args:
        return None, args
    index = args.index("--date")
    if index + 1 >= len(args):
        raise SystemExit("Error: --date requires YYYY-MM-DD")
    date = args[index + 1]
    del args[index : index + 2]
    return date, args


def convert_chat_main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 1 or len(args) > 2:
        print("Usage: python tools/convert_chat.py <chat_id> [output_file]")
        raise SystemExit(1)

    chat_id = args[0]
    output = Path(args[1]) if len(args) == 2 else None
    path = publish_conversation(chat_id, output=output)
    print(f"Generated: {path}")


def publish_chat_main(argv: list[str] | None = None) -> None:
    override_date, args = _pop_date_arg(sys.argv[1:] if argv is None else argv)

    if len(args) == 0:
        interactive_workflow()
        return

    if len(args) == 1:
        path = publish_conversation(args[0], override_date=override_date)
        print(f"Generated: {path}")
        return

    print("Usage:")
    print("  python tools/publish_chat.py")
    print("  python tools/publish_chat.py <chat_id>")
    print("  python tools/publish_chat.py --date 2026-01-15 <chat_id>")
    raise SystemExit(1)
