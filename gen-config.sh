#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Generates server + client AmneziaWG 3.1 configs into ./data (mode 700). Run on the host.
# Values mirror the app's defaults (protocolConstants.h, awgInstaller.cpp @ 94b51df), including Jc
# picked at random from 4 to 6. I1 is set on both sides.
set -euo pipefail
cd "$(dirname "$0")"
: "${AWG_PORT:=51820}"   # udp port to listen on / publish
: "${ENDPOINT:?set ENDPOINT to the server public hostname or IP}"
SUBNET_BASE=10.8.1
# shellcheck disable=SC1091
. ./common.sh
awg() { docker run --rm --entrypoint awg "$IMG" "$@"; }
docker image inspect "$IMG" >/dev/null 2>&1 || ./build.sh

umask 077; mkdir -p data
[ -e data/awg0.conf ] && { echo "data/awg0.conf exists; refusing to overwrite" >&2; exit 1; }

SPRIV=$(awg genkey); SPUB=$(printf %s "$SPRIV" | docker run --rm -i --entrypoint awg "$IMG" pubkey)
CPRIV=$(awg genkey); CPUB=$(printf %s "$CPRIV" | docker run --rm -i --entrypoint awg "$IMG" pubkey)
PSK=$(awg genpsk); HPK=$(awg genkey)   # header-protection key: same format as the app (a WG private key)

I1='<r 2><b 0x858000010001000000000669636c6f756403636f6d0000010001c00c000100010000105a00044d583737>'
JC=$((4 + RANDOM % 3))
COMMON="Jc = $JC
Jmin = 10
Jmax = 50
S1 = 12
S2 = 12
S3 = 12
S4 = 12
H1 = 1
H2 = 2
H3 = 3
H4 = 4
I1 = $I1
HeaderProtectionKey = $HPK
ContentPaddingAddition = 10-100
RekeyAfterTime = 100-120
RekeyTimeout = 3-7
RejectAfterTime = 150-180
KeepaliveTimeout = 5-15
MaxHandshakeAttempts = 15-20
RandomTrailers = on
DisableCookies = on"

cat > data/awg0.conf <<CONF
[Interface]
PrivateKey = $SPRIV
Address = $SUBNET_BASE.1/24
ListenPort = $AWG_PORT
$COMMON

[Peer]
PublicKey = $CPUB
PresharedKey = $PSK
AllowedIPs = $SUBNET_BASE.2/32
CONF

cat > data/client1.conf <<CONF
[Interface]
Address = $SUBNET_BASE.2/32
DNS = 1.1.1.1, 1.0.0.1
PrivateKey = $CPRIV
$COMMON

[Peer]
PublicKey = $SPUB
PresharedKey = $PSK
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = $ENDPOINT:$AWG_PORT
PersistentKeepalive = 25-35
CONF
echo "wrote data/awg0.conf (server) and data/client1.conf (import into the app). Neither is printed."
