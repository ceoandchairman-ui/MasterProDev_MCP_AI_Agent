# DEPENDENCY ANALYSIS - PostgreSQL, Redis & External Services

## 🎯 OVERVIEW

Our MCP system has **CRITICAL DEPENDENCIES** on external services. This document maps which files interact with what.

---

## 📊 DEPENDENCY MAP

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  PostgreSQL ◄───────────────────────► Redis Cache               │
│  (Port 5432)                          (Port 6379)               │
│                                                                   │
│  Users          Sessions              Sessions (24hr TTL)        │
│  Conversations  Conversations         Conversations (1hr TTL)    │
│  Tool Logs      Permissions           Tool Logs                  │
│  API Usage      API Usage                                        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                    ┌─────────┴─────────┐
                    │                   │
            ┌──────────────┐    ┌──────────────┐
            │  mcp_host/   │    │ MCP Servers  │
            │  state.py    │    │ (Read only)  │
            └──────────────┘    └──────────────┘
                    │
        ┌───────────┼───────────┐
        │           │           │
    config.py   main.py      auth.py
```

---

## 🔗 FILE-BY-FILE DEPENDENCY BREAKDOWN

### **1. `mcp_host/config.py`** ⚙️
**Purpose:** Configuration management

**PostgreSQL Dependencies:**
```python
DATABASE_URL: str = "postgresql://mcpagent:mcpagent_dev_password@localhost:5432/mcpagent"
```
- Defines the connection string
- Used by: `state.py`, `main.py` (startup event)
- **Status:** ✅ Defined, not implemented yet

**Redis Dependencies:**
```python
REDIS_URL: str = "redis://:mcpagent_dev_password@localhost:6379/0"
REDIS_PASSWORD: str = "mcpagent_dev_password"
REDIS_HOST: str = "localhost"
REDIS_PORT: int = 6379
REDIS_DB: int = 0
```
- Defines Redis connection parameters
- Used by: `state.py`
- **Status:** ✅ Defined, not implemented yet

**External Service URLs:**
```python
CALENDAR_SERVER_URL: str = "http://localhost:8001"
GMAIL_SERVER_URL: str = "http://localhost:8002"
```
- Define MCP server URLs
- Used by: Future `adapter.py` implementation
- **Status:** ✅ Defined

---

### **2. `mcp_host/state.py`** 🗄️
**Purpose:** State management - Redis & PostgreSQL coordination

**CRITICAL: This file needs implementation!**

```python
class StateManager:
    def __init__(self):
        self.redis = None           # ❌ Not initialized
        self.db_connection = None   # ❌ Not initialized

    async def initialize(self):
        """Initialize connections"""
        # ❌ TODO: Redis connection
        # ❌ TODO: PostgreSQL connection
