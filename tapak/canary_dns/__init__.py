"""Canary DNS listener (channel 5): authoritative server, event log, open simulation.

Run it with ``python -m tapak.canary_dns --domain <domain> --db <file> --ns-ip <public IPv4>``.
See ``tapak.marker.canary`` for how copies reference their canary name and how the unit's
internal resolver keeps lookups from inside the network silent.
"""

from tapak.canary_dns.server import CanaryDNSServer, CanaryResolver, HitLogger, HitStats, simulate_open
from tapak.canary_dns.store import (
    ANCHOR_KIND,
    CanaryEvent,
    ChainReport,
    anchor_head,
    chain_head,
    check_events_chain,
    events,
    init_store,
    read_anchors,
    record_event,
    verify_events_anchored,
    verify_events_chain,
)

__all__ = [
    "ANCHOR_KIND",
    "CanaryDNSServer",
    "CanaryEvent",
    "CanaryResolver",
    "ChainReport",
    "HitLogger",
    "HitStats",
    "anchor_head",
    "chain_head",
    "check_events_chain",
    "events",
    "init_store",
    "read_anchors",
    "record_event",
    "simulate_open",
    "verify_events_anchored",
    "verify_events_chain",
]
