# ─────────────────────────────────────────────────────────────────────────────
# Kafka client for VolPulse.
#
# Provides a producer (ingestion → broker) and consumer (broker → analytics)
# wrapped around confluent-kafka. All messages use the protobuf contracts in
# contracts/volpulse/options/v1/.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

import confluent_kafka

from volpulse_core.models.quote import OptionQuote, OptionRight, QuoteSource

logger = logging.getLogger(__name__)

__all__ = [
    "KafkaConfig",
    "KafkaConsumer",
    "KafkaProducer",
    "consume_quotes",
    "produce_quotes",
]


def _right_to_proto(right: OptionRight) -> int:
    """Map our OptionRight enum to protobuf enum value."""
    return {OptionRight.CALL: 1, OptionRight.PUT: 2}[right]


def _right_from_proto(value: int) -> OptionRight:
    """Map protobuf enum value to our OptionRight."""
    return {1: OptionRight.CALL, 2: OptionRight.PUT}[value]


def _source_to_proto(source: QuoteSource) -> int:
    """Map our QuoteSource enum to protobuf enum value."""
    return {
        QuoteSource.REALTIME_FEED: 1,
        QuoteSource.REST_POLL: 2,
        QuoteSource.HISTORICAL_BACKFILL: 3,
    }[source]


def _source_from_proto(value: int) -> QuoteSource:
    """Map protobuf enum value to our QuoteSource."""
    return {
        1: QuoteSource.REALTIME_FEED,
        2: QuoteSource.REST_POLL,
        3: QuoteSource.HISTORICAL_BACKFILL,
    }[value]


@dataclass(frozen=True, slots=True)
class KafkaConfig:
    """Configuration for Kafka client connections."""

    bootstrap_servers: str = "localhost:9092"
    client_id: str = "volpulse"
    security_protocol: str = "PLAINTEXT"
    extra: dict[str, Any] = field(default_factory=dict)

    def producer_config(self, **overrides: Any) -> dict[str, Any]:
        config: dict[str, Any] = {
            "bootstrap.servers": self.bootstrap_servers,
            "client.id": f"{self.client_id}-producer",
            "security.protocol": self.security_protocol,
            "message.timeout.ms": 30000,
            "retries": 3,
            "retry.backoff.ms": 500,
            "queue.buffering.max.messages": 100000,
            **self.extra,
            **overrides,
        }
        return config

    def consumer_config(self, group_id: str, **overrides: Any) -> dict[str, Any]:
        config: dict[str, Any] = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": group_id,
            "client.id": f"{self.client_id}-consumer-{group_id}",
            "security.protocol": self.security_protocol,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "enable.partition.eof": True,
            "session.timeout.ms": 45000,
            "heartbeat.interval.ms": 3000,
            **self.extra,
            **overrides,
        }
        return config


class KafkaProducer:
    """Kafka producer for publishing OptionQuote messages.

    Wraps confluent_kafka.Producer. Messages are serialised as protobuf
    ChainRecord envelopes and published to the options chain topic,
    keyed by underlying symbol so all quotes for one symbol land on the same
    partition (preserving per-symbol ordering).
    """

    __slots__ = ("_delivered", "_failed", "_producer", "config", "topic")

    def __init__(
        self,
        config: KafkaConfig | None = None,
        topic: str = "options.chain.streaming",
    ) -> None:
        self.config = config or KafkaConfig()
        self.topic = topic
        self._producer = confluent_kafka.Producer(self.config.producer_config())
        self._delivered = 0
        self._failed = 0

    def produce(
        self,
        quotes: list[OptionQuote],
        key: str | None = None,
        on_delivery: Callable[[confluent_kafka.KafkaError | None, confluent_kafka.Message | None], None] | None = None,
    ) -> int:
        """Publish a batch of quotes to Kafka.

        Args:
            quotes: List of OptionQuote messages to serialise and publish.
            key: Optional Kafka message key (defaults to underlying symbol of
                first quote).
            on_delivery: Optional delivery report callback.

        Returns:
            Number of messages successfully queued for delivery.
        """
        if not quotes:
            return 0

        from google.protobuf import timestamp_pb2

        from volpulse.options.v1 import quote_pb2, streaming_pb2

        chain = quote_pb2.OptionChainSnapshot(
            underlying_symbol=quotes[0].underlying_symbol,
            sequence=quotes[0].sequence,
        )
        for q in quotes:
            # Convert nanoseconds to protobuf Timestamp
            event_ts = timestamp_pb2.Timestamp()
            event_ts.FromNanoseconds(q.event_time_ns)

            ingest_ts = timestamp_pb2.Timestamp()
            ingest_ts.FromNanoseconds(q.ingest_time_ns)

            chain.quotes.add(
                contract_id=q.contract_id,
                underlying_symbol=q.underlying_symbol,
                strike=q.strike,
                right=_right_to_proto(q.right),
                bid=q.bid,
                ask=q.ask,
                last=q.last,
                close=q.close,
                implied_volatility=q.implied_volatility,
                event_time=event_ts,
                ingest_time=ingest_ts,
                sequence=int(q.sequence),
                source=_source_to_proto(q.source),
            )

        envelope = streaming_pb2.ChainRecord(
            schema_version=1,
            partition_key=key or quotes[0].underlying_symbol,
            producer_id="volpulse-ingestion",
            producer_epoch=1,
            chain=chain,
        )

        payload = envelope.SerializeToString()
        key_bytes = key.encode("utf-8") if key else quotes[0].underlying_symbol.encode("utf-8")

        def _delivery_report(
            err: confluent_kafka.KafkaError | None,
            msg: confluent_kafka.Message | None,
        ) -> None:
            if err is not None:
                self._failed += 1
                logger.error("Kafka delivery failed: %s", err)
            else:
                self._delivered += 1
                if on_delivery is not None:
                    on_delivery(err, msg)

        self._producer.produce(
            topic=self.topic,
            key=key_bytes,
            value=payload,
            callback=cast(
                Callable[[confluent_kafka.KafkaError | None, confluent_kafka.Message | None], None],
                _delivery_report,
            ),
        )
        self._producer.poll(0)
        return len(quotes)

    def flush(self, timeout: float = 5.0) -> int:
        """Flush pending messages.

        Returns the number of messages still in the queue after timeout.
        """
        return self._producer.flush(timeout)

    def close(self) -> None:
        self.flush()
        self._producer = None  # type: ignore[assignment]


