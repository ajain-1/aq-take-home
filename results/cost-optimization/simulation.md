# Adaptive attempts vs. always-10

All expectations are exact: every one of the 1024 outcome sequences of 10 runs is replayed and
weighted by p^passes (1-p)^failures. Latency is in waves (one wave = one attempt's wall time);
always-10 is 10 attempts in 1 wave.

**Exactness:** the exact policy (confidence 1.0) misclassified 0 of 4096 (sequence, wave cap) cases versus the 10-run rule.

## Exact policy: cost and latency by wave cap

Expected attempts are identical for every wave cap (parallel waves never launch an attempt a
one-at-a-time policy would skip); only latency changes.

| p | attempts | saved vs 10 | waves (cap 1) | waves (cap 3) | waves (cap 5) | waves (cap 10) | batches-of-5 attempts | batches-of-5 waves |
|---|---|---|---|---|---|---|---|---|
| 0.00 | 9.00 | 10% | 9.00 | 4.00 | 3.00 | 3.00 | 10.00 | 2.00 |
| 0.05 | 9.14 | 9% | 9.14 | 4.67 | 3.67 | 3.67 | 9.89 | 1.98 |
| 0.10 | 8.87 | 11% | 8.87 | 4.80 | 3.80 | 3.80 | 9.64 | 1.93 |
| 0.15 | 8.39 | 16% | 8.39 | 4.62 | 3.62 | 3.62 | 9.31 | 1.86 |
| 0.20 | 7.86 | 21% | 7.86 | 4.31 | 3.31 | 3.31 | 8.98 | 1.80 |
| 0.25 | 7.36 | 26% | 7.36 | 3.97 | 2.98 | 2.98 | 8.68 | 1.74 |
| 0.30 | 6.97 | 30% | 6.97 | 3.66 | 2.68 | 2.68 | 8.46 | 1.69 |
| 0.35 | 6.69 | 33% | 6.69 | 3.44 | 2.46 | 2.46 | 8.32 | 1.66 |
| 0.40 | 6.56 | 34% | 6.56 | 3.31 | 2.34 | 2.34 | 8.27 | 1.65 |
| 0.45 | 6.56 | 34% | 6.56 | 3.29 | 2.32 | 2.32 | 8.32 | 1.66 |
| 0.50 | 6.69 | 33% | 6.69 | 3.35 | 2.40 | 2.40 | 8.44 | 1.69 |
| 0.55 | 6.94 | 31% | 6.94 | 3.49 | 2.55 | 2.55 | 8.62 | 1.72 |
| 0.60 | 7.27 | 27% | 7.27 | 3.69 | 2.75 | 2.75 | 8.85 | 1.77 |
| 0.65 | 7.65 | 24% | 7.65 | 3.90 | 2.96 | 2.96 | 9.09 | 1.82 |
| 0.70 | 8.04 | 20% | 8.04 | 4.10 | 3.16 | 3.16 | 9.34 | 1.87 |
| 0.75 | 8.38 | 16% | 8.38 | 4.23 | 3.29 | 3.29 | 9.56 | 1.91 |
| 0.80 | 8.64 | 14% | 8.64 | 4.26 | 3.31 | 3.31 | 9.74 | 1.95 |
| 0.85 | 8.74 | 13% | 8.74 | 4.14 | 3.18 | 3.18 | 9.88 | 1.98 |
| 0.90 | 8.65 | 13% | 8.65 | 3.86 | 2.88 | 2.88 | 9.96 | 1.99 |
| 0.95 | 8.39 | 16% | 8.39 | 3.45 | 2.45 | 2.45 | 9.99 | 2.00 |
| 1.00 | 8.00 | 20% | 8.00 | 3.00 | 2.00 | 2.00 | 10.00 | 2.00 |

## Confidence-based stopping: cost vs. misclassification

Stops once the posterior predictive probability of one class (uniform prior on p) reaches the
threshold. Error = probability the label differs from what all 10 runs would have given.

| p | exact w10 attempts | conf 0.99 attempts | conf 0.95 attempts | conf 0.9 attempts | conf 0.99 error | conf 0.95 error | conf 0.9 error |
|---|---|---|---|---|---|---|---|
| 0.00 | 9.00 | 9.00 | 8.00 | 7.00 | 0.000 | 0.000 | 0.000 |
| 0.05 | 9.14 | 9.14 | 8.45 | 7.67 | 0.000 | 0.002 | 0.005 |
| 0.10 | 8.87 | 8.87 | 8.39 | 7.77 | 0.000 | 0.004 | 0.013 |
| 0.15 | 8.39 | 8.39 | 8.07 | 7.55 | 0.000 | 0.006 | 0.020 |
| 0.20 | 7.86 | 7.86 | 7.65 | 7.18 | 0.000 | 0.007 | 0.022 |
| 0.25 | 7.36 | 7.36 | 7.24 | 6.76 | 0.000 | 0.006 | 0.022 |
| 0.30 | 6.97 | 6.97 | 6.89 | 6.38 | 0.000 | 0.006 | 0.020 |
| 0.35 | 6.69 | 6.69 | 6.64 | 6.07 | 0.000 | 0.005 | 0.019 |
| 0.40 | 6.56 | 6.56 | 6.52 | 5.87 | 0.000 | 0.005 | 0.020 |
| 0.45 | 6.56 | 6.55 | 6.52 | 5.77 | 0.001 | 0.005 | 0.024 |
| 0.50 | 6.69 | 6.68 | 6.64 | 5.78 | 0.001 | 0.006 | 0.030 |
| 0.55 | 6.94 | 6.91 | 6.85 | 5.88 | 0.001 | 0.007 | 0.040 |
| 0.60 | 7.27 | 7.22 | 7.13 | 6.04 | 0.002 | 0.009 | 0.051 |
| 0.65 | 7.65 | 7.57 | 7.43 | 6.25 | 0.002 | 0.010 | 0.062 |
| 0.70 | 8.04 | 7.92 | 7.72 | 6.44 | 0.002 | 0.010 | 0.070 |
| 0.75 | 8.38 | 8.21 | 7.93 | 6.59 | 0.002 | 0.009 | 0.073 |
| 0.80 | 8.64 | 8.38 | 7.99 | 6.63 | 0.002 | 0.007 | 0.068 |
| 0.85 | 8.74 | 8.36 | 7.86 | 6.51 | 0.001 | 0.005 | 0.054 |
| 0.90 | 8.65 | 8.12 | 7.48 | 6.20 | 0.000 | 0.002 | 0.033 |
| 0.95 | 8.39 | 7.65 | 6.84 | 5.69 | 0.000 | 0.000 | 0.011 |
| 1.00 | 8.00 | 7.00 | 6.00 | 5.00 | 0.000 | 0.000 | 0.000 |

## Summary (p uniform on [0, 1])

| policy | attempts | saved vs 10 | waves | error rate |
|---|---|---|---|---|
| exact w10 | 7.85 | 22% | 2.91 | 0.000 |
| conf 0.99 | 7.69 | 23% | 2.90 | 0.001 |
| conf 0.95 | 7.34 | 27% | 2.90 | 0.005 |
| conf 0.9 | 6.43 | 36% | 2.90 | 0.031 |
| batches of 5 | 9.21 | 8% | 1.84 | 0.000 |

Measured from 8 real terminus-1 attempts: $0.605 per attempt at $5/$25 per Mtok in/out (tokenizer estimates, no caching discount). Always-10 = $6.05 per task.

- exact w10: $4.75 per task
- conf 0.99: $4.65 per task
- conf 0.95: $4.44 per task
- conf 0.9: $3.89 per task
- batches of 5: $5.57 per task
