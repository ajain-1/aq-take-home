# Insights: broken-coordinate-transform

**5/5 attempts resolved the task** (95% interval for the true pass rate: 57%-100%).
Learnability verdict: **undetermined** (5 passing / 0 failing runs; the 10-run rule (2-7 of 10 pass) is not yet decided).

Every finding below cites evidence that was re-checked verbatim against the run artifacts. Findings whose evidence did not verify are withheld and listed at the end.

## Findings

No failures to explain: every attempt resolved the task.

## Per-test pass rates

| Test | Passed | Failed | 95% interval |
|---|---|---|---|
| test_exists_and_compiles | 5 | 0 | 57%-100% |
| test_invalid_dimensions | 5 | 0 | 57%-100% |
| test_larger_matrix | 5 | 0 | 57%-100% |
| test_matrices_with_zeros | 5 | 0 | 57%-100% |
| test_negative_numbers | 5 | 0 | 57%-100% |
| test_normal_multiplication | 5 | 0 | 57%-100% |
| test_row_times_column | 5 | 0 | 57%-100% |
| test_single_element | 5 | 0 | 57%-100% |

## Attempts

| # | Outcome | Episodes | Duration (s) | Failed tests |
|---|---|---|---|---|
| 0 | solved | 12 | 116.47 | - |
| 1 | solved | 11 | 101.42 | - |
| 2 | solved | 14 | 115.27 | - |
| 3 | solved | 12 | 104.44 | - |
| 4 | solved | 24 | 204.58 | - |

Resolved vs unresolved (descriptive): {'n': 5, 'mean_episodes': 14.6, 'mean_duration_sec': 128.4, 'mean_input_tokens': 83843} vs {'n': 0}. Descriptive only; differences at this sample size are not statistically meaningful.

## Limitations

- Pass-rate intervals are 95% Wilson intervals; with few attempts they are wide and verdicts say so.
- Attempt classification is rule-based on recorded artifacts; it does not infer the agent's intent.
- Hidden-requirement detection is lexical: a test literal counts as stated only if it appears (case-insensitively) in the instruction, and as discoverable only if the environment showed it to an agent before that agent typed it; tests that accept any of several alternatives may be over-reported.
