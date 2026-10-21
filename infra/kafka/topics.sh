#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Create the VolPulse Kafka topics.
#
# Retention policy is part of the design, not an afterthought:
#   * the streaming topic keeps 7 days so a consumer can replay a week of
#     history after an incident,
#   * the dead letter topic keeps 30 days so a poison message can be
#     investigated long after it was quarantined.
#
# Usage: bash infra/kafka/topics.sh [bootstrap-server]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BOOTSTRAP="${1:-${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}}"
PARTITIONS="${KAFKA_TOPIC_PARTITIONS:-12}"
REPLICATION="${KAFKA_TOPIC_REPLICATION:-1}"

TOPIC_CHAIN="${KAFKA_TOPIC_OPTIONS:-options.chain.streaming}"
TOPIC_QUOTES="${KAFKA_TOPIC_QUOTES:-options.quotes.realtime}"
TOPIC_SURFACES="${KAFKA_TOPIC_SURFACES:-options.surfaces.recomputed}"
TOPIC_DLQ="${KAFKA_TOPIC_DLQ:-options.chain.deadletter}"

wait_for_broker() {
  echo "waiting for the broker at ${BOOTSTRAP} ..."
  for _ in $(seq 1 60); do
    if kafka-topics.sh --bootstrap-server "${BOOTSTRAP}" --list >/dev/null 2>&1; then
      echo "broker is up"
      return 0
    fi
    sleep 2
  done
  echo "broker did not become available" >&2
  return 1
}

create_topic() {
  local topic="$1"
  local retention="$2"
  local cleanup="$3"

  echo "creating ${topic} (partitions=${PARTITIONS}, replication=${REPLICATION})"
  kafka-topics.sh \
    --bootstrap-server "${BOOTSTRAP}" \
    --create \
    --if-not-exists \
    --topic "${topic}" \
    --partitions "${PARTITIONS}" \
    --replication-factor "${REPLICATION}" \
    --config "retention.ms=${retention}" \
    --config "cleanup.policy=${cleanup}" \
    --config "compression.type=lz4" \
    --config "min.insync.replicas=1"
}

wait_for_broker

# Seven days of history for replay.
create_topic "${TOPIC_CHAIN}" 604800000 delete
# One day: the realtime topic is a transport, not an archive.
create_topic "${TOPIC_QUOTES}" 86400000 delete
# Thirty days: recomputed surfaces are expensive to reproduce.
create_topic "${TOPIC_SURFACES}" 2592000000 delete
# Thirty days: quarantined messages must survive long enough to be triaged.
create_topic "${TOPIC_DLQ}" 2592000000 delete

echo "topics:"
kafka-topics.sh --bootstrap-server "${BOOTSTRAP}" --list | grep -E "^options\." || true
