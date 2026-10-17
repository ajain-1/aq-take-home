| Task | Verdict | Stages run | Errors | Warnings | Findings |
|---|---|---|---|---|---|
| broken-coordinate-transform | PASS | static, image_probe, oracle, nop | 0 | 0 | — |
| broken-flask-api | PASS | static, image_probe, oracle, nop | 0 | 0 | **info** `nop/tests_require_work`: 1/9 test(s) pass on the untouched environment and don't measure the agent's work: test_requirements_file_exists |
| config-manifest-validator | PASS | static, image_probe, oracle, nop | 0 | 0 | — |
| csv-to-json-cli-fix | PASS | static, image_probe, oracle, nop | 0 | 0 | **info** `nop/tests_require_work`: 1/5 test(s) pass on the untouched environment and don't measure the agent's work: test_utf8_stdout_encoding |
| fix-maven-artifact-dependencies | PASS | static, image_probe, oracle, nop | 0 | 0 | — |
| log-rotation-analyzer | PASS | static, image_probe, oracle, nop | 0 | 1 | **warning** `static/unstated_test_literals`: tests require text the instruction never states and the task never shows (test_analysis_report_content: 'Estimated total savings:', 'LOG FILE ANALYSIS', 'LOG ROTATION ANALYSIS REPORT', 'SYSTEM OVERVIEW', 'Total log size:'; test_savings_calculation: 'Potential space reduction:'; test_issue_identification: 'HIGH', 'Large file', 'MEDIUM'; test_recommendations_quality: 'RECOMMENDATIONS:', 'monitor'); state the expected format in the instruction or relax the tests |
