#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Builds the image from versions.env. The tag is derived from the two AmneziaWG versions.
set -euo pipefail
# shellcheck disable=SC1091
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
docker build -t "$IMG" \
  --build-arg GO_IMAGE="$GO_IMAGE" --build-arg ALPINE_IMAGE="$ALPINE_IMAGE" \
  --build-arg AWG_GO_TAG="$AWG_GO_TAG" --build-arg AWG_GO_COMMIT="$AWG_GO_COMMIT" \
  --build-arg AWG_TOOLS_TAG="$AWG_TOOLS_TAG" --build-arg AWG_TOOLS_COMMIT="$AWG_TOOLS_COMMIT" \
  "$HERE"
echo "built $IMG"
