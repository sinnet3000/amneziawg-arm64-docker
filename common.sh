# SPDX-License-Identifier: GPL-3.0-only
# shellcheck shell=bash
# Sourced by the other scripts: loads versions.env and derives the image tag.
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "$HERE/versions.env"
IMAGE_TAG="${AWG_GO_TAG#v}-tools${AWG_TOOLS_TAG#v}"
IMG=${IMG:-amneziawg:$IMAGE_TAG}

# The listen port comes from the server config, so run.sh and upgrade.sh cannot disagree with it.
listen_port() { awk -F' *= *' '$1=="ListenPort"{print $2; exit}' "$HERE/data/awg0.conf"; }
