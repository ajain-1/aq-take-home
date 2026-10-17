# Insights: log-rotation-analyzer

**0/5 attempts resolved the task** (95% interval for the true pass rate: 0%-43%).
Learnability verdict: **insufficient_evidence** (95% interval 0%-43% overlaps the 20-70% boundary; more runs needed).

Every finding below cites evidence that was re-checked verbatim against the run artifacts. Findings whose evidence did not verify are withheld and listed at the end.

## Findings

### [high] test_analysis_report_content never passes

test_analysis_report_content failed in all 5 completed attempts with the identical assertion message, which points at a systematic cause (a task/spec issue or a capability gap) rather than run-to-run noise.

Evidence:
- **E26** (verified) attempt 0, `runs/attempt-0/d420e95d2ee0-attempt-0/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-0/panes/post-test.txt:239`: "FAILED ../tests/test_outputs.py::test_analysis_report_content - AssertionError: Missing required section: SYSTEM OVERVIEW"
- **E27** (verified) attempt 1, `runs/attempt-1/d420e95d2ee0-attempt-1/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-1/panes/post-test.txt:239`: "FAILED ../tests/test_outputs.py::test_analysis_report_content - AssertionError: Missing required section: SYSTEM OVERVIEW"
- **E28** (verified) attempt 2, `runs/attempt-2/d420e95d2ee0-attempt-2/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-2/panes/post-test.txt:250`: "FAILED ../tests/test_outputs.py::test_analysis_report_content - AssertionError: Missing required section: SYSTEM OVERVIEW"
- **E29** (verified) attempt 3, `runs/attempt-3/d420e95d2ee0-attempt-3/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-3/panes/post-test.txt:239`: "FAILED ../tests/test_outputs.py::test_analysis_report_content - AssertionError: Missing required section: SYSTEM OVERVIEW"
- **E30** (verified) attempt 4, `runs/attempt-4/d420e95d2ee0-attempt-4/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-4/panes/post-test.txt:250`: "FAILED ../tests/test_outputs.py::test_analysis_report_content - AssertionError: Missing required section: SYSTEM OVERVIEW"

### [high] test_issue_identification never passes

test_issue_identification failed in all 5 completed attempts with the identical assertion message, which points at a systematic cause (a task/spec issue or a capability gap) rather than run-to-run noise.

Evidence:
- **E31** (verified) attempt 0, `runs/attempt-0/d420e95d2ee0-attempt-0/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-0/panes/post-test.txt:241`: "FAILED ../tests/test_outputs.py::test_issue_identification - AssertionError: No issues identified in log analysis"
- **E32** (verified) attempt 1, `runs/attempt-1/d420e95d2ee0-attempt-1/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-1/panes/post-test.txt:241`: "FAILED ../tests/test_outputs.py::test_issue_identification - AssertionError: No issues identified in log analysis"
- **E33** (verified) attempt 2, `runs/attempt-2/d420e95d2ee0-attempt-2/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-2/panes/post-test.txt:252`: "FAILED ../tests/test_outputs.py::test_issue_identification - AssertionError: No issues identified in log analysis"
- **E34** (verified) attempt 3, `runs/attempt-3/d420e95d2ee0-attempt-3/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-3/panes/post-test.txt:241`: "FAILED ../tests/test_outputs.py::test_issue_identification - AssertionError: No issues identified in log analysis"
- **E35** (verified) attempt 4, `runs/attempt-4/d420e95d2ee0-attempt-4/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-4/panes/post-test.txt:252`: "FAILED ../tests/test_outputs.py::test_issue_identification - AssertionError: No issues identified in log analysis"

### [high] test_recommendations_quality never passes

test_recommendations_quality failed in all 5 completed attempts.

