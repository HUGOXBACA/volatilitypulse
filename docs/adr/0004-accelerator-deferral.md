# ADR-0004: Defer CUDA and FPGA acceleration

* **Status:** Accepted
* **Date:** 2026-10-21
* **Deciders:** Platform owner

## Context

The brief proposes going "one step down the layer" from an institutional
architecture to an "ultra-low-latency" one with both **CUDA and FPGA**
design patterns, and describes the result as transforming the project into a
"world-class quantitative engineering masterpiece".

The pipeline as designed is:

```
upstream API (~1 request/second, metered)
  → C++ normalisation (microseconds per record)
  → binary audit log (memory mapped)
  → Kafka (milliseconds)
  → Python analytics (milliseconds to tens of milliseconds)
  → TimescaleDB (milliseconds)
```

The binding constraint is the **upstream quota**, not the computation. One
request per second, per symbol, is a rate limit agreed with a provider. No
amount of local compute changes it. A CUDA kernel that shaves 20 µs off a
step that costs 1 s of pacing is invisible in the end-to-end latency.

The hardware is also the wrong shape for the problem. The numerical work in
this pipeline — implied volatility inversion, surface fitting, Greeks over a
book — is branchy, memory-bound at the level of small arrays, and dominated
by library calls. GPUs are excellent at dense, large, regular arithmetic and
poor at exactly this shape of work. Moving the Black-Scholes solver to a
GPU would add a transfer cost that exceeds the computation it replaces.

FPGA is a different proposition: a fixed-pipeline implementation of a pricing
kernel can genuinely beat a CPU, and it is the right answer for a
latency-critical order book. But it is a hardware project with its own
toolchain, its own verification burden (you must prove the bit-exact
equivalence of two implementations) and its own failure modes.

## Decision

**Defer both.** Do not build CUDA or FPGA acceleration until a measurement
shows that the compute is on the critical path.

What is done instead:

* The numerical core is written to be *acceleratable* without being
  *accelerated*: vectorised NumPy over the whole book, no Python-level loop
  over positions, and a documented seam where a numba or JAX kernel could
  replace the vectorised implementation without changing the interfaces.
* The measurement infrastructure exists before it is needed. The end-to-end
  latency is measured from the upstream event timestamp to the analytics
  output, and the per-stage costs are exported as metrics — so the argument
  about where the time goes is settled by data rather than by opinion.
* The C++ path — where a hardware offload would actually belong, because
  that is where the per-record cost lives — is structured so that the
  normaliser and the log writer are independent of each other. A future
  hardware path can replace one without touching the other.

This decision is explicitly revisitable: it is not "never", it is "not
until the measurement says so".

## Consequences

### What becomes easier

* The system stays operable by one person. A CUDA toolchain or an FPGA
  vendor's suite is a second specialisation with its own learning curve, its
  own CI problems and its own class of bugs.
* The analytics code stays readable and testable. The property tests
  (put-call parity, implied volatility round trips) apply to the vectorised
  implementation directly.
* The critical path stays where it belongs: at the provider, and in the
  engineering of the upstream client (pacing, pagination, checkpointing) —
  all of which is ordinary, well-understood work.

### What becomes harder

* If the upstream ever becomes unthrottled, the pipeline will need
  re-profiling, and the first thing to look at will be the per-record cost
  in the C++ path. The instrumentation to do that is in place.
* The vectorised NumPy implementation is not the fastest possible
  implementation. When it becomes the constraint, a numba or JAX kernel is
  a contained change — but it will be a change.

### What is now forbidden

* Adding a GPU dependency before a measurement justifies it.
* Claiming a latency figure that was not measured end to end from the
  upstream event timestamp.

## Alternatives considered

### CUDA now, for the numerical kernels

Rejected. The kernels are small and memory-bound; the transfer and launch
overheads would exceed the compute saved, and the measurement does not
support the premise. If it is revisited, it will be with a benchmark in
hand — see the alternative below.

### An FPGA pricing kernel

Rejected as premature, and it is the most credible of the three: a fixed
pipeline really can beat a CPU for a pricing kernel, and it would fit the
"institutional" story. Against it: the verification burden of two
implementations of the same model, the hardware and toolchain commitment,
and the absence of any evidence that pricing latency is currently a
constraint. It is the right answer for a different system — a colocated
market-making engine — and the wrong answer for a pipeline whose input is
metered at one request per second.

### numba / JAX on the Python side (selected instead)

Accepted as the *first* acceleration step, when it is needed. It keeps the
implementation in one language, keeps the property tests applicable, and
targets the actual hot loop: the implied volatility solver over a book of
thousands of contracts, called on every snapshot.
