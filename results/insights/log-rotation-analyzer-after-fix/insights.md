# Insights: log-rotation-analyzer

**10/10 attempts resolved the task** (95% interval for the true pass rate: 72%-100%).
Learnability verdict: **too_easy** (10 passing / 0 failing runs decide the 10-run rule (2-7 of 10 pass)).

Every finding below cites evidence that was re-checked verbatim against the run artifacts. Findings whose evidence did not verify are withheld and listed at the end.

## Findings

No failures to explain: every attempt resolved the task.

## Per-test pass rates

| Test | Passed | Failed | 95% interval |
|---|---|---|---|
| test_analysis_report_content | 10 | 0 | 72%-100% |
| test_analysis_report_exists | 10 | 0 | 72%-100% |
| test_issue_identification | 10 | 0 | 72%-100% |
| test_optimized_logrotate_config | 10 | 0 | 72%-100% |
| test_recommendations_quality | 10 | 0 | 72%-100% |
| test_rotation_summary_csv | 10 | 0 | 72%-100% |
| test_savings_calculation | 10 | 0 | 72%-100% |

## Attempts

| # | Outcome | Episodes | Duration (s) | Failed tests |
|---|---|---|---|---|
| 0 | solved | 25 | 177.06 | - |
| 1 | solved | 22 | 174.98 | - |
| 2 | solved | 20 | 177.05 | - |
| 3 | solved | 19 | 143.68 | - |
| 4 | solved | 14 | 130.99 | - |
| 5 | solved | 28 | 362.46 | - |
| 6 | solved | 17 | 154.24 | - |
| 7 | solved | 17 | 205.3 | - |
| 8 | solved | 18 | 299.17 | - |
| 9 | solved | 18 | 183.68 | - |

Resolved vs unresolved (descriptive): {'n': 10, 'mean_episodes': 19.8, 'mean_duration_sec': 200.9, 'mean_input_tokens': 191244} vs {'n': 0}. Descriptive only; differences at this sample size are not statistically meaningful.

## Limitations

- Pass-rate intervals are 95% Wilson intervals; with few attempts they are wide and verdicts say so.
- Attempt classification is rule-based on recorded artifacts; it does not infer the agent's intent.
- Hidden-requirement detection is lexical: a test literal counts as stated only if it appears (case-insensitively) in the instruction, and as discoverable only if the environment showed it to an agent before that agent typed it; tests that accept any of several alternatives may be over-reported.
