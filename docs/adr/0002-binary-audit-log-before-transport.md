# ADR-0002: Build the binary audit log before the transport layer

* **Status:** Accepted
* **Date:** 2026-10-21
* **Deciders:** Platform owner

## Context

The brief describes a C++ engine that polls an upstream API, normalises the
payload, writes a zero-copy structured binary log, and publishes to a broker.
The natural build order is the opposite: get data flowing through the broker
first, then add the audit log.

That order is wrong here. The binary log is what makes the pipeline
*replayable*, and replayability is what makes every other part of the
system debuggable:

* when the analytics engine produces a wrong surface, the only way to
  reproduce it is to feed it the same input again;
* when a consumer crashes mid-batch, the input has to still exist somewhere;
* when a contract is changed, the old records have to remain readable by the
  old code to be comparable;
* the broker is a queue, not a history — its retention is a policy decision
  that may be shortened at any time.

Building the transport first means debugging a pipeline whose input has
already evaporated.

## Decision

Implement the **binary audit log first**, as a self-contained library with no
dependency on the broker, the analytics engine or the upstream API.

* The format is fixed width and endian explicit: a 32-byte header
  (magic, version, flags, payload size, sequence, timestamp, CRC-32)
  followed by the payload, padded to an 8-byte boundary.
* The writer memory-maps the file. Appending is a `memcpy`, not a syscall.
* Each record carries a CRC-32 over its payload. A reader stops at the first
  record that fails validation.
* A torn tail left by a crash is detected on the next open and truncated, so
  the log heals itself.
* Every record carries a monotonic sequence number, and the byte offset of
  every record is carried in the Kafka envelope, so any consumed record can
  be replayed from disk without touching the broker.

The log is an **audit trail**, not the system of record: records are ordered
and checksummed, but only made durable on an explicit flush. The broker and
the databases remain authoritative.

## Consequences

### What becomes easier

* Every later component can be developed and tested against a recorded
  input rather than against the upstream API.
* Quota is not spent on debugging. The upstream is metered at roughly one
  request per second; that is far too slow to iterate against.
* Incident recovery has a defined answer: replay from the audit log offset
  carried in the record that failed.
* The transport becomes replaceable. Kafka can be swapped without touching
  the ingestion logic, because the log already holds what was produced.

### What becomes harder

* The log format is a compatibility surface. It needs a version field, and
  a change to the layout is a breaking change that requires a migration
  path for existing files.
* Memory mapping means the writer must manage the window: growth, flushing
  and truncation to the logical size on close.
* The on-disk format is specific to this system, so it cannot be reused
  elsewhere. The protobuf contracts, by contrast, are reusable.

### What is now forbidden

* Changing the record layout without bumping `kFormatVersion` and providing
  a migration.
* Treating the log as the system of record, or reading state from it that
  is not also in a database.
* Silently accepting a record that fails its CRC. A damaged log is an
  incident, not a warning.

## Alternatives considered

### Build the transport first

Rejected. It is the conventional order and it produces a pipeline whose
input cannot be reproduced.

### Store the raw provider payload instead of the normalised quote

Rejected for the primary log. The normalised quote is what the system
actually consumed, and storing it means the log can be replayed without
depending on the upstream's parser staying unchanged. The raw payload is
retained alongside the normalised record in the protobuf envelope
(`RawProviderPayload`) for exactly the case where the normalisation itself
has to be re-examined.

### Use a text format (JSON lines)

Rejected. Text is convenient to read and expensive to write: at market rate
the encoding cost dominates, and the file does not compress as well. A
fixed-width binary record is cheaper to produce, cheaper to scan and
cheaper to seek.
