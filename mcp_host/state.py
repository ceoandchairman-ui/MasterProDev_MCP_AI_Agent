"""State management - Redis and PostgreSQL coordination"""

import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import uuid

import redis.asyncio as aioredis

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


class StateManager:
    """Manages state across Redis (cache) and PostgreSQL (persistent)"""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self.db_pool: Optional[Any] = None  # asyncpg.Pool if available
        self.degraded_mode = False
        # In-memory storage for degraded mode
        self._memory_sessions: Dict[str, dict] = {}
        self._memory_conversations: Dict[str, List[dict]] = {}

    async def initialize(self):
        """Initialize Redis and PostgreSQL connections"""
        try:
            # Redis connection
            self.redis = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf8",
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("✓ Redis connected")

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
                        await self.redis.setex(
                            f"session:{token}",
                            SESSION_TTL,
                            json.dumps(session_dict)
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

    async def save_conversation(
        self, user_id: str, conversation_id: str, message: str, response: str
    ) -> bool:
        """Save conversation to PostgreSQL and cache in Redis"""
        # Degraded mode - use in-memory storage
        if self.degraded_mode:
            if conversation_id not in self._memory_conversations:
                self._memory_conversations[conversation_id] = []
            self._memory_conversations[conversation_id].append({
                "message": message,
                "response": response,
                "created_at": datetime.utcnow().isoformat()
            })
            logger.debug(f"✓ Conversation stored in memory")
            return True
        
        try:
            # Store in PostgreSQL (persistent) if available
            if ASYNCPG_AVAILABLE and self.db_pool:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO conversations (conversation_id, user_id, message, response, created_at)
                        VALUES ($1, $2, $3, $4, NOW())
                        """,
                        conversation_id, user_id, message, response
                    )
                logger.debug(f"✓ Conversation saved to PostgreSQL: {conversation_id}")

            # Cache in Redis
            if self.redis:
                conversation_data = {
                    "message": message,
                    "response": response,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                await self.redis.setex(
                    f"conversation:{conversation_id}",
                    CONVERSATION_CACHE_TTL,
                    json.dumps(conversation_data)
                )
                logger.debug(f"✓ Conversation cached in Redis: {conversation_id}")

            return True

        except Exception as e:
            logger.error(f"✗ Error saving conversation: {e}")
            return False

    async def get_conversation_context(self, user_id: str, limit: int = 10) -> Optional[Dict[str, Any]]:
        """Get recent conversation context from Redis (fast) or PostgreSQL (fallback)"""
        # Degraded mode - use in-memory storage
        if self.degraded_mode:
            # Get all conversations for this user from memory
            all_messages = []
            for conv_id, messages in self._memory_conversations.items():
                all_messages.extend(messages)
            
            if all_messages:
                # Sort by created_at and limit
                all_messages.sort(key=lambda x: x.get("created_at", ""), reverse=True)
                limited = all_messages[:limit]
                return {
                    "user_id": user_id,
                    "conversation_count": len(limited),
                    "messages": limited,
                    "retrieved_at": datetime.utcnow().isoformat(),
                }
            return None
        
        try:
            # Try Redis first
            if self.redis:
                cached_context = await self.redis.get(f"context:{user_id}")
                if cached_context:
                    logger.debug(f"✓ Context found in Redis cache")
                    return json.loads(cached_context)

            # Fallback to PostgreSQL
            if ASYNCPG_AVAILABLE and self.db_pool:
                async with self.db_pool.acquire() as conn:
                    conversations = await conn.fetch(
                        """
                        SELECT id, message, response, created_at FROM conversations
                        WHERE user_id = $1
                        ORDER BY created_at DESC
                        LIMIT $2
                        """,
                        user_id, limit
                    )

                    if conversations:
                        context = {
                            "user_id": user_id,
                            "conversation_count": len(conversations),
                            "messages": [dict(c) for c in conversations],
                            "retrieved_at": datetime.utcnow().isoformat(),
                        }
                        
                        # Cache in Redis
                        if self.redis:
                            await self.redis.setex(
                                f"context:{user_id}",
                                CONVERSATION_CACHE_TTL,
                                json.dumps(context)
                            )
                        logger.debug(f"✓ Context retrieved and cached for user: {user_id}")
                        return context

            logger.debug(f"✗ No conversation context found for user: {user_id}")
            return None

        except Exception as e:
            logger.error(f"✗ Error retrieving conversation context: {e}")
            return None

    async def get_user_profile(self, user_id: str) -> Optional[dict]:
        """Get user profile from Redis or PostgreSQL"""
        try:
            # Try Redis first
            cached = await self.redis.get(f"user:{user_id}")
            if cached:
                logger.debug(f"✓ User profile found in Redis")
                return json.loads(cached)

            # Fallback to PostgreSQL
            if ASYNCPG_AVAILABLE and self.db_pool:
                async with self.db_pool.acquire() as conn:
                    user = await conn.fetchrow(
                        "SELECT id, username, email, created_at FROM users WHERE id = $1",
                        user_id
                    )
                    
                    if user:
                        user_dict = dict(user)
                        # Cache in Redis
                        await self.redis.setex(
                            f"user:{user_id}",
                            3600,  # 1 hour
                            json.dumps(user_dict)
                        )
                        logger.debug(f"✓ User profile found and cached")
                        return user_dict

            return None

        except Exception as e:
            logger.error(f"✗ Error retrieving user profile: {e}")
            return None


# Global state manager instance
state_manager = StateManager()
