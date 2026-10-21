# Artifactory

**Status:** opt-in. The dependency proxy is behind the `artifactory` compose
profile because it is a heavy service, and because most of the pipeline can
be built without it.

```bash
docker compose --profile artifactory up -d
```

| Port | Purpose |
| --- | --- |
| 8081 | The repository manager's web UI and API. |
| 8046 | The nginx reverse proxy in front of it. |

## Why it exists

The brief lists Artifactory as the dependency proxy for the Python packages
and the internal artefacts. In practice it does two jobs:

1. **A caching proxy for PyPI.** CI resolves dependencies through
   Artifactory rather than the internet, so a build is reproducible and does
   not depend on the availability of the public index.
2. **A home for the internal artefacts.** The generated protobuf stubs and
   the binary audit log format documentation are published here, so that
   another team can consume the contract without cloning this repository.

## Configuration

| Setting | Value |
| --- | --- |
| Admin password | `ARTIFACTORY_ADMIN_PASSWORD` (default `volpulse`) |
| PyPI remote repository | `api/pypi/pypi` |
| Reader credentials | `ARTIFACTORY_READER_USER` / `ARTIFACTORY_READER_PASSWORD` |

The reader credentials go into `~/.config/pip/pip.conf`:

```ini
[global]
index-url = http://localhost:8081/artifactory/api/pypi/pypi/simple
extra-index-url = http://localhost:8081/artifactory/api/pypi/pypi/simple
```

## Rules

* The local stack is unauthenticated for reads and uses a placeholder admin
  password. That is acceptable on a laptop and nowhere else.
* Nothing in this repository reads from Artifactory at runtime. It is a
  build-time dependency proxy, not a runtime dependency.
