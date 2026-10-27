#!/bin/bash
# TAPAK on Fly.io (fly.toml): one machine runs the web app and the canary DNS listener, which
# share the volume at /data (registry, keys, canary log). Fly mounts the volume as root, so the
# script starts as root, hands /data to the user tapak and runs again as tapak. When either
# service stops, the other is stopped too and Fly restarts the machine.
set -euo pipefail

if [ "$(id -u)" = 0 ]; then
    install -d -o tapak -g tapak -m 700 /data /data/keys /data/kanari /data/kanari-izin
    # Fly forwards UDP to the same port inside, so the listener needs port 53 without root.
    echo 53 > /proc/sys/net/ipv4/ip_unprivileged_port_start
    exec setpriv --reuid=tapak --regid=tapak --init-groups "$0" "$@"
fi

# Creates the code secret and the registry signing key on a new volume; keeps existing ones.
tapak keys init >/dev/null

# Fly delivers UDP only to the address fly-global-services, on the external port (and the
# replies must leave from it), and TCP to the machine's own address.
python -m tapak.canary_dns --host fly-global-services --tcp-host 0.0.0.0 --port 53 \
    --ns-ip "${TAPAK_CANARY_NS_IP:?set TAPAK_CANARY_NS_IP to the dedicated IPv4 of the app}" \
    --answer-ip "${TAPAK_CANARY_ANSWER_IP:-127.0.0.1}" &
dns=$!
uvicorn tapak.web.app:app --host 0.0.0.0 --port 8000 &
web=$!
# Every hour the head of the canary log is anchored (and signed) in the registry, so a later
# rewrite of the log shows; a run without new events writes nothing. Errors go to the log.
(while sleep 3600; do python -m tapak.canary_dns --anchor >/dev/null || true; done) &
anchor=$!

trap 'kill -TERM "$dns" "$web" "$anchor" 2>/dev/null' TERM INT
status=0
wait -n "$dns" "$web" || status=$?
kill -TERM "$dns" "$web" "$anchor" 2>/dev/null || true
wait || true
exit "$status"
