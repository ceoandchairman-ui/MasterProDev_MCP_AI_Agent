"""FastAPI server for MCP Host"""

from fastapi import FastAPI, HTTPException, Depends, status, Header, Request, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response, StreamingResponse
from fastapi.openapi.utils import get_openapi
import uuid  # Import uuid for trace_id generation
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    _SLOWAPI_AVAILABLE = True
except ImportError:
    _SLOWAPI_AVAILABLE = False
    # Graceful stub — no rate limiting when slowapi is not installed
    def get_remote_address(request):  # noqa: E301
        return request.client.host if request.client else "unknown"

    class Limiter:  # noqa: E302
        def __init__(self, **kwargs):
            pass
        def limit(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from pydantic_settings import BaseSettings
import logging
import httpx
import os
import asyncio
from typing import Optional
from pathlib import Path
import time

from .config import settings
from .models import (
    LoginRequest, ChatRequest, TokenResponse, ChatResponse,
    UserProfileResponse, HealthResponse
)
from .auth import hash_password, verify_password, create_access_token, decode_token
from .state import state_manager, ConversationState
from .agent import mcp_agent
from .rag_service import rag_service
from .evaluator import evaluator
from .quality_gate import initialize_quality_gate, quality_gate

try:
    from .voice_service import voice_service  # Voice processing (STT/TTS)
    _VOICE_SERVICE_AVAILABLE = True
except Exception as _vs_err:
    voice_service = None  # type: ignore
    _VOICE_SERVICE_AVAILABLE = False
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    Instrumentator = None  # type: ignore
    _PROMETHEUS_AVAILABLE = False

# Custom Prometheus metrics
if _PROMETHEUS_AVAILABLE:
    from prometheus_client import Counter, Histogram

    # Measures the duration of tool calls.
    # Buckets are in seconds, from 100ms to 10s.
    TOOL_CALL_DURATION = Histogram(
        "mcp_tool_call_duration_seconds",
        "Duration of tool calls",
        ["tool_name"]
    )

    # Counts the number of tool calls, labeled by status (success/error).
    TOOL_CALL_COUNTER = Counter(
        "mcp_tool_calls_total",
        "Total number of tool calls",
        ["tool_name", "status"]
    )

# Configure logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

# Get static directory path
STATIC_DIR = Path(__file__).parent / "static"


# Lifespan event handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events"""
    # Startup
    logger.info("Starting MCP Host...")
    await state_manager.initialize()

    # Instrument the app with Prometheus if available
    if _PROMETHEUS_AVAILABLE and Instrumentator:
        Instrumentator().instrument(app).expose(app)
        logger.info("✓ Prometheus instrumentation enabled.")

    # Initialize RAG service in background to avoid blocking startup
    asyncio.create_task(rag_service.initialize_async())

    await mcp_agent.initialize()

    # Initialize the Quality Gate with the LLM manager from the agent
    if mcp_agent.llm_manager:
        initialize_quality_gate(mcp_agent.llm_manager)
        logger.info("✅ Quality Gate initialized.")
    else:
        logger.warning("⚠️ Quality Gate could not be initialized: LLM manager not available.")

    # Initialize file processor at startup (not lazily per-request)
    from .file_processor import initialize_file_processor
    from .voice_service import voice_service as _vs
    _openai_client = None
    _openai_key = os.environ.get("OPENAI_API_KEY")
    if _openai_key:
        try:
            from openai import OpenAI
            _openai_client = OpenAI(api_key=_openai_key)
        except Exception as _e:
            logger.warning(f"OpenAI client init failed: {_e}")
    initialize_file_processor(_openai_client, _vs)

    logger.info("MCP Host started successfully")
    yield
    # Shutdown
    logger.info("Shutting down MCP Host...")
    await state_manager.shutdown()
    logger.info("MCP Host shut down")


# Rate Limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["100 per minute"])
app = FastAPI(
    title="MCP Host - Master Control Program",
    description="Main server for the MCP Agent, handling chat, voice, and tool orchestration.",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Performs a health check of the service and its dependencies.
    """
    start_time = time.time()
    service_status = {
        "calendar_server": "pending",
        "gmail_server": "pending",
        "rag_service": "pending",
        "llm_provider": "pending"
    }
    overall_status = "ok"

    async def check_service(service_name: str, url: str):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Use the health endpoint of the downstream service if it exists
                health_url = f"{url.rstrip('/')}/health"
                try:
                    response = await client.get(health_url)
                except httpx.ConnectError:
                    # Fallback to base URL if /health is not implemented
                    response = await client.get(url)
                
                if response.status_code == 200:
                    service_status[service_name] = "ok"
                else:
                    service_status[service_name] = "error"
                    nonlocal overall_status
                    overall_status = "error"
        except Exception as e:
            logger.warning(f"Health check for {service_name} failed: {e}")
            service_status[service_name] = "error"
            nonlocal overall_status
            overall_status = "error"

    # Check downstream services
    await asyncio.gather(
        check_service("calendar_server", settings.CALENDAR_SERVER_URL),
        check_service("gmail_server", settings.GMAIL_SERVER_URL)
    )

    # Check RAG service
    if rag_service.is_initialized():
        service_status["rag_service"] = "ok"
    else:
        service_status["rag_service"] = "degraded"
        # Not a critical failure, just degraded
        if overall_status == "ok":
            overall_status = "degraded"

    # Check LLM provider
    if mcp_agent.llm_manager and mcp_agent.llm_manager.active_provider:
        service_status["llm_provider"] = "ok"
    else:
        service_status["llm_provider"] = "error"
        overall_status = "error"

    duration = time.time() - start_time
    
    response_status_code = status.HTTP_200_OK if overall_status in ["ok", "degraded"] else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        content={
            "status": overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration, 4),
            "dependencies": service_status,
            "active_llm": mcp_agent.llm_manager.get_active_provider_info() if mcp_agent.llm_manager else None
        },
        status_code=response_status_code
    )


# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    logger.info(f"Mounted static files from {STATIC_DIR}")

# Apply rate limiter to all routes
if _SLOWAPI_AVAILABLE:
    app.state.limiter = limiter
    app.add_exception_handler(HTTPException, limiter.http_exception_handler)
    logger.info("✓ Rate limiting enabled.")


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/", tags=["General"], summary="Root endpoint, serves login page")
async def root():
    """Serves the main login page."""
    login_path = STATIC_DIR / "login.html"
    if login_path.exists():
        return FileResponse(login_path)
    return HTMLResponse("<h1>MCP Host</h1><p>Login page not found.</p>")

@app.get("/health", response_model=HealthResponse, tags=["General"], summary="Health check endpoint")
async def health_check():
    """Provides a health check endpoint for monitoring."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "database": await state_manager.is_healthy(),
            "llm": mcp_agent.llm_manager.is_healthy(),
            "rag": rag_service.is_healthy(),
            "calendar": await _check_service_health(settings.CALENDAR_SERVER_URL),
            "gmail": await _check_service_health(settings.GMAIL_SERVER_URL),
        }
    }