class KafkaConsumer:
    """Kafka consumer for reading OptionQuote messages.

    Wraps confluent_kafka.Consumer. Deserialises protobuf envelopes and
    yields OptionQuote objects.
    """

    __slots__ = ("_closed", "_consumer", "config", "group_id", "topics")

    def __init__(
        self,
        config: KafkaConfig | None = None,
        topics: list[str] | None = None,
        group_id: str = "volpulse-analytics",
    ) -> None:
        self.config = config or KafkaConfig()
        self.topics = topics or ["options.chain.streaming"]
        self.group_id = group_id
        self._consumer = confluent_kafka.Consumer(self.config.consumer_config(group_id))
        self._consumer.subscribe(self.topics)
        self._closed = False

    def poll(self, timeout: float = 1.0) -> list[OptionQuote]:
        """Poll for messages.

        Returns a list of decoded OptionQuote objects. Empty list if no
        messages available within timeout.
        """
        if self._closed:
            return []

        msg = self._consumer.poll(timeout)
        if msg is None:
            return []
        error = msg.error()
        if error is not None:
            if error.code() == confluent_kafka.KafkaError._PARTITION_EOF:
                return []
            logger.error("Kafka consumer error: %s", error)
            return []

        from volpulse.options.v1 import quote_pb2, streaming_pb2  # noqa: F401

        payload = msg.value()
        if payload is None:
            return []

        envelope = streaming_pb2.ChainRecord()
        envelope.ParseFromString(payload)

        quotes: list[OptionQuote] = []
        if envelope.WhichOneof("payload") == "chain":
            chain = envelope.chain
            for q in chain.quotes:
                # Convert protobuf Timestamp to nanoseconds
                event_time_ns = q.event_time.ToNanoseconds() if q.HasField("event_time") else 0
                ingest_time_ns = q.ingest_time.ToNanoseconds() if q.HasField("ingest_time") else 0
                
                quotes.append(
                    OptionQuote(
                        contract_id=q.contract_id,
                        underlying_symbol=q.underlying_symbol,
                        expiry_epoch_day=0,  # Not available in OptionQuote proto
                        strike=q.strike,
                        right=_right_from_proto(q.right),
                        bid=q.bid,
                        ask=q.ask,
                        last=q.last,
                        close=q.close,
                        implied_volatility=q.implied_volatility,
                        event_time_ns=event_time_ns,
                        ingest_time_ns=ingest_time_ns,
                        sequence=int(q.sequence),
                        source=_source_from_proto(q.source),
                    )
                )
        return quotes

    def close(self) -> None:
        self._closed = True
        self._consumer.close()

    def commit(self) -> None:
        """Commit the offset of the last polled message."""
        self._consumer.commit()


def produce_quotes(
    config: KafkaConfig,
    quotes: list[OptionQuote],
    topic: str = "options.chain.streaming",
    key: str | None = None,
) -> int:
    """Convenience: produce quotes and flush."""
    producer = KafkaProducer(config, topic=topic)
    try:
        count = producer.produce(quotes, key=key)
        producer.flush()
        return count
    finally:
        producer.close()


def consume_quotes(
    config: KafkaConfig,
    topics: list[str] | None = None,
    group_id: str = "volpulse-analytics",
    max_messages: int | None = None,
    timeout: float = 1.0,
) -> list[OptionQuote]:
    """Convenience: consume messages and return them as a list."""
    consumer = KafkaConsumer(config, topics=topics, group_id=group_id)
    collected: list[OptionQuote] = []
    try:
        while True:
            batch = consumer.poll(timeout=timeout)
            collected.extend(batch)
            if max_messages is not None and len(collected) >= max_messages:
                break
            if not batch:
                break
    finally:
        consumer.close()
    return collected
