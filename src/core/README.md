# Core

Server and thread state, shard routing, IO/executor loops, local-read reclamation,
and load/role controllers live here. This directory coordinates the ownership
and scheduling rules that cross the command, storage, and network boundaries.

`latency-tracking yes|no` uses Redis 7.4's grammar but deliberately defaults to
`no` in TomoKV (Redis defaults to `yes`). `latency-tracking-info-percentiles`
defaults to `50 99 99.9`; it accepts space-separated values in [0,100], preserving
order and duplicates. An empty string suppresses percentile fields. Both settings
support the config file and CONFIG GET/SET/REWRITE. Tracking records execution
durations for LATENCY HISTOGRAM and INFO latencystats; CONFIG RESETSTAT clears
histograms, while LATENCY RESET affects only the separate latency monitor.
