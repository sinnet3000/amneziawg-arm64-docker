#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
# Adapted from amnezia-client client/server_scripts/awg/start.sh (GPL-3.0). Only touches the container's own netns.
set -eu
CONF=/opt/amnezia/awg/awg0.conf

# Fail loudly instead of idling with no VPN: a missing config or a failed step exits non-zero,
# so `docker ps` shows the container restarting and `docker logs` says why.
[ -f "$CONF" ] || { echo "start.sh: $CONF is missing; run gen-config.sh and mount data/awg0.conf" >&2; exit 1; }

awg-quick down "$CONF" 2>/dev/null || true
awg-quick up "$CONF"
# The tunnel subnet comes from the interface address in the config, so only gen-config.sh defines it.
AWG_SUBNET=$(ip -4 -o addr show dev awg0 | awk '{print $4}')
# Outbound interface from the default route; eth0 is not guaranteed in every network namespace.
WAN_IF=$(ip -o -4 route show to default | awk '{print $5; exit}')
[ -n "$WAN_IF" ] || { echo "start.sh: no default route; cannot place NAT rules" >&2; exit 1; }

iptables -A INPUT   -i awg0 -j ACCEPT
iptables -A FORWARD -i awg0 -j ACCEPT
iptables -A OUTPUT  -o awg0 -j ACCEPT
iptables -A FORWARD -i awg0 -o "$WAN_IF" -s "$AWG_SUBNET" -j ACCEPT
iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -t nat -A POSTROUTING -s "$AWG_SUBNET" -o "$WAN_IF" -j MASQUERADE

# Stay up only while the tunnel does: if amneziawg-go dies, exit non-zero so Docker's restart policy recreates it.
trap 'exit 0' TERM INT
while awg show awg0 >/dev/null 2>&1; do sleep 10 & wait $!; done
echo "start.sh: awg0 is gone; exiting so Docker restarts the container" >&2
exit 1
