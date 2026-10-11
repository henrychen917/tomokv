#!/bin/bash
# Maintainer runtime handoff ONLY. This file has not been executed.
set -euo pipefail
cd /home/user/Projects/cx-respresume

# pre-audit-reproductions
env taskset -c 112-127 python3 tools/respresume_repro.py run --binary build/tomokv-respresume-pre --observer build/respresume-observer-pre/tomokv --output docs/respresume/runtime-pre

# post-audit-reproductions
env taskset -c 112-127 python3 tools/respresume_repro.py run --binary build/tomokv-respresume-post --observer build/respresume-observer-post/tomokv --output docs/respresume/runtime-post --post

# pre-new-rows
env 'GATE_ONLY_JOBS=respresume-fragment-1s-epoll respresume-fragment-1s-uring respresume-fragment-2s-epoll respresume-fragment-2s-uring respresume-cpu-1s-epoll respresume-cpu-1s-uring respresume-cpu-2s-epoll respresume-cpu-2s-uring respresume-neighbour-1s-epoll respresume-neighbour-1s-uring respresume-neighbour-2s-epoll respresume-neighbour-2s-uring' REDIS74_ROOT=/home/user/Projects/redis74 taskset -c 112-127 tests/gate.sh quick --server-cores 112-119 --load-cores 120-127 --ports 25400-25449 --candidate-binary /home/user/Projects/cx-respresume/build/tomokv-respresume-pre

# post-new-rows
env 'GATE_ONLY_JOBS=respresume-fragment-1s-epoll respresume-fragment-1s-uring respresume-fragment-2s-epoll respresume-fragment-2s-uring respresume-cpu-1s-epoll respresume-cpu-1s-uring respresume-cpu-2s-epoll respresume-cpu-2s-uring respresume-neighbour-1s-epoll respresume-neighbour-1s-uring respresume-neighbour-2s-epoll respresume-neighbour-2s-uring' REDIS74_ROOT=/home/user/Projects/redis74 taskset -c 112-127 tests/gate.sh quick --server-cores 112-119 --load-cores 120-127 --ports 25400-25449 --candidate-binary /home/user/Projects/cx-respresume/build/tomokv-respresume-post

# existing-netcap-respcompat-netio-tls
env 'GATE_ONLY_JOBS=netcap respcompat netio-1s netio-2s tls' REDIS74_ROOT=/home/user/Projects/redis74 taskset -c 112-127 tests/gate.sh quick --server-cores 112-119 --load-cores 120-127 --ports 25400-25449 --candidate-binary /home/user/Projects/cx-respresume/build/tomokv-respresume-post

# differ-epoll-split
env GATE_LOAD_CORES=120-127 REDIS74_ROOT=/home/user/Projects/redis74 GATE_DIFFER_GEOMETRY=split GATE_DIFFER_PROOF_SEEDS=/home/user/Projects/cx-respresume/docs/respresume/proof-seeds.txt GATE_DIFFER_PROOF_SUITES=/home/user/Projects/cx-respresume/docs/respresume/proof-suites.txt GATE_DIFFER_OUT=/home/user/Projects/cx-respresume/docs/respresume/runtime-differ-epoll-split taskset -c 112-127 tests/differ_gate.sh /home/user/Projects/cx-respresume/build/respresume-epoll 25420 25421 112-119 6:2

# differ-epoll-armed-fused
env GATE_LOAD_CORES=120-127 REDIS74_ROOT=/home/user/Projects/redis74 GATE_DIFFER_GEOMETRY=armed-fused GATE_DIFFER_PROOF_SEEDS=/home/user/Projects/cx-respresume/docs/respresume/proof-seeds.txt GATE_DIFFER_PROOF_SUITES=/home/user/Projects/cx-respresume/docs/respresume/proof-suites.txt GATE_DIFFER_OUT=/home/user/Projects/cx-respresume/docs/respresume/runtime-differ-epoll-armed-fused taskset -c 112-127 tests/differ_gate.sh /home/user/Projects/cx-respresume/build/respresume-epoll 25420 25421 112-119 6:2

# differ-uring-split
env GATE_LOAD_CORES=120-127 REDIS74_ROOT=/home/user/Projects/redis74 GATE_DIFFER_GEOMETRY=split GATE_DIFFER_PROOF_SEEDS=/home/user/Projects/cx-respresume/docs/respresume/proof-seeds.txt GATE_DIFFER_PROOF_SUITES=/home/user/Projects/cx-respresume/docs/respresume/proof-suites.txt GATE_DIFFER_OUT=/home/user/Projects/cx-respresume/docs/respresume/runtime-differ-uring-split taskset -c 112-127 tests/differ_gate.sh /home/user/Projects/cx-respresume/build/respresume-uring 25420 25421 112-119 6:2

# differ-uring-armed-fused
env GATE_LOAD_CORES=120-127 REDIS74_ROOT=/home/user/Projects/redis74 GATE_DIFFER_GEOMETRY=armed-fused GATE_DIFFER_PROOF_SEEDS=/home/user/Projects/cx-respresume/docs/respresume/proof-seeds.txt GATE_DIFFER_PROOF_SUITES=/home/user/Projects/cx-respresume/docs/respresume/proof-suites.txt GATE_DIFFER_OUT=/home/user/Projects/cx-respresume/docs/respresume/runtime-differ-uring-armed-fused taskset -c 112-127 tests/differ_gate.sh /home/user/Projects/cx-respresume/build/respresume-uring 25420 25421 112-119 6:2
