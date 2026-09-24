#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Rebuild from versions.env and recreate the container. data/ (keys, config) is never touched.
# If the new container does not come up healthy, the previous image is started again.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
. ./common.sh
NAME=${NAME:-amneziawg}
[ -f data/awg0.conf ] || { echo "upgrade.sh: data/awg0.conf not found; nothing to upgrade (run gen-config.sh first)" >&2; exit 1; }

old_img=$(docker inspect -f '{{.Image}}' "$NAME" 2>/dev/null || true)
./build.sh
new_id=$(docker image inspect -f '{{.Id}}' "$IMG")
if [ -n "$old_img" ] && [ "$old_img" = "$new_id" ]; then
  echo "container $NAME already runs $IMG; nothing to do"; exit 0
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true
healthy() {
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ] && docker exec "$NAME" awg show awg0 >/dev/null 2>&1
}
# A failing run.sh (port conflict, bad image) must reach the rollback too, so it sits inside the condition.
if NAME=$NAME ./run.sh >/dev/null && sleep 8 && healthy; then
  echo "upgraded: $NAME now runs $IMG"
  docker exec "$NAME" awg show awg0 latest-handshakes || true
  echo "check a client reconnects, then remove the old image if you like: docker image prune"
else
  echo "upgrade.sh: the new container did not start healthy; logs:" >&2
  docker logs --tail 20 "$NAME" >&2 || true
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  if [ -n "$old_img" ]; then
    # Same health bar as the upgrade path: a rollback that does not serve the tunnel is a failure.
    if IMG=$old_img NAME=$NAME ./run.sh >/dev/null && sleep 8 && healthy; then
      echo "rolled back to the previous image ($old_img)" >&2
    else
      docker logs --tail 20 "$NAME" >&2 || true
      echo "upgrade.sh: the rollback is not healthy; $NAME is not serving the tunnel" >&2
    fi
  fi
  exit 1
fi