```

**Methods that need PostgreSQL:**
- `create_session()` - Store session in DB
- `get_session()` - Retrieve from DB (fallback)
- `invalidate_session()` - Mark as revoked in DB
- `save_conversation()` - Store messages in DB
- `get_conversation_context()` - Retrieve from DB (fallback)

**Methods that need Redis:**
- `create_session()` - Cache with 24hr TTL
- `get_session()` - Fast retrieval
- `invalidate_session()` - Delete from cache
- `save_conversation()` - Cache with 1hr TTL
- `get_conversation_context()` - Fast retrieval

**Status:** ⚠️ **PLACEHOLDER - NEEDS IMPLEMENTATION**

---

### **3. `mcp_host/main.py`** 🚀
**Purpose:** FastAPI server

**PostgreSQL Dependencies:**
```python
@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    await state_manager.initialize()  # ❌ Tries to init DB
```

**Redis Dependencies:**
- Same as above through `state_manager`

**Functions that use state:**
- `login()` - Creates session (uses state manager)
- `logout()` - Invalidates session (uses state manager)
- `get_profile()` - Reads from state
- `chat()` - Saves conversation (uses state manager)
- `get_conversations()` - Retrieves from DB

**Status:** ⚠️ **DEPENDS ON state.py implementation**

---

### **4. `mcp_host/auth.py`** 🔐
**Purpose:** Authentication

**Database Dependencies:**
- ❌ NO DIRECT dependencies
- Uses: JWT tokens only
- ✅ Fully implemented and ready

**Status:** ✅ **COMPLETE - NO EXTERNAL DEPS**

---

### **5. `mcp_host/models.py`** 📋
**Purpose:** Pydantic schemas

**Database Dependencies:**
- ❌ NO DIRECT dependencies
- Pure data models
- ✅ Fully implemented

**Status:** ✅ **COMPLETE - NO EXTERNAL DEPS**

---

### **6. `mcp_servers/base_server.py`** 📡
**Purpose:** Base MCP server class

**Database Dependencies:**
- ❌ NO DIRECT dependencies
- Reads only (if needed in child classes)

**Status:** ✅ **COMPLETE - NO EXTERNAL DEPS**

---

### **7. `mcp_servers/calendar_server/main.py`** 📅
**Purpose:** Calendar MCP server

**Database Dependencies:**
- ❌ NO DIRECT dependencies
- Returns mock data
- Could read from DB in future

**Status:** ✅ **READY - Mock data only**

---

### **8. `mcp_servers/gmail_server/main.py`** 📧
**Purpose:** Gmail MCP server

**Database Dependencies:**
- ❌ NO DIRECT dependencies
- Returns mock data
- Could read from DB in future

**Status:** ✅ **READY - Mock data only**

---

## 🚨 CRITICAL ISSUES TO RESOLVE

### **Issue 1: StateManager Not Implemented** 🔴
**Severity:** CRITICAL
**File:** `mcp_host/state.py`
**Problem:** Redis & PostgreSQL connections are placeholders

```python
# Current (BROKEN):
self.redis = None
self.db_connection = None

# Needs to be:
import aioredis
import asyncpg

self.redis = await aioredis.from_url(settings.REDIS_URL)
self.db_connection = await asyncpg.connect(settings.DATABASE_URL)
```

**Impact:** 
- Can't store sessions
- Can't persist conversations
- Can't cache data
- **API will fail on startup**

---

### **Issue 2: Required Packages Missing** 🔴
**File:** `requirements.txt`
**Problem:** Need async database drivers

```
# Missing:
aioredis==2.0.1
asyncpg==0.29.0  # PostgreSQL async driver
```

**Current:** ✅ Already added to requirements.txt

---

### **Issue 3: Database Schema Not Initialized** 🟡
**Severity:** HIGH
**File:** `docker/init-scripts/postgres/01-schema.sql`
**Problem:** Schema only created if Docker runs successfully

**Depends on:**
1. Docker Compose running
2. PostgreSQL service healthy
3. init-scripts executed

---

## 📈 SERVICE STARTUP SEQUENCE

```
1. Docker starts
   ├── PostgreSQL (port 5432)
   │   ├── Waits for health check
   │   ├── Runs 01-schema.sql
   │   └── Ready ✅
   │
   ├── Redis (port 6379)
   │   ├── Waits for health check
   │   └── Ready ✅
   │
   └── MCP Host (port 8000)
       ├── Reads config.py (DATABASE_URL, REDIS_URL)
       ├── Calls state_manager.initialize()
       │   ├── Connects to PostgreSQL ❌ NEEDS IMPLEMENTATION
       │   ├── Connects to Redis ❌ NEEDS IMPLEMENTATION
       │   └── If fails → app crashes 💥
       └── Starts FastAPI server
