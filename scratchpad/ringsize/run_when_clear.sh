#!/bin/bash
# Wait for this lane's cores to clear, then run the phases given. The box is shared by many lanes;
# starting a measurement the moment a neighbour finishes is the difference between a verdict and a
# two-lane average. Gives up rather than measuring dirty.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
DEADLINE=$(( $(date +%s) + ${WAIT_S:-5400} ))
until "$HERE/laneguard.sh" >/dev/null 2>&1; do
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "GAVE UP waiting for clear cores at $(date +%T); last state:"
    "$HERE/laneguard.sh"
    exit 1
  fi
  sleep 20
done
echo "cores clear at $(date +%T), starting: $*"
exec "$HERE/validate.sh" "$@"
