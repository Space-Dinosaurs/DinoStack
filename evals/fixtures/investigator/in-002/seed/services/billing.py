"""Billing service. Publishes invoice.finalized events."""

from bus.event_bus import EventBus

bus = EventBus()


def finalize_invoice(invoice):
    bus.publish("invoice.finalized", invoice)
