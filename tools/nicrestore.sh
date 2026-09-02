#!/bin/bash
# Restore the 25GbE two-namespace bench rig after a reboot. Idempotent.
# Everything here dies on restart: the namespaces, IP assignments, and the ethtool
# coalescing settings (measured: stock coalescing costs ~53us of RTT — 87/117us floor
# vs 34/55us at rx-usecs 1). Uses the standing sudoers grant (/etc/sudoers.d/tomokv-nic,
# NOPASSWD /usr/sbin/ip) — ethtool runs THROUGH ip netns exec, needing no extra grant.
set -u
CIF=eno12399np0   # client side, 10.200.0.1 (clientns)
SIF=eno12409np1   # server side, 10.200.0.2 (serverns)

ns_up() { # NS IF IP
  local NS=$1 IF=$2 IP=$3
  sudo -n ip netns add "$NS" 2>/dev/null
  # If the interface still sits in the root namespace, move it.
  if ip link show "$IF" >/dev/null 2>&1; then
    sudo -n ip link set "$IF" netns "$NS"
  fi
  sudo -n ip netns exec "$NS" ip addr replace "$IP/24" dev "$IF"
  sudo -n ip netns exec "$NS" ip link set "$IF" up
  sudo -n ip netns exec "$NS" ip link set lo up
  # The latency-critical part — ethtool -C never persists:
  sudo -n ip netns exec "$NS" ethtool -C "$IF" adaptive-rx off rx-usecs 1 rx-frames 1
}

ns_up clientns $CIF 10.200.0.1
ns_up serverns $SIF 10.200.0.2

echo "--- verify ---"
sudo -n ip netns exec serverns ethtool $SIF | grep -E "Speed|Link detected"
sudo -n ip netns exec clientns ping -c 2 -i 0.2 10.200.0.2 | tail -2
for NS_IF in "clientns:$CIF" "serverns:$SIF"; do
  NS=${NS_IF%%:*}; IF=${NS_IF#*:}
  sudo -n ip netns exec $NS ethtool -c $IF | grep -E "^rx-usecs:|^rx-frames:" | tr '\n' ' '
  echo "($NS)"
done
echo "NOTE: NIC IRQ affinities land on CPUs 63-190 by default and collide with bench"
echo "geometries — re-pin per the run's geometry before trusting NIC numbers"
echo "(irqbalance is not installed, so pins stick until the next reboot)."
