# Tests

Protocol and concurrency batteries, differential checks, serverless C++ units,
and the publication gates live here. Start with the
[testing and gate guide](../docs/gates.md) for commands, dependencies, and tiers.

`make unit` runs the basic serverless units. Many additional Makefile targets
build units with named regression sections; `gate.sh` supplies their selectors
and also runs server-backed batteries and sanitizer controls. Its explicit
boot geometry differs from a default server startup.

`fixtures/` and `standing-null/` contain inputs read by tests and gates, not
scratch outputs. `survey/` is retained because its self-tests are a gate row.
Store new run artifacts under `build/`; run server and performance batteries
on a quiet machine with an assigned CPU and port allocation.
