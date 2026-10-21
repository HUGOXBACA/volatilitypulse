# Upstream HTTP client

**Status:** specified, not implemented.

The ingestion engine is the only component allowed to call the upstream
provider. This directory will hold that client.

## Responsibility

* Perform the REST and WebSocket calls against the IVolatility API.
* **Own the pacing.** Every call goes through a limiter configured at the
  subscription rate (roughly one request per second). No other component
  may bypass it, because the quota is shared.
* Handle the asynchronous job flow: a wide query returns a job, the details
  URL is polled until the download URL is published, and the result is
  walked page by page.
* Rewrite the `from` parameter, which is a Python keyword in the tooling
  and a reserved word in some clients.
* Translate provider failures into the platform's error taxonomy: timeout,
  authorisation, rate limit, transport, schema.

## Interface

The client implements the ingestion service's `QuoteSource` interface:

```cpp
class QuoteSource {
 public:
  virtual std::vector<Quote> fetch(std::size_t max_quotes) = 0;
  virtual bool exhausted() const = 0;
  virtual std::string describe() const = 0;
};
```

The pipeline must not know that the source is HTTP. That is what allows the
replay source and the tests to exist.

## Dependencies

`curl` for the transport, `nlohmann/json` for the payload, `openssl` for TLS.
All three are declared in `vcpkg.json`.

## Rules

* Every call has an explicit timeout. A hung upstream must not hang the
  engine.
* Failures are retried with backoff and jitter, and the retry count is
  bounded. The engine must not spin.
* The response is validated before it is normalised. A structurally
  impossible payload is dropped with a counter, not propagated.
* The API key is read from the environment and is never logged, never
  included in an error message and never written to the audit log.
