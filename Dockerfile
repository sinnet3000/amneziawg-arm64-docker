# SPDX-License-Identifier: GPL-3.0-only
# Built FROM SOURCE on the arm64 host: the published amneziavpn/amneziawg-go images are amd64-only
# and the target here is aarch64 (e.g. Oracle Ampere A1). Stages follow upstream amneziawg-go/Dockerfile, but every input is
# pinned to a commit (see versions.env).
# Every input comes from versions.env via ./build.sh (no defaults here on purpose: one source of truth).
# Base images are pinned by multi-arch index digest, sources by verified git commit.
ARG GO_IMAGE
ARG ALPINE_IMAGE

FROM ${GO_IMAGE} AS awg
RUN apk add --no-cache git
ARG AWG_GO_COMMIT
RUN git clone https://github.com/amnezia-vpn/amneziawg-go.git /awg && cd /awg \
 && git checkout "$AWG_GO_COMMIT" && test "$(git rev-parse HEAD)" = "$AWG_GO_COMMIT" \
 && go mod download && go mod verify \
 && CGO_ENABLED=0 go build -trimpath -o /out/amneziawg-go .

FROM ${ALPINE_IMAGE} AS tools
ARG AWG_TOOLS_COMMIT
RUN apk add --no-cache git build-base linux-headers \
 && git clone https://github.com/amnezia-vpn/amneziawg-tools.git /t && cd /t \
 && git checkout "$AWG_TOOLS_COMMIT" && test "$(git rev-parse HEAD)" = "$AWG_TOOLS_COMMIT" \
 && cd src && make

FROM ${ALPINE_IMAGE}
ARG AWG_GO_TAG
ARG AWG_TOOLS_TAG
LABEL org.opencontainers.image.title="amneziawg" amneziawg.go="${AWG_GO_TAG}" amneziawg.tools="${AWG_TOOLS_TAG}"
# upgrade first: the pinned base image does not get Alpine's later package fixes by itself
RUN apk upgrade --no-cache && apk add --no-cache iproute2 iptables bash dumb-init
COPY --from=tools /t/src/wg /usr/bin/awg
COPY --from=tools /t/src/wg-quick/linux.bash /usr/bin/awg-quick
COPY --from=awg /out/amneziawg-go /usr/bin/amneziawg-go
RUN chmod +x /usr/bin/awg /usr/bin/awg-quick && ln -s /usr/bin/awg /usr/bin/wg && ln -s /usr/bin/awg-quick /usr/bin/wg-quick \
 && mkdir -p /opt/amnezia/awg
COPY start.sh /opt/amnezia/start.sh
RUN chmod a+x /opt/amnezia/start.sh
ENTRYPOINT ["dumb-init", "/opt/amnezia/start.sh"]
