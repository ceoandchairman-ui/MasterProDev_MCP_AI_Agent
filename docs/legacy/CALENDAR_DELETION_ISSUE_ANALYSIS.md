# Calendar Deletion Issue - Root Cause Analysis

## Problem Summary
When a user asks to delete a calendar appointment, the system **creates a NEW calendar event** instead of deleting the existing one.

**Screenshot Evidence:**
- User request: "can u delete that appointment" (referring to the January 24, 2026 appointment)
- System response: Creates a new event with `TOOL: create_calendar_event | PARAMS: {"title": "Meeting", "start_time": "2025-12-14T14:00:00", "end_time": "2025-12-14T15:00:00"}`

---

## Root Causes Identified

### 1. **Incomplete Multi-Tool Workflow Implementation**
The planner prompt (lines 103-116 in `prompts.yaml`) clearly defines a **two-step deletion process**:

```
DELETION WORKFLOW FOR OLD APPOINTMENTS (IMPORTANT):
- Step 1: Call get_calendar_events with days_back=365 to fetch past events
- Step 2: Identify which old event matches user's description
- Step 3: Extract the event_id from results
- Step 4: Call delete_calendar_event with correct event_id
```

**Problem:** The LLM planner is likely **not executing this two-step workflow correctly**. Instead of:
1. First calling `get_calendar_events` to find the event
2. Then calling `delete_calendar_event` with the event_id

The agent is:
- Calling `create_calendar_event` (wrong tool)
- Not using the event_id from the retrieved events

### 2. **Ambiguous Event Reference Without Context**
When user says "can u delete that appointment":
- The system doesn't have the event_id
- The system needs to first retrieve events to identify which appointment the user is referring to
- **Current behavior:** Agent assumes `create_calendar_event` instead of `get_calendar_events` first

### 3. **Intent Router Limitations**
The `intent_router.py` only has 3 intent categories:
- `KNOWLEDGE_BASE_QUERY`
- `DATABASE_QUERY`
- `GREETING_OR_CONVERSATION`
- `UNSUPPORTED`

**Missing:** Specific routing for different **types of calendar operations** (get, create, delete).

### 4. **Weak Tool Description**
The `delete_calendar_event` tool description in `mcp_tools.py` (line 122-124):
```python
description: str = """Delete a calendar event by ID.
Use this when user wants to cancel or remove a meeting/appointment.
Examples: 'Cancel my 2pm meeting', 'Delete tomorrow's appointment'"""
```

**Issue:** Doesn't clearly state that the tool **requires an event_id** that must be obtained from `get_calendar_events` first.

### 5. **Potential LLM Reasoning Issue**
The planner uses `temperature=0.0` (line 382 in `agent.py`), which should ensure deterministic tool selection. However:
- The LLM might be misinterpreting "delete that appointment" as implicitly creating placeholder data
- Or the two-step workflow isn't being triggered because semantic routing flags aren't detected correctly

---

## Detection Signals

### What Happened:
1. User request: "can u delete that appointment" 
   - Keywords: "delete", "appointment" → should trigger `has_calendar_intent = True`
   
2. Semantic routing should detect:
   - `has_calendar_intent = True` (because of "delete", "appointment")
   - Should pass `calendar_intent=True` to planner

3. **Expected planner behavior:**
   - Recognize "delete" as delete intent
   - Select: `get_calendar_events` (with days_back to find old event)
   - Extract event_id from results
   - Select: `delete_calendar_event` with that event_id

4. **Actual behavior:**
   - Selected: `create_calendar_event` (WRONG tool)
   - Reason: Unknown - either intent detection failed OR planner reasoning failed

---

## File Analysis

### 1. **`mcp_host/agent.py` (Semantic Routing)**
- ✅ Has "delete" in `calendar_keywords` (line 341)
- ❌ But this routing might not be preventing `create_calendar_event` from being selected
- ❌ No validation that delete operations actually get event_id before execution

### 2. **`prompts.yaml` (Planner Prompt)**
- ✅ Clear examples of delete workflow (Examples 3 & 4)
- ✅ Explicit instruction for two-step process
- ❌ But LLM isn't following it - unclear why

### 3. **`mcp_host/mcp_tools.py`**
- ✅ `delete_calendar_event` tool exists and is registered (line 351)
- ✅ Tool expects `event_id` parameter
- ❌ No validation that event_id is valid before deletion
- ❌ Tool descriptions don't explain the workflow dependency

### 4. **`mcp_servers/calendar_server/main.py`**
- ✅ `_delete_event()` method exists (line 362)
- ✅ Correctly calls Google Calendar API delete
- ❌ No validation of event_id existence before deletion attempt

---

## Recommended Fixes (in priority order)

### CRITICAL (Do First)

#### Fix 1: Enhance Planner Validation
Add validation in `agent.py` `_validate_plan()` method to catch delete operations without preceding get_calendar_events:

```python
# Line 485+ in agent.py
# After action validation, add:

if any(action.get("tool") == "delete_calendar_event" for action in actions):
    # Check that a preceding get_calendar_events action exists
    has_get_events = any(
        action.get("tool") == "get_calendar_events" 
        for action in actions[:actions.index(next(a for a in actions if a.get("tool") == "delete_calendar_event"))]
    )
    if not has_get_events:
        logger.error("❌ Delete calendar event requires event_id - must fetch events first")
        # Force a two-step workflow
        return {
            "actions": [
                {"tool": "get_calendar_events", "arguments": {"days": 30, "days_back": 90}},
                {"tool": "delete_calendar_event", "arguments": {"event_id": "[REQUIRES_ID_FROM_ABOVE]"}}
            ],
            "final_response": None
        }
```

