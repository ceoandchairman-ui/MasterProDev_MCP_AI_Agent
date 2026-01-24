"""State management - Redis and PostgreSQL coordination"""

import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import uuid

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("redis not available - Redis operations will be limited")


try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logging.warning("asyncpg not available - PostgreSQL operations will be limited")

from .config import settings

logger = logging.getLogger(__name__)

# Constants
SESSION_TTL = 86400  # 24 hours in seconds
CONVERSATION_CACHE_TTL = 3600  # 1 hour in seconds


class ConversationState:
    """Represents the state of a single conversation."""
    def __init__(self, session_id: str, conversation_id: str):
        self.session_id = session_id
        self.conversation_id = conversation_id
        self.history: List[Dict[str, Any]] = []
        self.pending_action: Optional[str] = None  # Store pending tool calls as JSON string
        self.last_updated = datetime.utcnow()

    def add_turn(self, user_message: str, assistant_response: str):
        """Adds a turn to the conversation history."""
        self.history.append({"user": user_message, "assistant": assistant_response})
        self.last_updated = datetime.utcnow()

    def to_json(self) -> str:
        """Serializes state to JSON."""
        return json.dumps({
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "history": self.history,
            "pending_action": self.pending_action,
            "last_updated": self.last_updated.isoformat()
        })

    @classmethod
    def from_json(cls, json_str: str):
        """Deserializes state from JSON."""
        data = json.loads(json_str)
        state = cls(data["session_id"], data["conversation_id"])
        state.history = data.get("history", [])
        state.pending_action = data.get("pending_action")
        state.last_updated = datetime.fromisoformat(data.get("last_updated", datetime.utcnow().isoformat()))
        return state


