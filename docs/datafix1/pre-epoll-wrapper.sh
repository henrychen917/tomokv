#!/bin/bash
# Keep a positional config file at argv[1]; explicit test engine wins.
for arg in "$@"; do
  if [ "$arg" = --net-io ]; then
    exec /home/user/Projects/cx-datafix1/build/datafix1/pre-src/build/tomokv "$@"
  fi
done
exec /home/user/Projects/cx-datafix1/build/datafix1/pre-src/build/tomokv "$@" --net-io epoll
