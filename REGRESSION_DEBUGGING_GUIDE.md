# Regression Debugging: A Systematic Investigation Process

## Part 1: The Methodology

**Regression Debugging** is the systematic process of identifying and resolving failures in previously working functionality after code changes. This approach is critical when new features break existing systems.

### Key Principles

#### 1. Symptom Recognition
Identify that functionality has degraded from a known good state. The symptom is not the root cause—it's the signal that something broke.

#### 2. Scope Isolation
Determine which recent changes are likely suspects. Not all modifications cause regressions; focus on changes that touched the affected code paths.

#### 3. Trace-Based Root Cause Analysis
Follow the execution flow through the entire stack, method by method. Don't assume where the failure is—verify each step:
- Does the function receive correct inputs?
- Does it produce expected outputs?
- Where does the chain break?

#### 4. Hypothesis-Driven Investigation
Form testable hypotheses before making fixes: "If the history format changed, would this method fail?" Then verify by examining code.

#### 5. Cascading Failure Pattern Recognition
One broken component often masks deeper issues. Fix the surface problem, retest, and look for the next failure. Repeat until fully resolved.

#### 6. Validation Before Moving Forward
After each fix, verify the change works AND doesn't create new problems. Don't batch fixes blindly—test incrementally.

### Why This Matters

- Prevents wild guessing that introduces new bugs
- Creates a documented trail of what broke and why
- Teaches the system architecture through investigation
- Builds confidence in the fix, not just luck

### Common Pitfalls

- Auto-fixing without understanding the problem
- Testing too late after multiple changes
- Assuming the obvious location is where it broke
- Accepting partial fixes without full investigation

This systematic approach transforms frustrating debugging into structured problem-solving.

---

## Part 2: The MasterProDev Example

### Scenario

User reports that knowledge base search stopped working after implementing a pending action state management feature.

### Symptom

```
User: "tell me more about masterprodev"
Agent: "I ran into a temporary hiccup while retrieving details..."
```

Previously, this returned accurate information from the knowledge base.

### Investigation Process

#### Step 1: Trace the Execution Flow

We mapped where the request flows:
```
/chat endpoint 
  → agent.process_message() 
  → _plan_actions() 
  → _execute_plan() 
  → KnowledgeSearchTool._arun() 
  → rag_service.search()
```

#### Step 2: Identify Recent Changes

The pending action system modified 5 files:
- `state.py`
- `agent_logic.py`
- `query_processor.py`
- `agent.py`
- `main.py`

Each touches the request pipeline.

#### Step 3: Layer-by-Layer Verification

| Component | Status | Finding |
|-----------|--------|---------|
| `/chat` endpoint | ✅ | Correctly routing requests |
| `process_message()` | ✅ | Detecting knowledge intent |
| `_plan_actions()` | ✅ | Deciding to use knowledge_search |
| `_execute_plan()` | ✅ | Calling the tool |
| `KnowledgeSearchTool` | ❌ | **First issue found**: History context is being passed empty to the planner |

#### Step 4: Root Cause - Data Format Mismatch

The new `state_manager` was storing conversation history with keys:
```python
{"user": "...", "assistant": "..."}
```

But `_format_history()` expected:
```python
{"role": "...", "content": "..."}
```

**Result:** Empty history context meant the planner couldn't understand conversation context properly.

**Fix #1:** Modified `_format_history()` to handle both formats (hybrid approach):
```python
def _format_history(self, conversation_history):
    if not conversation_history:
        return ""
    trimmed = conversation_history[-3:]
    return "\n".join(
        f"{msg.get('role') or 'user'}: {msg.get('content') or msg.get('assistant', '')}" 
        for msg in trimmed
    )
```

#### Step 5: Retest, Find Next Issue

After fixing history format, knowledge search still failed silently. Tracing deeper revealed the real culprit: `rag_service.search()` was hitting an `InferenceClient api_key` error when generating embeddings.

**Lesson Applied:**
The first fix appeared to solve the problem (conversation now had context), but the deeper issue—embedding generation failure—wasn't exposed until we tested end-to-end. This is why incremental testing at each layer matters.

### Outcome

By following the trace-based approach, we discovered the actual failure wasn't in our new code—it was in RAGService's dependency on InferenceClient, which was being called with incorrect parameters during embedding generation.

### Key Takeaways

1. **Don't assume the obvious location is where it broke** - The knowledge base search failed, but the problem was in state management
2. **Test incrementally, not in batches** - Each layer's output becomes the next layer's input; validating each step prevents compound failures
3. **Cascade problems require cascade investigation** - One broken component masks deeper issues
4. **Documentation during debugging is investigation gold** - Recording each step's status helps identify patterns
5. **Hypothesis-driven testing is faster than random fixes** - Form theories, verify them systematically

---

## Application to Your Project

This regression debugging methodology proved invaluable when:
- New feature (pending action state management) broke existing feature (knowledge search)
- Root cause was in an upstream dependency (state manager's history format)
- Multiple layers of abstraction made the failure non-obvious

Use this framework whenever:
- "Something that worked yesterday stopped working"
- Multiple files were recently modified
- The symptom and root cause seem disconnected
- You need to explain to stakeholders what broke and why

