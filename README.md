# Multi-Agent Orchestrator Core

A Python library for building deterministic, auditable AI agent workflows. Define
flows as directed node graphs; the engine executes them synchronously, suspending on
`action` and `human_gate` nodes until an external event arrives. `ExecutionInstance`
state can be persisted across process boundaries, and every execution step emits a
structured `TraceEvent`. v0.1 ships five node types; parallel fan-out and automatic
retries are planned for later releases.

---

## Supported Node Types

| Type | Behaviour | Suspends? |
|---|---|---|
| `decision` | Writes key-value pairs into the execution context and advances. | No |
| `condition` | Evaluates a boolean expression; branches to `true_next` or `false_next`. | No |
| `boundary` | Same evaluation logic as `condition`; marks a compliance or policy gate. | No |
| `action` | Dispatches a `Task` to an external worker and suspends the instance (`WAITING`). | Yes |
| `human_gate` | Suspends the instance pending a human approval decision. | Yes |

**Not yet executable:** `parallel` passes DSL validation but raises
`UnsupportedNodeTypeError` at runtime. All other planned node types
(`timeout`, `retry`, `sequence`, `selector`, `aggregate`, `wait_event`) are
not yet recognised by the validator or the engine — see
[Not Yet Implemented](#not-yet-implemented).

---

## Installation

```
git clone https://github.com/<owner>/multi-agent-orchestrator-core
cd multi-agent-orchestrator-core
pip install -e ".[dev]"   # installs pytest
```

Python 3.9 or later is required. CI-verified on CPython 3.9.

---

## Minimal Example

```python
from dsl.compiler import FlowDefinition, NodeDefinition
from runtime.engine import start
from runtime.models import NodeState

flow = FlowDefinition(
    flow_id="hello",
    start_node="greet",
    nodes_by_id={
        "greet": NodeDefinition(
            id="greet", type="decision",
            config={"set": {"message": "hello world"}},
        ),
    },
)

instance = start(flow, context={})
assert instance.status == NodeState.SUCCEEDED
print(instance.context["message"])   # hello world
```

---

## DSL Dict Approach

Instead of constructing objects directly, build flows from plain Python dicts and
compile them:

```python
from dsl.compiler import compile_dsl
from dsl.validator import validate

dsl = {
    "flow_id": "score_flow",
    "start_node": "evaluate",
    "nodes": [
        {"id": "evaluate",  "type": "decision",  "next": "grade",
         "set": {"score": 72}},
        {"id": "grade",     "type": "boundary",
         "true_next": "pass_node", "false_next": "fail_node",
         "expression": "score > 60"},
        {"id": "pass_node", "type": "decision",  "set": {"result": "PASS"}},
        {"id": "fail_node", "type": "decision",  "set": {"result": "FAIL"}},
    ],
}

validate(dsl)           # raises DSLValidationError on structural problems
flow = compile_dsl(dsl)
```

`validate` catches duplicate ids, unknown node types, and dangling transition
references before the flow ever runs.

---

## action -> WAITING -> resume

When the engine reaches an `action` node it:

1. Builds a `Task` and calls `dispatcher.dispatch(task)`.
2. Sets the instance status to `WAITING` and returns immediately.

Your application stores the suspended instance, delivers the task to a worker, then
calls `resume` once the worker reports a result:

```python
from execution.dispatcher import InMemoryDispatcher
from runtime.engine import start, resume
from runtime.models import NodeState
from runtime.resume import TaskCompletedEvent

dispatcher = InMemoryDispatcher()
instance = start(flow, context={"input": "data"}, dispatcher=dispatcher)
# instance.status == NodeState.WAITING

# ... worker processes dispatcher.tasks[0] ...

event = TaskCompletedEvent(
    instance_id=instance.instance_id,
    node_id="my_action",
    payload={"result": {"score": 0.9}},
)
instance = resume(flow, instance, event, dispatcher=dispatcher)
# instance.status == NodeState.SUCCEEDED
# instance.context["my_action"] == {"score": 0.9}
```

A `TaskFailedEvent` halts the instance with `status = FAILED`.

---

## human_gate

A `human_gate` node suspends the instance and waits for a human decision.

```python
from runtime.resume import HumanApprovedEvent, HumanRejectedEvent

# Approve -- execution continues to node.next
event = HumanApprovedEvent(
    instance_id=instance.instance_id,
    node_id="review_gate",
    approver="alice",
)
instance = resume(flow, instance, event)
# instance.context["review_gate"] == {"approved": True, "approver": "alice"}

# Reject -- instance halted with status = FAILED
event = HumanRejectedEvent(
    instance_id=instance.instance_id,
    node_id="review_gate",
    reason="budget exceeded",
    approver="alice",
)
instance = resume(flow, instance, event)
# instance.context["review_gate"] == {"approved": False, "reason": "...", "approver": "..."}
```

---

## boundary

`boundary` evaluates the same boolean expressions as `condition` but carries a distinct
semantic: it marks a compliance or risk decision point in the flow, not just a routing
choice. Use `boundary` where an expression determines whether the workflow must escalate
or proceed under a policy rule.

```python
NodeDefinition(
    id="amount_gate",
    type="boundary",
    true_next="manual_review",
    false_next="auto_approve",
    config={"expression": "amount > 1000"},
)
```

Supported expression operators: `>`, `<`, `==`, `!=`.
The right-hand side may be an integer, float, boolean (`true`/`false`), `null`,
a quoted string (`"premium"`), or an unquoted string (e.g. `active`).

---

## State Persistence

Two store implementations are provided. Both satisfy `StateStoreProtocol`.

```python
from state.store import InMemoryStateStore, JsonFileStateStore

# in-memory (tests / single-process)
store = InMemoryStateStore()
store.save_instance(instance)              # raises ValueError if already saved
instance = store.load_instance(instance_id)
store.update_instance(modified_instance)   # raises KeyError if not found

# file-backed (multi-process / restarts)
store = JsonFileStateStore("/tmp/workflow_state")
store.save_instance(instance)
instance = store.load_instance(instance_id)
store.update_instance(modified_instance)
```

`JsonFileStateStore` writes one `<instance_id>.json` file per instance.
Context and output values must be JSON-native types (`str`, `int`, `float`, `bool`,
`None`, `list`, `dict`).

Typical WAITING -> save -> load -> resume pattern:

```python
store = InMemoryStateStore()

instance = start(flow, context, dispatcher=dispatcher)
# instance.status == NodeState.WAITING
store.save_instance(instance)

# ... process restarts or time passes ...

instance = store.load_instance(instance.instance_id)
event = TaskCompletedEvent(
    instance_id=instance.instance_id,
    node_id="a1",
    payload={"result": 42},
)
result = resume(flow, instance, event, dispatcher=dispatcher)
store.update_instance(result)
```

---

## Trace

Pass an `emitter` to `start` or `resume` to receive structured trace events at every
major execution step.

```python
from trace.collector import InMemoryTraceCollector
from trace.ledger_adapter import to_ledger_record

collector = InMemoryTraceCollector()
instance = start(flow, context, emitter=collector)

for event in collector.list_events():
    print(event.event_type, event.node_id, event.payload)
```

### Event types emitted

| Event | Trigger |
|---|---|
| `flow.started` | `start()` called |
| `flow.succeeded` | All nodes completed |
| `flow.waiting` | Action or human_gate suspended the instance |
| `flow.failed` | Exception or failure event halted the instance |
| `flow.resumed` | `resume()` called |
| `node.started` | A node began executing |
| `node.succeeded` | A node completed successfully |
| `node.waiting` | Action / human_gate node suspended |
| `node.failed` | A node raised or received a failure event |
| `action.dispatched` | A task was dispatched (payload: `task_id`, `worker`) |
| `boundary.triggered` | A boundary node evaluated (payload: `next_id`) |
| `human_gate.approved` | `HumanApprovedEvent` processed |
| `human_gate.rejected` | `HumanRejectedEvent` processed |

`InMemoryTraceCollector` provides filtering helpers:

```python
collector.list_events(instance_id)       # all events for one instance
collector.by_type("boundary.triggered")  # filter by event type
collector.event_types()                  # ordered list of type strings
```

Convert any event to a plain dict for logging or audit trails:

```python
record = to_ledger_record(event)
# {"instance_id": ..., "node_id": ..., "event_type": ...,
#  "timestamp": "2025-01-01T00:00:00+00:00", "payload": {...}}
```

---

## Running Examples

Each example is a standalone script. Run from the **project root**:

```
python examples/simple_sync/run.py
python examples/async_action/run.py
python examples/human_review/run.py
python examples/boundary_escalation/run.py
```

No extra dependencies are required beyond the base install.

| Example | What it shows |
|---|---|
| `simple_sync` | Decision + boundary flow completing synchronously with trace output. |
| `async_action` | Action node dispatches a task; `TaskCompletedEvent` and `TaskFailedEvent` paths. |
| `human_review` | `human_gate` suspended for review; both approved and rejected paths shown. |
| `boundary_escalation` | Boundary routes large amounts to human_gate; state persisted with `JsonFileStateStore`. |

---

## Running Tests

```
pytest
```

With verbose output:

```
pytest -v
```

The test suite covers:

| File | Coverage |
|---|---|
| `tests/test_engine.py` | Core engine: start / resume / error cases |
| `tests/test_action.py` | Action node dispatch and Task construction |
| `tests/test_resume.py` | TaskCompleted / TaskFailed resume paths |
| `tests/test_human_gate.py` | HumanApproved / HumanRejected paths |
| `tests/test_boundary.py` | Boundary expression evaluation and routing |
| `tests/test_state_store.py` | Snapshot serialisation, InMemory/JsonFile stores, WAITING->resume integration |
| `tests/test_trace.py` | TraceEvent, emitter, collector, ledger adapter, per-scenario emission |

---

## Project Structure

```
multi-agent-orchestrator-core/
├── dsl/
│   ├── compiler.py          # DSL dict -> FlowDefinition / NodeDefinition
│   ├── validator.py         # structural validation, DSLValidationError
│   └── parser.py            # raw input normalisation (pre-validation)
├── runtime/
│   ├── models.py            # ExecutionInstance, NodeState, Task, ...
│   ├── engine.py            # start(), resume(), execution loop
│   ├── resume.py            # TaskCompletedEvent, HumanApprovedEvent, ...
│   └── decision_contract.py # expression evaluator (>, <, ==, !=)
├── nodes/
│   ├── decision/
│   │   ├── condition.py     # condition node runner
│   │   ├── decision.py      # decision node runner
│   │   ├── boundary.py      # boundary node runner
│   │   └── human_gate.py    # human_gate node runner (no-op; engine owns state)
│   ├── action/
│   │   └── action.py        # action node runner -> Task
│   └── control/             # placeholder stubs — not yet implemented
├── execution/
│   ├── dispatcher.py        # DispatcherProtocol, InMemoryDispatcher
│   ├── worker_interface.py  # WorkerInterface ABC
│   └── event_bus.py         # EventBusProtocol, InMemoryEventBus
├── sdk/
│   ├── agent_contract.py    # AgentContract dataclass
│   └── agent_registry.py    # agent registration / lookup
├── state/
│   ├── snapshot.py          # ExecutionInstance <-> plain dict (to_dict / from_dict)
│   ├── store.py             # StateStoreProtocol, InMemoryStateStore, JsonFileStateStore
│   └── event_store.py       # InMemoryEventStore (resume event log)
├── trace/
│   ├── model.py             # TraceEvent dataclass
│   ├── emitter.py           # TraceEmitterProtocol, TraceEmitter
│   ├── collector.py         # InMemoryTraceCollector
│   └── ledger_adapter.py    # to_ledger_record()
├── docs/                    # design specifications
├── examples/
│   ├── simple_sync/run.py
│   ├── async_action/run.py
│   ├── human_review/run.py
│   └── boundary_escalation/run.py
└── tests/
```

---

## Not Yet Implemented

### Passes validation, fails at runtime

`parallel` is listed in the DSL validator's allow-list. A flow containing it
passes `validate()` and `compile_dsl()`, but the engine raises
`UnsupportedNodeTypeError` when execution reaches the node.

### Not yet in the validator or engine

The following types exist as empty placeholder files under `nodes/control/`
but are not recognised by the validator and cannot be used in flows:

| Type | Planned behaviour |
|---|---|
| `parallel` (engine) | Fan-out execution across multiple branches simultaneously |
| `timeout` | Automatic failure after a wall-clock deadline |
| `retry` | Automatic re-dispatch of failed action nodes |
| `sequence` | Execute a fixed ordered list of child nodes |
| `selector` | Execute child nodes until one succeeds |
| `aggregate` | Collect results from parallel branches |
| `wait_event` | Suspend until an arbitrary named event arrives |

## License

MIT License © 2026 Masao Watanabe