Evidence:
- **E36** (verified) attempt 0, `runs/attempt-0/d420e95d2ee0-attempt-0/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-0/panes/post-test.txt:242`: "FAILED ../tests/test_outputs.py::test_recommendations_quality - AssertionError: No recommendations section found"
- **E37** (verified) attempt 1, `runs/attempt-1/d420e95d2ee0-attempt-1/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-1/panes/post-test.txt:242`: "FAILED ../tests/test_outputs.py::test_recommendations_quality - AssertionError: No recommendations section found"
- **E38** (verified) attempt 2, `runs/attempt-2/d420e95d2ee0-attempt-2/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-2/panes/post-test.txt:253`: "FAILED ../tests/test_outputs.py::test_recommendations_quality - AssertionError: Recommendations lack specificity, found 1 actionable terms"
- **E39** (verified) attempt 3, `runs/attempt-3/d420e95d2ee0-attempt-3/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-3/panes/post-test.txt:242`: "FAILED ../tests/test_outputs.py::test_recommendations_quality - AssertionError: No recommendations section found"
- **E40** (verified) attempt 4, `runs/attempt-4/d420e95d2ee0-attempt-4/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-4/panes/post-test.txt:253`: "FAILED ../tests/test_outputs.py::test_recommendations_quality - AssertionError: Recommendations lack specificity, found 2 actionable terms"

### [high] test_savings_calculation never passes

test_savings_calculation failed in all 5 completed attempts with the identical assertion message, which points at a systematic cause (a task/spec issue or a capability gap) rather than run-to-run noise.

Evidence:
- **E41** (verified) attempt 0, `runs/attempt-0/d420e95d2ee0-attempt-0/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-0/panes/post-test.txt:240`: "FAILED ../tests/test_outputs.py::test_savings_calculation - AssertionError: Savings percentage not found in report"
- **E42** (verified) attempt 1, `runs/attempt-1/d420e95d2ee0-attempt-1/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-1/panes/post-test.txt:240`: "FAILED ../tests/test_outputs.py::test_savings_calculation - AssertionError: Savings percentage not found in report"
- **E43** (verified) attempt 2, `runs/attempt-2/d420e95d2ee0-attempt-2/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-2/panes/post-test.txt:251`: "FAILED ../tests/test_outputs.py::test_savings_calculation - AssertionError: Savings percentage not found in report"
- **E44** (verified) attempt 3, `runs/attempt-3/d420e95d2ee0-attempt-3/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-3/panes/post-test.txt:240`: "FAILED ../tests/test_outputs.py::test_savings_calculation - AssertionError: Savings percentage not found in report"
- **E45** (verified) attempt 4, `runs/attempt-4/d420e95d2ee0-attempt-4/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-4/panes/post-test.txt:251`: "FAILED ../tests/test_outputs.py::test_savings_calculation - AssertionError: Savings percentage not found in report"

### [high] test_analysis_report_content checks for text the instruction never specifies

test_analysis_report_content looks for 'LOG ROTATION ANALYSIS REPORT', 'SYSTEM OVERVIEW', 'LOG FILE ANALYSIS', 'Total log size:', 'Estimated total savings:', but none of these appear in the instruction or in any terminal output the agents saw. It failed in 5/5 completed attempts. Either state the expected format in the instruction or relax the test.

Evidence:
- **E46** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:20`: "LOG ROTATION ANALYSIS REPORT"
- **E47** (verified) `LOG ROTATION ANALYSIS REPORT` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`
- **E48** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:21`: "SYSTEM OVERVIEW"
- **E49** (verified) `SYSTEM OVERVIEW` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`
- **E50** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:22`: "LOG FILE ANALYSIS"
- **E51** (verified) `LOG FILE ANALYSIS` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`
- **E52** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:30`: "Total log size:"
- **E53** (verified) `Total log size:` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`
- **E54** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:31`: "Estimated total savings:"
- **E55** (verified) `Estimated total savings:` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`

### [high] test_savings_calculation checks for text the instruction never specifies

test_savings_calculation looks for 'Potential space reduction:', but none of these appear in the instruction or in any terminal output the agents saw. It failed in 5/5 completed attempts. Either state the expected format in the instruction or relax the test.

Evidence:
- **E56** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:91`: "Potential space reduction:"
- **E57** (verified) `Potential space reduction:` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`