class StateManager:
    """Manages state across Redis (cache) and PostgreSQL (persistent)"""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self.db_pool: Optional[Any] = None  # asyncpg.Pool if available
        self.degraded_mode = False
        # In-memory storage for degraded mode
        self._memory_sessions: Dict[str, dict] = {}
        self._memory_conversations: Dict[str, ConversationState] = {}

    async def initialize(self):
        """Initialize Redis and PostgreSQL connections"""
        try:
            # Redis connection
            if REDIS_AVAILABLE:
                self.redis = await aioredis.from_url(
                    settings.REDIS_URL,
                    encoding="utf8",
                    decode_responses=True
                )
                await self.redis.ping()
                logger.info("✓ Redis connected")
            else:
                raise ConnectionError("Redis is not installed or available.")

            # PostgreSQL connection pool (if asyncpg available)
            if ASYNCPG_AVAILABLE:
                self.db_pool = await asyncpg.create_pool(
                    settings.DATABASE_URL,
                    min_size=5,
                    max_size=20,
                    max_queries=50000,
                    max_cached_statement_lifetime=300,
                    max_cacheable_statement_size=15000,
                )
                logger.info("✓ PostgreSQL pool created")

                # Verify database schema exists
                async with self.db_pool.acquire() as conn:
                    tables = await conn.fetch(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                    )
                    logger.info(f"✓ Database tables: {len(tables)} found")
            else:
                logger.warning("⚠ PostgreSQL unavailable - using Redis only for persistence")

            logger.info("✓ State manager fully initialized")

        except Exception as e:
            logger.warning(f"⚠ State manager initialization warning: {e}")
            logger.warning("⚠ Running in degraded mode (no persistence)")
            self.degraded_mode = True
            # Continue without Redis - using in-memory storage

    async def shutdown(self):
        """Cleanup connections"""
        try:
            if self.redis:
                await self.redis.close()
                logger.info("✓ Redis disconnected")
            
            if self.db_pool and ASYNCPG_AVAILABLE:
                await self.db_pool.close()
                logger.info("✓ PostgreSQL pool closed")
                
        except Exception as e:
            logger.error(f"✗ Error during shutdown: {e}")

    async def create_session(self, user_id: str, token: str, user_type: str = "user") -> dict:
        """Create and store user session in both Redis and PostgreSQL"""
        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "token": token,
            "user_type": user_type,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(seconds=SESSION_TTL)).isoformat(),
        }
        
        # Degraded mode - use in-memory storage
        if self.degraded_mode:
            self._memory_sessions[token] = session_data
            logger.debug(f"✓ Session stored in memory: {session_id}")
            return session_data
        
        try:
            # Store in Redis (fast cache)
            if self.redis:
                await self.redis.setex(
                    f"session:{token}",
                    SESSION_TTL,
                    json.dumps(session_data)
                )
                logger.debug(f"✓ Session cached in Redis: {session_id}")

            # Store in PostgreSQL (persistent) if available
            if ASYNCPG_AVAILABLE and self.db_pool:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO sessions (session_id, user_id, token, user_type, created_at, expires_at)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (token) DO UPDATE SET
                            updated_at = NOW()
                        """,
                        session_id, user_id, token, user_type,
                        datetime.utcnow(), datetime.utcnow() + timedelta(seconds=SESSION_TTL)
                    )
                logger.debug(f"✓ Session stored in PostgreSQL: {session_id}")

            return session_data

        except Exception as e:
            logger.error(f"✗ Error creating session: {e}")
            # Fallback to in-memory
            self._memory_sessions[token] = session_data
            logger.debug(f"✓ Session stored in memory (fallback): {session_id}")
            return session_data

    async def get_session(self, token: str) -> Optional[dict]:
        """Get session data from Redis (fast path) or PostgreSQL (fallback)"""
        # Degraded mode - use in-memory storage
        if self.degraded_mode:
            return self._memory_sessions.get(token)
        
        try:
            # Try Redis first (fast path)
            if self.redis:
                cached = await self.redis.get(f"session:{token}")
                if cached:
                    logger.debug(f"✓ Session found in Redis cache")
                    return json.loads(cached)

            # Fallback to PostgreSQL
            if ASYNCPG_AVAILABLE and self.db_pool:
                async with self.db_pool.acquire() as conn:
                    session = await conn.fetchrow(
                        "SELECT * FROM sessions WHERE token = $1 AND expires_at > NOW()",
                        token
                    )
                    
                    if session:
                        session_dict = dict(session)
                        # Repopulate Redis cache
                        if self.redis:
                            await self.redis.setex(
                                f"session:{token}",
                                SESSION_TTL,
                                json.dumps(session_dict, default=str)
                            )
                        logger.debug(f"✓ Session found in PostgreSQL, refreshed cache")
                        return session_dict

            logger.debug(f"✗ Session not found or expired: {token}")
            return None

        except Exception as e:
            logger.error(f"✗ Error retrieving session: {e}")
            return None

    async def invalidate_session(self, token: str) -> bool:
        """Invalidate session in both Redis and PostgreSQL"""
        # Degraded mode - use in-memory storage
        if self.degraded_mode:
            if token in self._memory_sessions:
                del self._memory_sessions[token]
                logger.debug(f"✓ Session removed from memory")
            return True
        
        try:
            # Remove from Redis
            if self.redis:
                await self.redis.delete(f"session:{token}")
                logger.debug(f"✓ Session removed from Redis")

            # Mark as revoked in PostgreSQL
            if ASYNCPG_AVAILABLE and self.db_pool:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE sessions SET is_revoked = true, updated_at = NOW() WHERE token = $1",
                        token
                    )
                logger.debug(f"✓ Session revoked in PostgreSQL")

            return True

        except Exception as e:
            logger.error(f"✗ Error invalidating session: {e}")
            return False

    async def get_conversation_state(self, session_id: str) -> Optional[ConversationState]:
        """Retrieves the full state of a conversation from Redis."""
        if self.degraded_mode:
            return self._memory_conversations.get(session_id)

        if not self.redis:
            return None

        try:
            state_json = await self.redis.get(f"conversation_state:{session_id}")
            if state_json:
                return ConversationState.from_json(state_json)
            return None
        except Exception as e:
            logger.error(f"✗ Error retrieving conversation state: {e}")
            return None

    async def update_conversation_state(self, session_id: str, state: ConversationState):
        """Saves the full state of a conversation to Redis."""
        if self.degraded_mode:
            self._memory_conversations[session_id] = state
            return

        if not self.redis:
            return

        try:
            await self.redis.setex(
                f"conversation_state:{session_id}",
                CONVERSATION_CACHE_TTL,
                state.to_json()
            )
        except Exception as e:
            logger.error(f"✗ Error updating conversation state: {e}")


    async def save_conversation_turn(
        self, session_id: str, user_id: str, conversation_id: str, user_message: str, assistant_response: str
    ):
        """Saves a turn and updates the full conversation state."""
        state = await self.get_conversation_state(session_id)
        if not state:
            state = ConversationState(session_id, conversation_id)
        
        state.add_turn(user_message, assistant_response)
        await self.update_conversation_state(session_id, state)

        # Also save to persistent storage if available (skip for guests)
        if user_id != "guest" and ASYNCPG_AVAILABLE and self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO conversations (conversation_id, user_id, message, response, created_at)
                        VALUES ($1, $2, $3, $4, NOW())
                        """,
                        conversation_id, user_id, user_message, assistant_response
                    )
                logger.debug(f"✓ Conversation turn saved to PostgreSQL: {conversation_id}")
            except Exception as e:
                logger.error(f"✗ Error saving conversation turn to PostgreSQL: {e}")

    async def get_conversation_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Retrieves conversation history from the state (last 50 messages)."""
        state = await self.get_conversation_state(session_id)
        return state.history[-50:] if state else []


# Global state manager instance
state_manager = StateManager()

