# AmneziaWG 3.1 in a Docker container for arm64

This repo runs an AmneziaWG 3.1 server in a Docker container on an arm64 (aarch64) VPS, such as an Oracle
Ampere A1, and changes nothing on the host outside Docker. It adapts the scripts the official Amnezia app
pushes over SSH (`amnezia-client/client/server_scripts/awg/`, commit `94b51df`) and turns each step into a
file you can read.

I wanted full control of the installation and none of the extras the Amnezia app's deploy adds. It runs a host
firewall script that drops ICMP echo requests and rewrites global TCP sysctls, starts the container with
`--privileged`, and pulls an unpinned `latest` image.

Its scripts also do not support arm64, because the image they build on is amd64 only. This repo builds from
source instead.

## Requirements

- An arm64 Linux host with Docker (Compose is not needed), root or sudo, and `/dev/net/tun`.
- Outbound access to GitHub, the Go module proxy and the Alpine mirrors during the build.
- An inbound UDP port (default 51820) open in whatever firewall or cloud security list sits in front of the
  host. Docker's published port bypasses the host's `INPUT` chain, so that outer firewall usually does the
  filtering.

## Quick start

```bash
git clone <this repo> && cd <repo-dir>
ENDPOINT=vpn.example.com AWG_PORT=51820 ./gen-config.sh   # builds the image (./build.sh), writes ./data (mode 700)
./run.sh                                                    # starts the container (port from data/awg0.conf)
docker exec amneziawg awg show                              # interface, params, peer
```

`gen-config.sh` builds the image if it does not exist yet. It then generates the server and client keys, a
pre-shared key and the obfuscation parameters, and writes two files into `data/`:

- `awg0.conf` is the server config. `run.sh` mounts it read-only into the container.
- `client1.conf` is the client config. You import it into your AmneziaWG client (see below).

The script prints no keys. If `data/awg0.conf` already exists, it stops, so a rerun cannot overwrite a working
server.

Take care of `data/`. It holds the server and client keys, and nothing else has a copy. `upgrade.sh` never
touches it.

### Client

Import `data/client1.conf` into a client that supports the 3.1 parameters, such as AmneziaVPN 5.0.1.5 or
newer. The file holds the client's private key and the pre-shared key, so delete your copies once it is
imported.

### Verify

```bash
docker exec amneziawg awg show   # a 'latest handshake' line means a client connected
docker logs amneziawg
```

If a client connects but no traffic passes, check that the obfuscation parameters match on both sides.

## How it works

```
client (AmneziaWG 3.1)  --udp/51820-->  host  --docker port publish-->  container
                                                                          amneziawg-go (userspace)
                                                                          awg0  10.8.1.1/24
                                                                          MASQUERADE -> eth0 -> internet
```

- `amneziawg-go` runs in userspace inside the container, and `awg-quick` falls back to it when the host has
  no `amneziawg` kernel module, so it needs no DKMS, no reboot and no PPA.
- The image is built from source because Amnezia's published `amneziavpn/amneziawg-go` images are amd64 only.
  The Dockerfile compiles `amneziawg-go` and `amneziawg-tools` from git commits on digest-pinned `golang` and
  `alpine` base images. Every pin lives in `versions.env`. (Upstream's own Dockerfile uses `alpine:3.19`,
  which has been end of life since 2025-11-01.)
- The image is about 30 MB, and the container used about 3.5 MiB of RAM when idle.

## Differences from the Amnezia app's deploy

| Amnezia app | This repo |
|---|---|
| `setup_host_firewall.sh` (drops ICMP echo, sets host sysctls including `hybla`, adds FORWARD jumps) | Not run. The host changes only through Docker's own port-publish rules |
| `docker run --privileged --cap-add SYS_MODULE -v /lib/modules` | `--cap-add NET_ADMIN --device /dev/net/tun` only |
| `amneziawg-go:latest`, `apk upgrade`, `--no-cache --pull` | Source build at pinned commits, no `apk upgrade` |
| A dedicated `amnezia-dns` container and network | The default Docker bridge; client DNS is a plain setting |
| `--restart always`, logging off | `--restart unless-stopped`, 128 MB memory cap, `--pids-limit 100`, small local log, `net.ipv4.ip_forward=1` set explicitly |
| The script keeps idling if setup fails | `start.sh` exits non-zero on a missing config or a failed step, so the failure shows |

## Parameters

`gen-config.sh` uses the Amnezia app's 3.1 defaults (`protocolConstants.h`) and its default client DNS
(`1.1.1.1`, `1.0.0.1`). The one difference is that `I1` is also set on the server. Edit the script to change a value.

The tunnel is IPv4 only, as in the app. The client routes `::/0` into it, so IPv6 traffic is dropped.

## Updating

Updating takes two steps, so you see what changes before anything is rebuilt:

```bash
./update.py            # 1. CHECK: compare versions.env with upstream; changes nothing (exit 10 = something is newer)
./update.py --apply    #    rewrite versions.env only (a text file); no image is built, nothing is restarted
git diff versions.env  #    review the new tags, commits and digests
./upgrade.sh           # 2. REBUILD + RECREATE: builds a new image from versions.env and replaces the container
```

`update.py` looks for the newest `amneziawg-go` and `amneziawg-tools` tag of the same major version and
resolves each to its commit. It also looks for the newest stable `golang` and `alpine` base images, resolves
them to their multi-arch digests, and notices when a pinned tag has moved. It writes only `versions.env`. The
running image changes only when you run `upgrade.sh`.

`upgrade.sh` runs `./build.sh` (the image tag comes from the two AmneziaWG versions), then removes and
recreates the container with the same port and config. It never touches `data/`, so your keys and client
config stay valid. If the new container is unhealthy after a few seconds, the script prints its logs, starts
the previous image again and exits 1. Expect a few seconds of downtime.

After an upgrade, check that a client reconnects and commit `versions.env`. `docker image prune` removes the
old images.

Pinned means frozen. A container you never upgrade keeps its old Alpine and Go, without their security fixes.
Run `./update.py` now and then. It only reads, so it also works from cron.

## Files

| File | Purpose |
|---|---|
| `versions.env` | Every pinned version, tag, commit and digest (single source of truth) |
| `Dockerfile`, `build.sh` | Build the image from `versions.env`; `common.sh` derives the image tag |
| `gen-config.sh` | Generate the server and client configs into `data/` |
| `run.sh`, `start.sh` | Start the container; the container entrypoint |
| `update.py`, `upgrade.sh` | Check for newer versions; rebuild and recreate with rollback |

## Removal

```bash
docker rm -f amneziawg
docker image prune -f   # or docker rmi <the amneziawg image>
rm -rf data             # deletes the server and client keys
```

The repo changes no host files, firewall rules or sysctls, so nothing else needs undoing.

## Sources

- `amnezia-vpn/amnezia-client`, `client/server_scripts/awg/`, commit `94b51df` (the app's deploy scripts)
- `amnezia-vpn/amneziawg-go` (its Dockerfile is the model for the build stages)
- `amnezia-vpn/amneziawg-tools`
- amnezia-client issue #3082 (self-hosted 3.1 defaults)

## License

GPL-3.0-only (see `LICENSE`). The scripts are adapted from `amnezia-client`, which is GPL-3.0.