```

---

## 🎯 WHAT NEEDS TO BE DONE

### **PRIORITY 1: Implement StateManager** (CRITICAL)
**File:** `mcp_host/state.py`
**Estimated Time:** 2-3 hours

```python
async def initialize(self):
    """Initialize connections"""
    try:
        # Redis connection
        self.redis = await aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf8",
            decode_responses=True
        )
        
        # PostgreSQL connection pool
        self.db_connection = await asyncpg.create_pool(
            settings.DATABASE_URL,
            min_size=10,
            max_size=20
        )
        
        logger.info("State manager initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        raise
```

**Then implement all methods:**
- `create_session()` - Dual write (Redis + PostgreSQL)
- `get_session()` - Read from Redis, fallback to PostgreSQL
- `invalidate_session()` - Delete from Redis, update in PostgreSQL
- `save_conversation()` - Dual write with TTL
- `get_conversation_context()` - Redis first, PostgreSQL fallback

---

### **PRIORITY 2: Test StateManager** (HIGH)
**File:** `tests/integration/test_state_management.py`
**Estimated Time:** 1 hour

```python
@pytest.mark.asyncio
async def test_redis_connection():
    """Test Redis connectivity"""
    # Connect to local Redis
    # Verify PING works

@pytest.mark.asyncio
async def test_postgres_connection():
    """Test PostgreSQL connectivity"""
    # Connect to local PostgreSQL
    # Verify schema created

@pytest.mark.asyncio
async def test_session_flow():
    """Test complete session flow"""
    # Create session in Redis
    # Verify in PostgreSQL
    # Retrieve from Redis
    # Invalidate and verify
```

---

### **PRIORITY 3: Docker Health Checks** (HIGH)
**File:** `docker/docker-compose.yml`
**Status:** ✅ Already configured

```yaml
postgres:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U mcpagent"]
    interval: 10s
    timeout: 5s
    retries: 5

redis:
  healthcheck:
    test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
    interval: 10s
    timeout: 5s
    retries: 5
```

---

## 🔍 DEPENDENCY CHECKLIST

### **Before Running:**

- [ ] Docker installed
- [ ] Docker Compose installed
- [ ] Python 3.11+
- [ ] Virtual environment activated
- [ ] requirements.txt installed (`pip install -r requirements.txt`)

### **First Run:**

1. [ ] Check PostgreSQL can start: `docker ps | grep postgres`
2. [ ] Check Redis can start: `docker ps | grep redis`
3. [ ] Verify schema created: `psql -U mcpagent -d mcpagent -c "\dt"`
4. [ ] Verify Redis running: `redis-cli ping`
5. [ ] Start MCP Host: `python -m mcp_host.main`

### **Testing:**

- [ ] Unit tests (no external deps): `pytest tests/unit/`
- [ ] Integration tests (need external deps): `pytest tests/integration/`

---

## 📋 IMPLEMENTATION ROADMAP

```
Week 1:
├── [ ] Implement StateManager (Redis + PostgreSQL)
├── [ ] Test state management
├── [ ] Fix startup sequence
└── [ ] Run end-to-end test

Week 2:
├── [ ] Add LangChain agent
├── [ ] Add tool execution tracking
├── [ ] Add RAG system
└── [ ] Full integration tests

Week 3:
├── [ ] Production deployment
├── [ ] AWS setup
├── [ ] Monitoring & logging
└── [ ] Performance optimization
```

---

## 💡 KEY INSIGHTS

1. **StateManager is BLOCKING** - Can't run anything without it
2. **Docker Compose handles infrastructure** - We just need to implement app code
3. **Mock data for MCP servers is OK** - Calendar/Gmail can stay as-is for now
4. **Tests don't need external deps** - auth.py can be tested standalone
5. **Async/await required** - Everything uses asyncpg and aioredis

---

**Status Summary:**
- ✅ Configuration: Ready
- ✅ Models: Ready
- ✅ Authentication: Ready
- ❌ State Management: BLOCKED (needs implementation)
- ✅ MCP Servers: Ready (mock data)
- ⚠️ Docker: Ready (waiting for app implementation)
- ⚠️ Tests: Partial (need state management tests)

**Next Action:** Implement StateManager in `mcp_host/state.py`
