"""
extract_chat.py
---------------
Extracts user prompts and Claude's final text responses from a Claude Code
JSONL session file and writes a clean Markdown transcript.

Usage:
    python extract_chat.py                          # uses defaults below
    python extract_chat.py chat.jsonl output.md     # explicit paths

What "final response" means:
    After each user prompt, Claude may send many messages (tool calls,
    intermediate announcements, tool results). This script keeps only the
    LAST assistant message that contains text in each turn — the one the
    user actually sees as Claude's answer.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults — auto-discovered from the Claude Code project directory
# ---------------------------------------------------------------------------

def _find_session_jsonl() -> Path:
    """Return the largest Claude Code session JSONL for this project.

    Claude Code stores session files under:
        ~/.claude/projects/<project-path-with-slashes-replaced-by-dashes>/
    Falls back to _deliverable_artefacts/full_claude_chat.jsonl if the
    directory cannot be found (e.g. when running outside the project).
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    project_key  = str(project_root).replace("/", "-")
    claude_dir   = Path.home() / ".claude" / "projects" / project_key
    if claude_dir.is_dir():
        candidates = sorted(claude_dir.glob("*.jsonl"),
                            key=lambda p: p.stat().st_size, reverse=True)
        if candidates:
            return candidates[0]
    # Manual fallback
    return Path(__file__).parent.parent / "full_claude_chat.jsonl"

DEFAULT_INPUT  = _find_session_jsonl()
DEFAULT_OUTPUT = Path(__file__).parent / "chat_transcript.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[a-zA-Z_-][^>]*>.*?</[a-zA-Z_-][^>]*>", re.DOTALL)
_SELF_CLOSING_RE = re.compile(r"<[a-zA-Z_-][^>]*/?>")


def _clean(text: str) -> str:
    """Strip XML-style tag blocks injected by the IDE/harness."""
    text = _TAG_RE.sub("", text)
    text = _SELF_CLOSING_RE.sub("", text)
    return text.strip()


def _extract_text(content) -> str:
    """Pull all text blocks from a message content value."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _is_tool_result_message(content) -> bool:
    """True when the message is an automated tool-result reply, not a human prompt."""
    if not isinstance(content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "tool_result"
        for b in content
    )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def extract(input_path: Path, output_path: Path) -> None:
    with input_path.open(encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]

    # Keep only user and assistant message entries, in order
    messages = [e for e in entries if e.get("type") in ("user", "assistant")]

    # Identify the positions of real human prompts
    real_prompt_positions: list[int] = []
    for i, msg in enumerate(messages):
        if msg.get("type") != "user":
            continue
        content = msg.get("message", {}).get("content", [])
        if _is_tool_result_message(content):
            continue
        text = _clean(_extract_text(content))
        if text:
            real_prompt_positions.append(i)

    print(f"  Found {len(real_prompt_positions)} real user prompts")

    # For each prompt, collect prompt text + last assistant text response
    turns: list[tuple[str, str]] = []
    for idx, pos in enumerate(real_prompt_positions):
        prompt_text = _clean(_extract_text(
            messages[pos].get("message", {}).get("content", [])
        ))

        # Slice until the next real prompt (or end of file)
        end = (
            real_prompt_positions[idx + 1]
            if idx + 1 < len(real_prompt_positions)
            else len(messages)
        )

        # Last assistant message with text in this turn
        final_response = ""
        for msg in reversed(messages[pos + 1 : end]):
            if msg.get("type") != "assistant":
                continue
            text = _extract_text(msg.get("message", {}).get("content", []))
            if text.strip():
                final_response = text.strip()
                break

        turns.append((prompt_text, final_response))

    # Write Markdown
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as out:
        out.write("# Claude Code — Chat Transcript\n\n")
        out.write(
            f"*Extracted from `{input_path.name}` · "
            f"{len(turns)} turns*\n\n---\n\n"
        )
        for i, (prompt, response) in enumerate(turns, 1):
            out.write(f"## Turn {i}\n\n")
            out.write(f"**You**\n\n{prompt}\n\n")
            if response:
                out.write(f"**Claude**\n\n{response}\n\n")
            else:
                out.write("**Claude** *(no text response — tool calls only)*\n\n")
            out.write("---\n\n")

    print(f"  Written {len(turns)} turns → {output_path}")


if __name__ == "__main__":
    input_path  = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    print(f"Reading  : {input_path}")
    print(f"Writing  : {output_path}")
    extract(input_path, output_path)