### [high] test_issue_identification checks for text the instruction never specifies

test_issue_identification looks for 'HIGH', 'MEDIUM', 'Large file', but none of these appear in the instruction or in any terminal output the agents saw. It failed in 5/5 completed attempts. Either state the expected format in the instruction or relax the test.

Evidence:
- **E58** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:103`: "HIGH"
- **E59** (verified) `HIGH` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`
- **E60** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:103`: "MEDIUM"
- **E61** (verified) `MEDIUM` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`
- **E62** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:114`: "Large file"
- **E63** (verified) `Large file` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`

### [high] test_recommendations_quality checks for text the instruction never specifies

test_recommendations_quality looks for 'monitor', 'RECOMMENDATIONS:', but none of these appear in the instruction or in any terminal output the agents saw. It failed in 5/5 completed attempts. Either state the expected format in the instruction or relax the test.

Evidence:
- **E64** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:135`: "monitor"
- **E65** (verified) `monitor` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`
- **E66** (verified) `tasks/log-rotation-analyzer/tests/test_outputs.py:128`: "RECOMMENDATIONS:"
- **E67** (verified) `RECOMMENDATIONS:` does **not** occur in `tasks/log-rotation-analyzer/task.yaml#instruction`

### [info] Attempt 0: declared_done_with_failing_tests

Attempt 0 ended as declared done with failing tests; failing tests: test_analysis_report_content, test_issue_identification, test_recommendations_quality, test_savings_calculation

Evidence:
- **E5** (verified) attempt 0, episode 16, `runs/attempt-0/d420e95d2ee0-attempt-0/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-0/agent-logs/episode-16/response.json`: "All three required files have been successfully created in /app:  1. **analysis_report.txt** (4029 bytes, 132 lines) - Human-readable report with:    - Executive summary showing 78% disk usage and compliance requirements    - Current log ro"
- **E1** (verified) attempt 0, `runs/attempt-0/d420e95d2ee0-attempt-0/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-0/panes/post-test.txt:239`: "FAILED ../tests/test_outputs.py::test_analysis_report_content - AssertionError: Missing required section: SYSTEM OVERVIEW"
- **E2** (verified) attempt 0, `runs/attempt-0/d420e95d2ee0-attempt-0/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-0/panes/post-test.txt:240`: "FAILED ../tests/test_outputs.py::test_savings_calculation - AssertionError: Savings percentage not found in report"
- **E3** (verified) attempt 0, `runs/attempt-0/d420e95d2ee0-attempt-0/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-0/panes/post-test.txt:241`: "FAILED ../tests/test_outputs.py::test_issue_identification - AssertionError: No issues identified in log analysis"
- **E4** (verified) attempt 0, `runs/attempt-0/d420e95d2ee0-attempt-0/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-0/panes/post-test.txt:242`: "FAILED ../tests/test_outputs.py::test_recommendations_quality - AssertionError: No recommendations section found"

### [info] Attempt 1: declared_done_with_failing_tests

Attempt 1 ended as declared done with failing tests; failing tests: test_analysis_report_content, test_issue_identification, test_recommendations_quality, test_savings_calculation

Evidence:
- **E10** (verified) attempt 1, episode 15, `runs/attempt-1/d420e95d2ee0-attempt-1/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-1/agent-logs/episode-15/response.json`: "All three required files have been successfully created in /app:  1. analysis_report.txt (8259 bytes, 210 lines) - Contains comprehensive analysis including:    - Executive summary with current disk usage (78%)    - Current log rotation sta"
- **E6** (verified) attempt 1, `runs/attempt-1/d420e95d2ee0-attempt-1/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-1/panes/post-test.txt:239`: "FAILED ../tests/test_outputs.py::test_analysis_report_content - AssertionError: Missing required section: SYSTEM OVERVIEW"
- **E7** (verified) attempt 1, `runs/attempt-1/d420e95d2ee0-attempt-1/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-1/panes/post-test.txt:240`: "FAILED ../tests/test_outputs.py::test_savings_calculation - AssertionError: Savings percentage not found in report"
- **E8** (verified) attempt 1, `runs/attempt-1/d420e95d2ee0-attempt-1/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-1/panes/post-test.txt:241`: "FAILED ../tests/test_outputs.py::test_issue_identification - AssertionError: No issues identified in log analysis"
- **E9** (verified) attempt 1, `runs/attempt-1/d420e95d2ee0-attempt-1/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-1/panes/post-test.txt:242`: "FAILED ../tests/test_outputs.py::test_recommendations_quality - AssertionError: No recommendations section found"

