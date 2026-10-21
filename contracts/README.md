# Contracts

Every message that crosses a service boundary is defined here, and only
here. Both the C++ and the Python implementations generate their stubs from
these files, so the two sides cannot drift.

```
contracts/volpulse/
├── common/v1/common.proto         Shared vocabulary: enums, instruments, money.
└── options/v1/
    ├── quote.proto                The normalised quote, the surface, the risk.
    └── streaming.proto            Kafka envelopes and the gRPC control plane.
```

## Rules

1. **Field numbers are frozen.** A retired field number is reserved, never
   reused. Renaming a field is fine; changing its number is a breaking
   change.
2. **New fields are always optional.** An old consumer must be able to read
   a new message. Protobuf handles this, but only if you never make an
   existing field required.
3. **The hot path stays flat.** The normalised quote is written to disk and
   put on the wire without transformation. Do not add a field that only the
   consumer can compute — derive it there instead.
4. **One source of truth per concept.** If both sides need it, it is here.
   If only one side needs it, it belongs in that side's own code.

## The two channels

| Channel | Carries | Protocol |
| --- | --- | --- |
| **Data plane** | Normalised quotes, at line rate. | Kafka, `options.chain.streaming`. |
| **Control plane** | Administrative operations: backfill, health, recomputation. | gRPC, `IngestionControl`. |

Tick data never travels over the control plane, and control operations never
travel over the data plane. Keeping them apart means a slow administrative
call cannot stall the quote path.

## The normalised quote

`OptionQuote` is the atom of the pipeline. It is flat, fixed and cheap:

* prices are doubles in the quote currency;
* the expiry is an epoch day count, because an expiry is a date;
* timestamps are `google.protobuf.Timestamp` in UTC;
* `sequence` is monotonic per partition, for gap detection and
  de-duplication;
* `source` says how the quote was produced, so a backfilled quote is never
  mistaken for a live one.

The record carries `ingest_time` as well as `event_time`, so the pipeline
can measure latency honestly instead of reporting the age of the newest
arrival.

## Working with the contracts

```bash
make proto           # regenerate the stubs into .gen/
make proto-lint      # buf lint + format check
make proto-breaking  # compare against main
```

The generated code is gitignored and rebuilt by CI. It is never edited by
hand.

### Versioning

`ChainRecord.schema_version` is bumped on any breaking change to the
payload. The consumer checks it and quarantines a record it cannot read, so
a bad deploy cannot silently mis-parse the stream.
