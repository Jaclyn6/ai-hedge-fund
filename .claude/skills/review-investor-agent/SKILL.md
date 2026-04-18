---
name: review-investor-agent
description: Gap-check a Claude Code investor subagent against the original ai-hedge-fund v1 LangChain prompt. Use this whenever a new or edited `.claude/agents/<investor>.md` file needs to be verified against `src/agents/<investor>.py`. Triggers on requests like "review the Buffett subagent," "does the Munger agent match the original?," "parity-check the new investor," or after completing a new investor conversion. Finds missing principles, signal rules, confidence tiers, reasoning style, few-shot examples, edge cases, and output-schema drift — then closes the gaps.
---

# Review investor subagent parity with v1 prompt

You are gap-checking a Claude Code subagent against its v1 counterpart so we don't drift from the original ai-hedge-fund investor logic. Run through every checkpoint. Do not skip.

## Inputs

You need:
- **Investor name** — kebab-case for the subagent file, snake_case for the Python file. E.g. `warren-buffett` ↔ `warren_buffett`. If the user gave one form, derive the other.
- **Subagent path** — `.claude/agents/<kebab-case>.md`
- **Original agent path** — `src/agents/<snake_case>.py`
- **Pure analyzer module** (if extracted) — `src/agents/<snake_case>_analysis.py`

If any of these files doesn't exist, stop and report which is missing. Don't invent paths.

## Workflow

1. **Read all three files.** Don't skim — read fully, because the gaps are usually in specifics (exact thresholds, example sentences, output schemas).
2. **Locate the v1 LLM system prompt.** In `src/agents/<snake_case>.py` it's inside a function named like `generate_<name>_output`. It's a `ChatPromptTemplate.from_messages([("system", "…"), ("human", "…")])`. The system message is your ground truth for the investor's voice and rules.
3. **Locate the v1 scoring logic.** Search the agent function for lines like `if total_score >= 0.7 * max_possible_score`. If present, v1 maps score→signal deterministically before calling the LLM. This threshold should be surfaced in the subagent so its LLM reasoning stays consistent with v1 behavior.
4. **Run the parity checklist below**, building a gap list with file:line references.
5. **Present the gaps** as a numbered list with severity (`critical` / `moderate` / `minor`) and the proposed fix. Then apply the fixes by editing `.claude/agents/<kebab-case>.md`.

## Parity checklist

For each item, write ✅ (present & matching), ⚠️ (present but diverges), or ❌ (missing). Cite the v1 source line.

### Principles & philosophy
- [ ] **Every bullet point** from the v1 system-prompt principles list is preserved in the subagent
- [ ] Wording preserves the investor's **voice** (Buffett plainspoken, Graham analytical, Wood visionary, Burry contrarian, etc.)
- [ ] Any **investor-specific warnings** (e.g. Graham's "avoid speculative/high-growth assumptions," Burry's "focus on tail risk") are explicit

### Signal rules
- [ ] Bullish / bearish / neutral **trigger conditions** match v1 signal rules exactly
- [ ] Any **score-to-signal threshold** in the v1 code (e.g. `>= 0.7 * max_score`) is surfaced as guidance in the subagent
- [ ] **Quantitative thresholds** (margin of safety cutoffs, ratio minimums) match v1 analyzer logic

### Confidence calibration
- [ ] **Confidence scale tiers** (e.g. 90-100, 70-89, …) match v1 verbatim where present
- [ ] Numeric type matches v1: `int` vs `float` (v1 Pydantic schema is authoritative)

### Reasoning style
- [ ] **Reasoning length** matches v1 expectation. If v1 says "Keep reasoning under 120 characters," the subagent must enforce the same. If v1 says "thorough reasoning," the subagent must request 2-5 sentences and forbid a bare one-liner.
- [ ] Any **reasoning checklist** in v1 (e.g. Graham's 6-point "explain valuation metrics, cite precise numbers, compare to thresholds…") is reproduced
- [ ] **Few-shot examples** from v1 (sample bullish / sample bearish reasoning with numbers) are carried into the subagent — do not paraphrase them away; copy them.

### Output schema
- [ ] JSON keys match v1's Pydantic model (`signal`, `confidence`, `reasoning`, plus any extras)
- [ ] `signal` literal values match v1: typically `"bullish" | "bearish" | "neutral"`
- [ ] Adding `ticker` is acceptable (improvement for aggregation) — call it out in the gap report but don't flag as regression

### MCP tool plumbing
- [ ] The subagent's `tools:` frontmatter references the matching `mcp__hedgefund__<name>_analysis` tool
- [ ] The MCP tool actually exists in `mcp_server/server.py` and wraps the correct analyzer functions
- [ ] The consolidated analysis dict returned by the MCP tool contains every field v1 passes to its LLM (inspect v1's `analysis_data[ticker] = { … }` assignment)

### Edge cases & data handling
- [ ] **Missing-data behavior** is defined: what does the subagent return when `analysis["intrinsic_value"]` or equivalent is null?
- [ ] v1's `default_factory` fallback (e.g. `BenGrahamSignal(signal="neutral", confidence=0.0, reasoning="Insufficient data…")`) is matched
- [ ] If v1 has any **"do not invent data" / "return JSON only"** instructions, they are present

## Severity rubric

- **Critical** — missing principle, wrong signal rule, wrong output schema, missing few-shot examples. Fix immediately.
- **Moderate** — voice mismatch, wrong reasoning length, missing threshold citation. Fix in the same pass.
- **Minor** — wording polish, format tweak. Can fix or defer with a note.

## Reporting format

```markdown
## Parity review — <investor-name>

**v1 source:** src/agents/<snake_case>.py (lines N-M system prompt)
**Subagent:** .claude/agents/<kebab-case>.md
**MCP tool:** mcp__hedgefund__<name>_analysis

### Gaps
1. **[critical] <short title>** — <what v1 has, what subagent has, fix>
2. **[moderate] …**
3. **[minor] …**

### Fixes applied
- <file:line> — <summary of edit>

### Verdict
- Critical gaps: <count>
- Moderate gaps: <count>
- Minor gaps: <count>
- Status: ✅ closed / ⚠️ partial — <reason>
```

## Do not

- Do not "modernize" or "improve" the v1 prompt wording during review. Parity is the goal. Improvements go through the user in a separate pass.
- Do not delete value-add extras we already added (Mr. Market framing, quantitative tool boxes, explicit data-missing fallbacks) — keep them **in addition to** the v1 content.
- Do not mark a subagent as passing if the few-shot examples are paraphrased. v1 bullish/bearish example sentences must appear verbatim (or near-verbatim with the same numbers).
