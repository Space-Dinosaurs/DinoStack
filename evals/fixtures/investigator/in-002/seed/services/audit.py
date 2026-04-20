"""Audit log publisher."""

from bus.event_bus import EventBus

audit_bus = EventBus()


def record(event_type, actor, details):
    audit_bus.publish("audit." + event_type, {"actor": actor, "details": details})