### [info] Attempt 2: declared_done_with_failing_tests

Attempt 2 ended as declared done with failing tests; failing tests: test_analysis_report_content, test_issue_identification, test_recommendations_quality, test_savings_calculation

Evidence:
- **E15** (verified) attempt 2, episode 21, `runs/attempt-2/d420e95d2ee0-attempt-2/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-2/agent-logs/episode-21/response.json`: "All three required files have been successfully created:  1. **analysis_report.txt** - Contains:    - Executive Summary    - Current Log Status    - Identified Issues (6 issues found)    - Disk Space Impact Analysis    - Recommendations    "
- **E11** (verified) attempt 2, `runs/attempt-2/d420e95d2ee0-attempt-2/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-2/panes/post-test.txt:250`: "FAILED ../tests/test_outputs.py::test_analysis_report_content - AssertionError: Missing required section: SYSTEM OVERVIEW"
- **E12** (verified) attempt 2, `runs/attempt-2/d420e95d2ee0-attempt-2/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-2/panes/post-test.txt:251`: "FAILED ../tests/test_outputs.py::test_savings_calculation - AssertionError: Savings percentage not found in report"
- **E13** (verified) attempt 2, `runs/attempt-2/d420e95d2ee0-attempt-2/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-2/panes/post-test.txt:252`: "FAILED ../tests/test_outputs.py::test_issue_identification - AssertionError: No issues identified in log analysis"
- **E14** (verified) attempt 2, `runs/attempt-2/d420e95d2ee0-attempt-2/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-2/panes/post-test.txt:253`: "FAILED ../tests/test_outputs.py::test_recommendations_quality - AssertionError: Recommendations lack specificity, found 1 actionable terms"

### [info] Attempt 3: declared_done_with_failing_tests

Attempt 3 ended as declared done with failing tests; failing tests: test_analysis_report_content, test_issue_identification, test_recommendations_quality, test_savings_calculation

Evidence:
- **E20** (verified) attempt 3, episode 17, `runs/attempt-3/d420e95d2ee0-attempt-3/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-3/agent-logs/episode-17/response.json`: "All three required files have been successfully created in /app:  1. analysis_report.txt (6779 bytes) - Comprehensive human-readable report with:    - Summary of current log rotation status    - Identified issues and their severity (Critica"
- **E16** (verified) attempt 3, `runs/attempt-3/d420e95d2ee0-attempt-3/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-3/panes/post-test.txt:239`: "FAILED ../tests/test_outputs.py::test_analysis_report_content - AssertionError: Missing required section: SYSTEM OVERVIEW"
- **E17** (verified) attempt 3, `runs/attempt-3/d420e95d2ee0-attempt-3/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-3/panes/post-test.txt:240`: "FAILED ../tests/test_outputs.py::test_savings_calculation - AssertionError: Savings percentage not found in report"
- **E18** (verified) attempt 3, `runs/attempt-3/d420e95d2ee0-attempt-3/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-3/panes/post-test.txt:241`: "FAILED ../tests/test_outputs.py::test_issue_identification - AssertionError: No issues identified in log analysis"
- **E19** (verified) attempt 3, `runs/attempt-3/d420e95d2ee0-attempt-3/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-3/panes/post-test.txt:242`: "FAILED ../tests/test_outputs.py::test_recommendations_quality - AssertionError: No recommendations section found"

