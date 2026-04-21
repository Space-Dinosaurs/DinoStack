"""Structured logging setup. Honors ADR-0002."""
import structlog


def configure() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


def bind_correlation_id(correlation_id: str) -> None:
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
