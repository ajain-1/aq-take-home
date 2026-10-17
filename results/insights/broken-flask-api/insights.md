# Insights: broken-flask-api

**5/5 attempts resolved the task** (95% interval for the true pass rate: 57%-100%).
Learnability verdict: **insufficient_evidence** (95% interval 57%-100% overlaps the 20-70% boundary; more runs needed).

Every finding below cites evidence that was re-checked verbatim against the run artifacts. Findings whose evidence did not verify are withheld and listed at the end.

## Findings

No failures to explain: every attempt resolved the task.

## Per-test pass rates

| Test | Passed | Failed | 95% interval |
|---|---|---|---|
| test_app_file_exists | 5 | 0 | 57%-100% |
| test_data_file_valid_json | 5 | 0 | 57%-100% |
| test_requirements_file_exists | 5 | 0 | 57%-100% |
| test_server_handles_multiple_requests | 5 | 0 | 57%-100% |
| test_server_is_running | 5 | 0 | 57%-100% |
| test_user_by_id_endpoint_invalid_id | 5 | 0 | 57%-100% |
| test_user_by_id_endpoint_valid_id | 5 | 0 | 57%-100% |
| test_users_endpoint_has_correct_structure | 5 | 0 | 57%-100% |
| test_users_endpoint_returns_json | 5 | 0 | 57%-100% |

## Attempts

| # | Outcome | Episodes | Duration (s) | Failed tests |
|---|---|---|---|---|
| 0 | solved | 26 | 194.99 | - |
| 1 | solved | 47 | 259.64 | - |
| 2 | solved | 36 | 206.89 | - |
| 3 | solved | 16 | 109.95 | - |
| 4 | solved | 28 | 162.51 | - |

Resolved vs unresolved (descriptive): {'n': 5, 'mean_episodes': 30.6, 'mean_duration_sec': 186.8, 'mean_input_tokens': 424958} vs {'n': 0}. Descriptive only; differences at this sample size are not statistically meaningful.

## Limitations

- Pass-rate intervals are 95% Wilson intervals; with few attempts they are wide and verdicts say so.
- Attempt classification is rule-based on recorded artifacts; it does not infer the agent's intent.
- Hidden-requirement detection is lexical: a test literal counts as stated only if it appears (case-insensitively) in the instruction, and as discoverable only if the environment showed it to an agent before that agent typed it; tests that accept any of several alternatives may be over-reported.
