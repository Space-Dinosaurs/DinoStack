"""Message queue consumer using someobscureq v3.2.

Our consumer stopped acking messages after an upgrade from v2.8 to v3.2.
Messages are received and processed, but the broker never sees the ack
and redelivers them after the visibility timeout.
"""
from someobscureq import Client, AckMode


def consume():
    client = Client.connect("amqp://broker:5672")
    # In v2.8 this subscribe() call returned a Consumer that auto-acked
    # on yield; the code below preserved that pattern after the v3.2
    # upgrade.
    consumer = client.subscribe("orders", ack_mode=AckMode.MANUAL)
    for msg in consumer:
        try:
            handle(msg)
            # We call msg.complete() - this was the v2.8 API and is
            # what the upgrade checklist in our README still documents.
            msg.complete()
        except Exception:
            msg.fail()


def handle(msg):
    # Real handler elided.
    print(f"handled {msg.id}")
