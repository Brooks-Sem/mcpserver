from __future__ import annotations

import json

from .cli import resolve_claude_command, resolve_codex_command
from .config import GrokConfig


def diagnosis() -> dict[str, object]:
    report: dict[str, object] = {}
    for name, resolver in (("codex", resolve_codex_command), ("claude", resolve_claude_command)):
        try:
            command = resolver()
            report[name] = {
                "available": True,
                "executable": command.executable,
            }
        except FileNotFoundError as error:
            report[name] = {"available": False, "error": str(error)}
    try:
        report["grok"] = {"available": True, **GrokConfig.from_env().masked()}
    except ValueError as error:
        report["grok"] = {"available": False, "error": str(error)}
    return report


def main() -> None:
    print(json.dumps(diagnosis(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
