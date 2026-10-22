#!/bin/bash
# Invoke gate jobs only, with no ABBA measurement or throughput load generator.
set -u
cd /home/user/Projects/cx-notifyorder
taskset -c 96-111 bash docs/notifyorder/run-final-directed.sh --now
taskset -c 96-111 bash docs/notifyorder/run-proof.sh post
taskset -c 96-111 bash docs/notifyorder/run-proof.sh differ
taskset -c 96-111 bash docs/notifyorder/run-proof.sh pre
taskset -c 96-111 bash docs/notifyorder/run-final-units.sh