async def _check_service_health(service_url: Optional[str]) -> str:
    """Helper to check the health of a downstream service."""
    if not service_url:
        return "not_configured"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{service_url}/health")
            return "ok" if response.status_code == 200 else "unhealthy"
    except httpx.RequestError:
        return "unreachable"

@app.get("/login-docs", include_in_schema=False)
async def login_docs():
    """Serves a simple login page for accessing the documentation."""
    return FileResponse(str(STATIC_DIR / "login-docs.html"))

@app.get("/login", include_in_schema=False)
async def login_page():
    """Login page for admin access"""
    return FileResponse(str(STATIC_DIR / "login.html"))

@app.get("/docs", include_in_schema=False)
async def swagger_ui(
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """Swagger UI (requires valid auth token)"""
    # Try to get token from query parameter or header
    auth_token = None
    
    if token:
        # Token from URL query parameter
        auth_token = token
    elif authorization:
        # Token from Authorization header
        auth_token = get_token_from_header(authorization)
    else:
        # No token provided - redirect to login page
        return FileResponse(str(STATIC_DIR / "login-docs.html"))
    
    # Validate token
    payload = decode_token(auth_token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please login again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.info(f"📋 Swagger docs accessed by user {payload.get('sub')}")
    
    # Return Swagger UI HTML with token in header
    from fastapi.openapi.docs import get_swagger_ui_html
    from fastapi.responses import HTMLResponse
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MCP Host API Documentation</title>
        <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
        <script>
            window.onload = function() {{
                window.ui = SwaggerUIBundle({{
                    url: "/openapi.json",
                    dom_id: '#swagger-ui',
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIStandalonePreset
                    ],
                    layout: "StandaloneLayout",
                    requestInterceptor: (req) => {{
                        req.headers['Authorization'] = 'Bearer {auth_token}';
                        return req;
                    }}
                }});
            }};
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, login_req: LoginRequest):
    """User login - returns JWT token
    
    Requires email and password authentication.
    Email must match ADMIN_EMAIL, password verified against ADMIN_PASSWORD.
    Rate limited: 5 attempts per minute per IP address.
    """
    # Verify email
    if login_req.email != settings.ADMIN_EMAIL:
        logger.warning(f"✗ Failed login attempt: invalid email {login_req.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if login_req.password != settings.ADMIN_PASSWORD:
        logger.warning(f"✗ Failed login attempt for: {login_req.email} (incorrect password)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = login_req.email or "00000000-0000-0000-0000-000000000123"
    
    # Create tokens
    access_token = create_access_token(
        data={"sub": user_id, "email": login_req.email},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_access_token(
        data={"sub": user_id, "type": "refresh"}
    )
    
    # Create session
    await state_manager.create_session(user_id, access_token, "employee")
    
    logger.info(f"✓ User logged in: {login_req.email}")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@app.post("/chat-login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def chat_login(request: Request, login_req: LoginRequest):
    """Chat login - separate from admin login
    
    Rejects all login attempts. Users should use 'Continue as Guest' instead.
    This endpoint exists to prevent admin credentials from being used in chat.
    """
    # Reject all login attempts for chat
    logger.warning(f"Chat login attempt rejected for: {login_req.email}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="User accounts not available. Please continue as Guest.",
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.post("/logout")
async def logout(authorization: Optional[str] = Header(None)):
    """Logout - invalidate session"""
    token = get_token_from_header(authorization)
    await state_manager.invalidate_session(token)
    return {"message": "Logged out successfully"}


@app.get("/user/profile", response_model=UserProfileResponse)
async def get_profile(authorization: Optional[str] = Header(None)):
    """Get user profile"""
    token = get_token_from_header(authorization)
    payload = decode_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    return UserProfileResponse(
        id=payload.get("sub"),
        email=payload.get("email"),
        name="User",
        user_type="employee",
        role="employee"
    )


@app.post("/voice")
async def voice_chat(
    audio: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    """Voice chat endpoint - accepts audio, returns audio response
    
    Workflow:
    1. Receive audio file (webm/mp3/wav)
    2. Convert speech to text (STT via Whisper)
    3. Process through agent (same as text chat)
    4. Convert response to speech (TTS via OpenAI)
    5. Return audio file
    """
    if not _VOICE_SERVICE_AVAILABLE or voice_service is None:
        raise HTTPException(status_code=503, detail="Voice service unavailable (openai package missing)")
    
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Initiating new voice chat request.")

    try:
        # Get session (same as /chat endpoint)
        if authorization:
            try:
                token = get_token_from_header(authorization)
                session = await state_manager.get_session(token)
                if session:
                    session_id = session["session_id"]
                    user_id = session["user_id"]
                    conversation_id = session.get("conversation_id")
                    conversation_history = await state_manager.get_conversation_history(session_id)
                else:
                    session_id = str(uuid.uuid4())
                    user_id = "guest"
                    conversation_id = str(uuid.uuid4())
                    conversation_history = []
            except:
                session_id = str(uuid.uuid4())
                user_id = "guest"
                conversation_id = str(uuid.uuid4())
                conversation_history = []
        else:
            # No token - guest mode
            session_id = str(uuid.uuid4())
            user_id = "guest"
            conversation_id = str(uuid.uuid4())
            conversation_history = []
        
        # Step 1: STT - Convert audio to text
        audio_bytes = await audio.read()
        filename = audio.filename or "audio.webm"
        
        logger.info(f"[{trace_id}] 🎤 Voice input received: {len(audio_bytes)} bytes, format: {filename}")
        user_message = await voice_service.speech_to_text(audio_bytes, filename)
        logger.info(f"[{trace_id}] 📝 Transcribed: {user_message}")
        
        # Step 2: Process through agent
        agent_result = await mcp_agent.process_message(
            message=user_message,
            session_id=session_id,
            conversation_history=conversation_history,
            trace_id=trace_id
        )
        
        response_text = agent_result.get("response", "I couldn't process that.")
        logger.info(f"[{trace_id}] 💬 Agent response: {response_text[:100]}...")
        
        # Step 3: TTS - Convert text to speech (returns tuple: audio_bytes, content_type)
        audio_response, audio_content_type = await voice_service.text_to_speech(response_text)
        
        # Step 4: Save conversation (if authenticated)
        if user_id != "guest":
            await state_manager.save_conversation_turn(
                session_id, user_id, conversation_id, user_message, response_text
            )
        
        # Helper to sanitize text for HTTP headers (ASCII only)
        def sanitize_header(text: str) -> str:
            return text.encode('ascii', 'replace').decode('ascii')[:200]
        
        # Return audio if available, otherwise return JSON for browser TTS
        if audio_response:
            logger.info(f"[{trace_id}] 🔊 Generated audio response: {len(audio_response)} bytes ({audio_content_type})")
            return Response(
                content=audio_response,
                media_type=audio_content_type or "audio/mpeg",
                headers={
                    "Content-Disposition": "attachment; filename=response.mp3",
                    "X-Transcription": sanitize_header(user_message),
                    "X-Response-Text": sanitize_header(response_text)
                }
            )
        else:
            # No audio - return JSON with browser TTS fallback
            logger.info(f"[{trace_id}] 🔊 No server TTS, returning text for browser TTS")
            return JSONResponse(
                content={
                    "transcription": user_message,
                    "response": response_text,
                    "use_browser_tts": True
                },
                headers={
                    "X-Transcription": sanitize_header(user_message),
                    "X-Response-Text": sanitize_header(response_text)
                }
            )
        
    except Exception as e:
        logger.error(f"[{trace_id}] ❌ Voice chat error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice processing failed: {str(e)}"
        )


@app.get("/voice-chat")
async def voice_chat_page():
    """Serve voice chat UI with avatar (now unified in chat-widget)"""
    return FileResponse(str(STATIC_DIR / "widget-demo.html"))


@app.get("/evaluation")
async def get_evaluation_metrics(authorization: Optional[str] = Header(None)):
    """Get agent evaluation metrics and task completion report
    
    Returns comprehensive evaluation data including:
    - Task completion rates by category (Calendar, Knowledge, Email, Conversation)
    - Overall success rate and production readiness
    - Individual task results
    """
    token = get_token_from_header(authorization)
    payload = decode_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    # Get evaluation metrics
    metrics = evaluator.get_metrics()
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "overall_success_rate": round(metrics.overall_success_rate, 2),
            "total_tasks": metrics.total_tasks,
            "total_passed": metrics.total_passed,
            "production_ready": metrics.production_ready,
            "production_gate_threshold": 85.0
        },
        "categories": {
            "calendar": {
                "success_rate": round(metrics.calendar_success_rate, 2),
                "total": metrics.calendar_total,
                "passed": metrics.calendar_passed,
                "threshold": 90.0,
                "meets_threshold": metrics.calendar_success_rate >= 90.0 if metrics.calendar_total > 0 else None
            },
            "knowledge": {
                "success_rate": round(metrics.knowledge_success_rate, 2),
                "total": metrics.knowledge_total,
                "passed": metrics.knowledge_passed,
                "threshold": 85.0,
                "meets_threshold": metrics.knowledge_success_rate >= 85.0 if metrics.knowledge_total > 0 else None
            },
            "email": {
                "success_rate": round(metrics.email_success_rate, 2),
                "total": metrics.email_total,
                "passed": metrics.email_passed,
                "threshold": 80.0,
                "meets_threshold": metrics.email_success_rate >= 80.0 if metrics.email_total > 0 else None
            },
            "conversation": {
                "success_rate": round(metrics.conversation_success_rate, 2),
                "total": metrics.conversation_total,
                "passed": metrics.conversation_passed,
                "threshold": 95.0,
                "meets_threshold": metrics.conversation_success_rate >= 95.0 if metrics.conversation_total > 0 else None
            }
        },
        "recent_tasks": [
            {
                "task_id": task.task_id,
                "category": task.category,
                "task_type": task.task_type,
                "user_request": task.user_request,
                "tools_used": task.tool_calls,
                "success": task.success,
                "reason": task.reason,
                "timestamp": task.timestamp
            }
            for task in evaluator.results[-20:]  # Last 20 tasks
        ]
    }



# ============================================================================
# OAuth Proxy Endpoints (Routes calendar/gmail OAuth through mcp_host)
# ============================================================================

@app.get("/integrations/google/calendar/auth")
async def calendar_auth_proxy():
    """Proxy calendar OAuth - redirects to Google with correct callback URI"""
    try:
        callback_uri = f"{settings.PUBLIC_DOMAIN}/integrations/google/calendar/callback"
        logger.info(f"📅 Calendar OAuth: callback_uri={callback_uri}, calendar_server={settings.CALENDAR_SERVER_URL}")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.CALENDAR_SERVER_URL}/auth",
                params={"redirect_uri": callback_uri}
            )
        logger.info(f"📅 Calendar server responded with status {response.status_code}")
        return HTMLResponse(content=response.text)
    except Exception as e:
        logger.error(f"❌ Calendar auth proxy error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Calendar auth failed: {str(e)}")


@app.get("/integrations/google/calendar/callback")
async def calendar_callback_proxy(code: str = None, state: str = None, error: str = None):
    """Proxy calendar OAuth callback - passes code to calendar-server"""
    if error:
        return HTMLResponse(
            content=f"""
            <html>
                <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                    <h1>✗ Authorization Denied</h1>
                    <p>Error: {error}</p>
                </body>
            </html>
            """
        )
    
    try:
        logger.info(f"📅 Calendar callback: code={code[:10] if code else 'None'}...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.CALENDAR_SERVER_URL}/callback",
                params={"code": code, "state": state}
            )
        logger.info(f"📅 Calendar callback processed, status={response.status_code}")
        return HTMLResponse(content=response.text)
    except Exception as e:
        logger.error(f"❌ Calendar callback proxy error: {e}", exc_info=True)
        return HTMLResponse(
            content=f"""
            <html>
                <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                    <h1>✗ Authorization Failed</h1>
                    <p>Error: {str(e)}</p>
                </body>
            </html>
            """
        )


@app.get("/integrations/google/gmail/auth")
async def gmail_auth_proxy():
    """Proxy Gmail OAuth - redirects to Google with correct callback URI"""
    try:
        callback_uri = f"{settings.PUBLIC_DOMAIN}/integrations/google/gmail/callback"
        logger.info(f"📧 Gmail OAuth: callback_uri={callback_uri}, gmail_server={settings.GMAIL_SERVER_URL}")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.GMAIL_SERVER_URL}/auth",
                params={"redirect_uri": callback_uri}
            )
        logger.info(f"📧 Gmail server responded with status {response.status_code}")
        return HTMLResponse(content=response.text)
    except Exception as e:
        logger.error(f"❌ Gmail auth proxy error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Gmail auth failed: {str(e)}")


@app.get("/integrations/google/gmail/callback")
async def gmail_callback_proxy(code: str = None, state: str = None, error: str = None):
    """Proxy Gmail OAuth callback - passes code to gmail-server"""
    if error:
        return HTMLResponse(
            content=f"""
            <html>
                <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                    <h1>✗ Authorization Denied</h1>
                    <p>Error: {error}</p>
                </body>
            </html>
            """
        )
    
    try:
        logger.info(f"📧 Gmail callback: code={code[:10] if code else 'None'}...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.GMAIL_SERVER_URL}/callback",
                params={"code": code, "state": state}
            )
        logger.info(f"📧 Gmail callback processed, status={response.status_code}")
        return HTMLResponse(content=response.text)
    except Exception as e:
        logger.error(f"❌ Gmail callback proxy error: {e}", exc_info=True)
        logger.error(f"Gmail callback proxy error: {e}")
        return HTMLResponse(
            content=f"""
            <html>
                <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                    <h1>✗ Authorization Failed</h1>
                    <p>Error: {str(e)}</p>
                </body>
            </html>
            """
        )