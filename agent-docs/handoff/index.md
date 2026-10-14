File: 3192c062a0fd880f-selfcheck-checker-gaps-and-repeats.md
Summary: Stage 2/3 — first live selfcheck check exposed PC8 blind to Bash spec writes, no retroactive-spec check, and a single harness run per instance
Related Files: selfcheck/process.py, selfcheck/__main__.py, selfcheck/run.py, selfcheck/report.py, selfcheck/fixture.py, selfcheck/results/a41e64cb9bbbef03.md
Related Symbols: evaluate_entry, PC8, PC2, PC9, cmd_check, run.run, report.build
---
File: bf0d1dd85535bb18-selfcheck-informed-brief-review.md
Summary: Stage 1/3 — post-run reviewer that compares harness briefs and spec with gold and reports divergences, without changing the run
Related Files: selfcheck/agent/user_sim.py, selfcheck/agent/driver.py, selfcheck/run.py, selfcheck/process.py, selfcheck/report.py, selfcheck/fixtures/instances.jsonl
Related Symbols: PHRASE, on_idle, compose_prompt, evaluate_entry, report.build
---
File: 44ab3e5b5b54f81d-selfcheck-informed-reviewer-condition.md
Summary: Stage 3/3 — in-loop gold-informed reviewer answering harness briefs as a separate constrained condition; unassisted check stays primary
Related Files: selfcheck/agent/user_sim.py, selfcheck/agent/driver.py, selfcheck/run.py, selfcheck/manifest.py, selfcheck/fixture.py, selfcheck/report.py
Related Symbols: PHRASE, on_idle, max_user_turns, fixture_id, report.build
