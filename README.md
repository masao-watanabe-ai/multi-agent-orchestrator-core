# multi-agent-orchestrator-core
DSL-driven decision orchestration engine with traceable execution, human-in-the-loop, and boundary control.
## Why this exists

Most AI systems produce signals — predictions, scores, or recommendations.

But real-world systems require decisions:

- Approve or reject
- Escalate to human
- Retry or stop
- Apply policies and boundaries

This project separates **Signal** from **Decision**.

It provides a minimal core to explicitly model and execute decisions as structured, traceable processes.
