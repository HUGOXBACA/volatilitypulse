# Documentation index

Everything the team needs to operate, extend and review VolPulse.

| Section | What it covers | Read it when |
| --- | --- | --- |
| [Architecture](architecture/overview.md) | How the brief maps onto the code. | You are new, or you changed a boundary. |
| [Data flow](architecture/data-flow.md) | The life of a single quote. | You are debugging the pipeline. |
| [ADRs](adr/) | Why the system is the way it is. | You are about to change a decision. |
| [Runbooks](runbooks/) | What to do when it breaks. | You have been paged. |
| [Operations](operations/observability.md) | Metrics, alerts, dashboards. | You are adding instrumentation. |
| [Development](development/local-setup.md) | Getting a working environment. | You are setting up, or onboarding. |
| [Glossary](glossary.md) | The vocabulary of the desk. | You are new to options or to this codebase. |

## Principles

1. **Written decisions beat remembered ones.** If a decision has consequences
   that outlive the sprint, it gets an ADR.
2. **Every alert has a runbook.** A rule without instructions is a page
   without a plan.
3. **The diagram is the code.** Contracts and interfaces are the truth; the
   prose describes them.
4. **Boring is a feature.** The pipeline is deliberately boring: one broker,
   one schema registry, one time-series store, one relational store. Every
   extra moving part costs more than it earns until proven otherwise.
