# ─────────────────────────────────────────────────────────────────────────────
# Images.
#
# The two service images are built from the same repository as the local
# infrastructure, so a container and a laptop run the same code.
#
#   docker build -f infra/docker/Dockerfile.ingestion -t volpulse/ingestion .
#   docker build -f infra/docker/Dockerfile.analytics  -t volpulse/analytics .
#
# The local infrastructure stack (Kafka, TimescaleDB, Prometheus, ...) is
# defined in the compose file at the repository root; these files build the
# services that run against it.
# ─────────────────────────────────────────────────────────────────────────────