### [info] Attempt 4: declared_done_with_failing_tests

Attempt 4 ended as declared done with failing tests; failing tests: test_analysis_report_content, test_issue_identification, test_recommendations_quality, test_savings_calculation

Evidence:
- **E25** (verified) attempt 4, episode 25, `runs/attempt-4/d420e95d2ee0-attempt-4/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-4/agent-logs/episode-25/response.json`: "All three required files have been successfully created:  1. /app/analysis_report.txt (4412 bytes) - Human-readable report containing:    - Summary of current log rotation status    - Identified issues and their severity (4 HIGH, 1 MEDIUM) "
- **E21** (verified) attempt 4, `runs/attempt-4/d420e95d2ee0-attempt-4/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-4/panes/post-test.txt:250`: "FAILED ../tests/test_outputs.py::test_analysis_report_content - AssertionError: Missing required section: SYSTEM OVERVIEW"
- **E22** (verified) attempt 4, `runs/attempt-4/d420e95d2ee0-attempt-4/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-4/panes/post-test.txt:251`: "FAILED ../tests/test_outputs.py::test_savings_calculation - AssertionError: Savings percentage not found in report"
- **E23** (verified) attempt 4, `runs/attempt-4/d420e95d2ee0-attempt-4/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-4/panes/post-test.txt:252`: "FAILED ../tests/test_outputs.py::test_issue_identification - AssertionError: No issues identified in log analysis"
- **E24** (verified) attempt 4, `runs/attempt-4/d420e95d2ee0-attempt-4/log-rotation-analyzer/log-rotation-analyzer.1-of-1.d420e95d2ee0-attempt-4/panes/post-test.txt:253`: "FAILED ../tests/test_outputs.py::test_recommendations_quality - AssertionError: Recommendations lack specificity, found 2 actionable terms"

## Per-test pass rates

| Test | Passed | Failed | 95% interval |
|---|---|---|---|
| test_analysis_report_content | 0 | 5 | 0%-43% |
| test_analysis_report_exists | 5 | 0 | 57%-100% |
| test_issue_identification | 0 | 5 | 0%-43% |
| test_optimized_logrotate_config | 5 | 0 | 57%-100% |
| test_recommendations_quality | 0 | 5 | 0%-43% |
| test_rotation_summary_csv | 5 | 0 | 57%-100% |
| test_savings_calculation | 0 | 5 | 0%-43% |

## Attempts

| # | Outcome | Episodes | Duration (s) | Failed tests |
|---|---|---|---|---|
| 0 | declared_done_with_failing_tests | 17 | 167.27 | test_analysis_report_content, test_issue_identification, test_recommendations_quality, test_savings_calculation |
| 1 | declared_done_with_failing_tests | 16 | 169.06 | test_analysis_report_content, test_issue_identification, test_recommendations_quality, test_savings_calculation |
| 2 | declared_done_with_failing_tests | 22 | 301.69 | test_analysis_report_content, test_issue_identification, test_recommendations_quality, test_savings_calculation |
| 3 | declared_done_with_failing_tests | 18 | 179.35 | test_analysis_report_content, test_issue_identification, test_recommendations_quality, test_savings_calculation |
| 4 | declared_done_with_failing_tests | 26 | 430.58 | test_analysis_report_content, test_issue_identification, test_recommendations_quality, test_savings_calculation |

Resolved vs unresolved (descriptive): {'n': 0} vs {'n': 5, 'mean_episodes': 19.8, 'mean_duration_sec': 249.6, 'mean_input_tokens': 234967}. Descriptive only; differences at this sample size are not statistically meaningful.

## Limitations

- Pass-rate intervals are 95% Wilson intervals; with few attempts they are wide and verdicts say so.
- Attempt classification is rule-based on recorded artifacts; it does not infer the agent's intent.
- Hidden-requirement detection is lexical: a test literal counts as stated only if it appears (case-insensitively) in the instruction, and as discoverable only if the environment showed it to an agent before that agent typed it; tests that accept any of several alternatives may be over-reported.
