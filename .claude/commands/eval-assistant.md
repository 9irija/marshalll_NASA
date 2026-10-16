---
description: Run the Flight Controller evals and summarise failures
argument-hint: [--offline]
---
Run `PYTHONUTF8=1 .venv/Scripts/python -m evals.run_evals $ARGUMENTS` from the repo root.
With `ANTHROPIC_API_KEY` set it calls the Claude API (model from `CLAUDE_MODEL`); this costs money,
so confirm with the user before a live run unless they asked for one. Without a key it runs the
deterministic offline agent and skips prompts that need a language model.

Summarise: pass / fail / skip counts, then for each failure the prompt id, what failed (untraceable
number, invented or missing citation, wrong tool, wrong target, wrong feasibility, missing phrase)
and the offending answer excerpt from `evals/last_run.json`.

Diagnose before fixing. An untraceable number is a bug in the prompt or the verifier, never a reason
to loosen the verifier's tolerance. The rule is: the model never produces a safety-critical number.
