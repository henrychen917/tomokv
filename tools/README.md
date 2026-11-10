# Build and gate tools

This directory contains the source-map and formatting helpers, metadata
generators, disposable correctness-control builders, and drivers referenced by
the Makefile or retained tests. These tools are separate from the server runtime.
Their generated artifacts belong under `build/`.

`make tools` builds the retained load drivers used by test and publication
workflows. [tailgen](tailgen/README.md) is the smooth open-loop RESP driver;
`make tailgen-unit` runs its serverless correctness and pacing units.

Read the [publication gate guide](../docs/gates.md) before running a tool that
starts a server or collects measurements. Reference binaries and the NIC test
rig are supplied separately.
