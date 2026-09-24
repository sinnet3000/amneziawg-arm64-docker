#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Runs the container with least privilege: NET_ADMIN + /dev/net/tun only (upstream uses
# --privileged, SYS_MODULE, /lib/modules). Bounded memory. No host firewall/sysctl changes.
set -euo pipefail
cd "$(dirname "$0")"
NAME=${NAME:-amneziawg}
# shellcheck disable=SC1091
. ./common.sh
[ -f data/awg0.conf ] || { echo "run.sh: data/awg0.conf not found (or not a file); run ./gen-config.sh first" >&2; exit 1; }
AWG_PORT=$(listen_port)
[ -n "$AWG_PORT" ] || { echo "run.sh: no ListenPort in data/awg0.conf" >&2; exit 1; }
docker run -d --name "$NAME" --restart unless-stopped \
  --cap-add NET_ADMIN --device /dev/net/tun \
  --sysctl net.ipv4.conf.all.src_valid_mark=1 \
  --sysctl net.ipv4.ip_forward=1 \
  --memory 128m --memory-swap 128m --pids-limit 100 \
  --log-driver local --log-opt max-size=5m --log-opt max-file=2 \
  -p "${AWG_PORT}:${AWG_PORT}/udp" \
  -v "$PWD/data/awg0.conf:/opt/amnezia/awg/awg0.conf:ro" \
  "$IMG"
