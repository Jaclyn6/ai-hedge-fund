#!/usr/bin/env python3
"""PostToolUse hook: inspects every `mcp__hedgefund__*` tool response for a
`data_quality` block. If the block says the analysis ran against incomplete
data, injects an `additionalContext` warning that the main model / subagent
sees immediately after the tool call — forcing it to tell the user about the
data gap before producing a signal.

This is the enforcement layer. The MCP server populates `data_quality`, this
hook surfaces it unconditionally so the rule applies even inside isolated
subagent contexts.
"""
from __future__ import annotations

import json
import sys


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return

    tool_name = event.get("tool_name", "")
    if not tool_name.startswith("mcp__hedgefund__"):
        return

    response = event.get("tool_response")
    analysis = _extract_analysis(response)
    if not analysis:
        return

    dq = analysis.get("data_quality") if isinstance(analysis, dict) else None
    if not dq or dq.get("complete"):
        return  # nothing to warn about

    ticker = analysis.get("ticker", "?")
    lines: list[str] = []
    if dq.get("critical"):
        lines.append(f"🚨 CRITICAL DATA GAP — {tool_name}({ticker})")
        missing = ", ".join(dq.get("missing_fields", []))
        if missing:
            lines.append(f"Missing valuation fields: {missing}")
        lines.append(
            "You MUST tell the user these fields are missing BEFORE producing any bullish/bearish/neutral signal. "
            "Do not silently downgrade to neutral — explicitly surface the data gap and explain which analyzers cannot run. "
            "If the user is using this for real investment decisions, a silent gap is worse than no answer."
        )
    else:
        lines.append(f"⚠️  Degraded analyzers — {tool_name}({ticker})")
        for w in dq.get("warnings", []):
            lines.append(f"  • {w}")
        lines.append(
            "You MUST list the degraded analyzers to the user and note how that constrains the signal's confidence BEFORE returning the final JSON. "
            "Do not produce a high-confidence signal on a partial analysis."
        )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(lines),
        }
    }
    print(json.dumps(output))


def _extract_analysis(response) -> dict | None:
    """The tool_response shape varies across Claude Code versions: sometimes
    it's the analysis dict directly, sometimes wrapped in `structuredContent`
    or a `content: [{type: 'text', text: '<json>'}]` envelope. Try each."""
    if not isinstance(response, dict):
        return None
    if "data_quality" in response:
        return response
    sc = response.get("structuredContent")
    if isinstance(sc, dict) and "data_quality" in sc:
        return sc
    content = response.get("content")
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                try:
                    parsed = json.loads(c.get("text", ""))
                    if isinstance(parsed, dict) and "data_quality" in parsed:
                        return parsed
                except Exception:
                    continue
    return None


if __name__ == "__main__":
    main()