#### Fix 2: Improve Tool Descriptions
Update `mcp_tools.py` to make dependencies explicit:

```python
# Line 122-124 in mcp_tools.py
description: str = """Delete a calendar event by ID. 
IMPORTANT: Requires event_id parameter.
First call get_calendar_events to retrieve the event_id, then call this tool.
Use when user wants to cancel/remove meetings: 'Cancel my 2pm meeting', 'Delete that appointment'"""
```

#### Fix 3: Strengthen Calendar Intent Detection
Add more specific calendar deletion keywords to `agent.py`:

```python
# Line 340 in agent.py
calendar_keywords = ['schedule', 'meeting', 'calendar', 'event', 'appointment', 'book',
                    'conference', 'call', 'check my', "what's my", 'when am i', 
                    'cancel', 'delete', 'reschedule', 'move the', 'time slot',
                    'remove event', 'drop meeting', 'unscheduled', 'no longer need']
```

### HIGH PRIORITY (Do Next)

#### Fix 4: Add Event Lookup Logic
Create a helper function to identify events from user descriptions before deletion:

```python
# New method in agent.py
async def _identify_event_from_description(
    self, 
    description: str, 
    calendar_events: List[Dict[str, Any]]
) -> Optional[str]:
    """
    Use LLM to match user's event description (e.g., "that January 24 meeting")
    to an actual event from calendar_events list.
    Returns the matching event_id or None.
    """
    # Use LLM to fuzzy-match user description to calendar events
    pass
```

#### Fix 5: Implement Input Validation
Add pre-execution validation in `_execute_plan()` to catch delete operations with missing event_id:

```python
# In agent.py _execute_plan() method
for action in actions:
    if action.get("tool") == "delete_calendar_event":
        event_id = action.get("arguments", {}).get("event_id")
        if not event_id or event_id == "[REQUIRES_ID_FROM_ABOVE]":
            logger.error("❌ Cannot delete: event_id not provided")
            # Fetch calendar and prompt user to specify which event
            pass
```

### MEDIUM PRIORITY (Nice to Have)

#### Fix 6: Add Test Cases for Delete Workflow
Create comprehensive test cases:

```python
# tests/unit/test_calendar_delete.py
async def test_delete_recent_appointment():
    """User deletes an upcoming appointment"""
    
async def test_delete_past_appointment():
    """User deletes an old appointment from last month"""
    
async def test_delete_without_event_id():
    """User tries to delete without specifying which event"""
    
async def test_delete_nonexistent_event():
    """User tries to delete an event that doesn't exist"""
```

#### Fix 7: Improve Error Handling
Add specific error messages in `calendar_server/main.py`:

```python
# Line 362+ in calendar_server/main.py
async def _delete_event(self, params: Dict[str, Any]) -> Dict[str, Any]:
    """Delete event"""
    event_id = params.get("event_id")
    
    if not event_id:
        return {
            "status": "error",
            "error": "event_id is required to delete an event",
            "suggestion": "First call get_calendar_events to find the event_id"
        }
    
    # ... rest of deletion logic
```

---

## Workflow Comparison

### Expected (Correct) Workflow
```
User: "can u delete that appointment"
    ↓
Agent: "I need to find that appointment first"
    ↓
Agent calls: get_calendar_events(days=7, days_back=30)
    ↓
Server returns: [Event1, Event2, Event3, ...January 24 appointment...]
    ↓
Agent identifies: "that appointment" = January 24 event with ID "xyz123"
    ↓
Agent calls: delete_calendar_event(event_id="xyz123")
    ↓
Server deletes event
    ↓
User: "Done! I've deleted your January 24 appointment"
```

### Actual (Broken) Workflow
```
User: "can u delete that appointment"
    ↓
Agent: ??? (something wrong here)
    ↓
Agent calls: create_calendar_event(title="Meeting", start="2025-12-14T14:00:00", ...)
    ↓
Server creates new event (WRONG!)
    ↓
User: "Why is there a new event instead of deleting mine?"
```

---

## Testing & Validation

After implementing fixes, test with:

1. **Delete recent event:** "Delete my 11 AM meeting on January 24"
2. **Delete past event:** "Remove the meeting from last month"
3. **Delete without event_id:** "Can u delete that appointment" (should prompt for clarification)
4. **Cancel instead of delete:** "Cancel tomorrow's meeting"
5. **Reschedule instead of delete:** "Move my Monday meeting to Tuesday"

---

## Summary Table

| Issue | Severity | Root Cause | Fix |
|-------|----------|-----------|-----|
| Wrong tool selected (create vs delete) | CRITICAL | LLM planner reasoning failure | Validate plan, enhance tool descriptions |
| Missing event_id | CRITICAL | Two-step workflow not executed | Force get_calendar_events before delete |
| Weak intent detection | HIGH | Limited calendar keywords | Add more delete-specific keywords |
| No event matching logic | HIGH | User says "that appointment" but no ID | Implement LLM-based event matching |
| Missing validation | MEDIUM | No pre-execution checks | Add input validation in _execute_plan |
| No test coverage | MEDIUM | Undetected regression risk | Add comprehensive test suite |

---

## Next Steps

1. **Immediate:** Implement Fix 1 (Planner Validation) - prevents new events being created on delete
2. **Short term:** Implement Fixes 2-3 (Tool descriptions and intent detection)
3. **Medium term:** Implement Fixes 4-5 (Event lookup and input validation)
4. **Long term:** Implement Fixes 6-7 (Tests and better error handling)
