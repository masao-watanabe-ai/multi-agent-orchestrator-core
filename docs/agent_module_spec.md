# Agent Module Specification (v0.1)

---

## 1. Purpose

This specification defines the minimal implementation requirements for an **Agent Module** operating on top of the **Multi-Agent Orchestrator Core**.

An Agent Module defines the role, input/output, and execution behavior of individual agents, and is assumed to be invoked via `action` nodes from the Orchestrator Core.

Agents in this specification do **not perform final decisions**.

Instead, Agents are responsible for:

- Information extraction  
- Evaluation  
- Hypothesis generation  
- Candidate generation  
- Context organization  
- Risk analysis  
- Recommendation generation  

Final branching, stopping conditions, and escalation to humans are controlled by the **Orchestrator Core** via `decision`, `boundary`, and `human_gate`.

---

## 2. Design Principles

### 2.1 Core Principle

> Agents execute AI tasks.  
> The Orchestrator Core executes decision flows.

Responsibilities are clearly separated:

### Agent Module
- Defines inputs  
- Defines outputs  
- Defines execution worker  
- Defines local constraints  

### Orchestrator Core
- Controls execution order  
- Defines branching conditions  
- Defines stopping conditions  
- Defines human escalation  
- Manages trace/state  

---

### 2.2 Separation of Signal and Decision

Agent outputs are **Signals**, not **Decisions**.

Examples of Agent outputs:

- risk_score  
- compliance_flags  
- retrieved_context  
- candidate_actions  
- recommendation  
- explanation  
- confidence  

Examples handled by Core:

- approve / reject  
- escalate to human  
- continue / stop  
- invoke next branch  

---

### 2.3 Structured Output Principle

All Agents should return **structured data** whenever possible.

Agents returning only free text are **not recommended** in v0.1.

---

## 3. Scope

### Included (v0.1)

- Agent definition  
- Agent registry  
- Input/output schema  
- Worker binding  
- Execution policy  
- Trace metadata  
- Result validation  

### Excluded (v0.1)

- Autonomous workflow generation  
- Agent-to-agent direct calls  
- Persistent storage updates  
- Final decision execution in agents  
- Dynamic graph rewriting  
- Learning/optimization  

---

## 4. Responsibilities of Agent Module

Each Agent Module must provide:

1. Agent identity  
2. Input specification  
3. Output specification  
4. Worker assignment  
5. Execution policy  
6. Trace metadata  
7. Registry registration  

---

## 5. Basic Structure

### 5.1 AgentSpec

```python
class AgentSpec:
    name: str
    version: str
    description: str
    category: str
    worker: str
    input_schema: dict
    output_schema: dict
    policy: dict
    trace: dict
```

### 5.2 Fields

name: Unique identifier
version: Spec version
description: Role description
category: Agent type
worker: Execution worker
input_schema: Input definition
output_schema: Output definition
policy: Local constraints
trace: Logging config

---

## 6. Agent Interface

```
class Agent:
    def invoke(self, payload: dict) -> dict:
        ...
```
Contract
Input: structured payload
Output: structured result

---

## 7. Input Schema

Principle
Agents must receive only required data.
Example
```
input_schema = {
    "type": "object",
    "properties": {
        "facts": {"type": "object"},
        "history": {"type": "array"},
        "policy": {"type": "object"}
    },
    "required": ["facts"]
}
```

---

## 8. Output Schema

Principle
Outputs must be reusable Signals.
Example
```
output_schema = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "label": {"type": "string"},
        "reasons": {"type": "array"},
        "confidence": {"type": "number"}
    },
    "required": ["score", "label"]
}
```

---

## 9. Worker Binding

Supported Workers
llm_worker
python_worker
rule_worker
api_worker

---

## 10. Execution Policy

```
policy = {
    "must_return_json": True,
    "min_confidence": 0.5,
    "allow_free_text": False,
    "escalate_on_invalid_output": True
}
```

---

## 11. Trace Metadata

```
trace = {
    "trace_name": "risk_agent_execution",
    "log_input": True,
    "log_output": True,
    "redact_fields": ["personal_info"]
}
```

---

## 12. Agent Registry

```
AGENT_REGISTRY = {
    "risk_agent": AgentSpec(...),
    "context_agent": AgentSpec(...)
}
```

---

## 13. Orchestrator Integration

Execution Flow
Resolve AgentSpec
Build payload
Validate input
Dispatch to worker
Receive result
Validate output
Store in context
Record trace
Proceed
Responsibility Boundary
Agents must NOT:
Control workflow
Stop execution
Trigger human review
Modify persistent state
Call other agents

---

## 14. Validation

Input
Must pass schema validation
Output
Must match output_schema
Failure handling:
node failure
invalid output
boundary routing
human escalation

---

## 15. Agent Categories

extractor
evaluator
generator
summarizer
reviewer
aggregator

---

## 16. Example

```
risk_agent = AgentSpec(
    name="risk_agent",
    version="v0.1",
    description="Performs risk evaluation",
    category="evaluator",
    worker="llm_worker",
    ...
)
```

---

## 17. Implementation Order

AgentSpec
Registry
Schema validation
Agent resolution
Worker binding
Output validation
Trace handling

---

## 18. Non-goals

Autonomous workflow control
Agent negotiation
Memory optimization
Auto prompt tuning
Dynamic roles

---

## 19. Success Criteria

Agents registered
Agents resolvable
Inputs validated
Execution successful
Outputs validated
Context updated
Trace recorded

---

## 20. Design Principles (Recap)

Agents generate/evaluate candidates
Core controls decision flow
Outputs are Signals, not Decisions
