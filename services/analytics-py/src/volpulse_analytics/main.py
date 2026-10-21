"""Entry point of the VolPulse analytics engine.

    volpulse-analytics --config config/analytics.yaml

The process is a long-running consumer:

1. read the configuration from the environment,
2. subscribe to the broker,
3. decode, validate, compute and persist,
4. export metrics on ``/metrics`` for Prometheus to scrape.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from types import FrameType

from volpulse_core.config import Settings, load_settings
from volpulse_core.observability.metrics import VolPulseMetrics

from volpulse_analytics.consumer import AnalyticsConsumer, ProtobufQuoteDecoder
from volpulse_analytics.persistence.timescale import TimescaleConnection, TimescaleWriter

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="volpulse-analytics",
        description="VolPulse quantitative analytics engine.",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=9100,
        help="Port the Prometheus metrics endpoint binds to (default: 9100).",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Compute but do not write to the time-series store.",
    )
    return parser


def _install_signal_handlers(stop: threading.Event) -> None:
    """Stop the consumer cleanly on SIGINT/SIGTERM."""

    def handle(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)


def main(argv: list[str] | None = None) -> int:
    """Run the analytics engine.

    Args:
        argv: Command line arguments. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    args = _build_parser().parse_args(argv)

    try:
        settings: Settings = load_settings()
    except RuntimeError as error:
        print(f"volpulse-analytics: {error}", file=sys.stderr)
        return 2

    metrics = VolPulseMetrics()
    writer = None
    if not args.no_persist:
        writer = TimescaleWriter(TimescaleConnection.from_settings(settings))

    try:
        decoder = ProtobufQuoteDecoder()
    except ImportError as error:
        print(f"volpulse-analytics: {error}", file=sys.stderr)
        return 2

    consumer = AnalyticsConsumer(decoder, metrics, writer)

    try:
        # Imported lazily so that `--help` and a configuration error do not
        # pay for the client library.
        from prometheus_client import start_http_server  # noqa: PLC0415

        start_http_server(args.metrics_port)
    except OSError as error:
        print(f"volpulse-analytics: cannot bind metrics port: {error}", file=sys.stderr)
        return 1

    stop = threading.Event()
    _install_signal_handlers(stop)

    print(
        f"volpulse-analytics starting: brokers={settings.kafka_bootstrap_servers} "
        f"topics={settings.kafka_topic_options},{settings.kafka_topic_quotes} "
        f"metrics=:{args.metrics_port}",
        flush=True,
    )

    _consume_forever(settings, consumer, stop)
    print("volpulse-analytics stopped", flush=True)
    return 0


def _consume_forever(
    settings: Settings, consumer: AnalyticsConsumer, stop: threading.Event
) -> None:
    """Consume from the broker until the stop event is set."""
    # Imported lazily: the broker client is only needed once the process is
    # actually configured and running.
    from confluent_kafka import Consumer, KafkaError  # noqa: PLC0415

    kafka = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": settings.kafka_consumer_group,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "session.timeout.ms": 45000,
        }
    )
    kafka.subscribe([settings.kafka_topic_options, settings.kafka_topic_quotes])

    try:
        while not stop.is_set():
            message = kafka.poll(timeout=1.0)
            if message is None:
                continue
            error = message.error()
            if error is not None:
                if error.code() == KafkaError._PARTITION_EOF:
                    continue
                print(f"volpulse-analytics: broker error: {error}", file=sys.stderr)
                continue

            payload = message.value()
            if payload is None:
                continue
            consumer.process(payload)
            kafka.commit(message=message, asynchronous=False)
    finally:
        kafka.close()


if __name__ == "__main__":
    raise SystemExit(main())
