"""FastAPI server for MCP Host"""

from fastapi import FastAPI, HTTPException, Depends, status, Header, Request, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response
from fastapi.openapi.utils import get_openapi
from slowapi import Limiter
from slowapi.util import get_remote_address
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from pydantic_settings import BaseSettings
import logging
import uuid
import httpx
import os
from typing import Optional
from pathlib import Path

from .config import settings
from .models import (
    LoginRequest, ChatRequest, TokenResponse, ChatResponse,
    UserProfileResponse, HealthResponse
)
from .auth import hash_password, verify_password, create_access_token, decode_token
from .state import state_manager
from .agent import mcp_agent
from .rag_service import rag_service
from .evaluator import evaluator  # Import evaluator for metrics endpoint
from .voice_service import voice_service  # Voice processing (STT/TTS)
from prometheus_fastapi_instrumentator import Instrumentator

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
    rag_service.initialize()
    await mcp_agent.initialize()
    logger.info("MCP Host started successfully")
    yield
    # Shutdown
    logger.info("Shutting down MCP Host...")
    await state_manager.shutdown()
    logger.info("MCP Host shut down")


# Create FastAPI app
# Disable default docs - we use custom auth-protected endpoints below
app = FastAPI(
    title="MCP Host - Master Pro Dev AI Agent",
    version="1.0.0",
    description="AI Agent with MCP servers for Calendar and Gmail",
    lifespan=lifespan,
    docs_url=None,  # Disabled - using custom /docs with auth
    redoc_url=None,  # Disabled
    openapi_url=None  # Disabled - using custom /openapi.json with auth
)

# Initialize rate limiter for login endpoint
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# Instrument the app
Instrumentator().instrument(app).expose(app)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Helper Functions
# ============================================================================

def get_token_from_header(authorization: Optional[str] = None) -> str:
    """Extract token from authorization header"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header"
        )
    return parts[1]


# ============================================================================
# Secure OpenAPI/Docs (Require Authentication)
# ============================================================================

@app.get("/openapi.json", include_in_schema=False)
async def openapi_schema(authorization: Optional[str] = Header(None)):
    """Get OpenAPI schema (requires valid auth token)"""
    # Require authentication
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header. Use /login to get a token."
        )
    
    token = get_token_from_header(authorization)
    payload = decode_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Use /login to get a new token."
        )
    
    logger.info(f"📋 OpenAPI schema accessed by user {payload.get('sub')}")
    
    # Generate and return OpenAPI schema
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="MCP Host - Master Pro Dev AI Agent",
        version="1.0.0",
        description="AI Agent with MCP servers for Calendar and Gmail",
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


# Login page for docs access
@app.get("/login-docs", include_in_schema=False)
async def login_docs_page():
    """Login page to access API documentation"""
    return FileResponse(str(STATIC_DIR / "login-docs.html"))


# Login page for chat (admin login)
@app.get("/login", include_in_schema=False)
async def login_page():
    """Login page for admin access"""
    return FileResponse(str(STATIC_DIR / "login.html"))


# Custom docs UI with auth
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


# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Routes
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """System health check"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
        services={
            "api": "ok",
            "database": "ok",  # TODO: Check actual status
            "redis": "ok",     # TODO: Check actual status
        }
    )


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
        
        logger.info(f"🎤 Voice input received: {len(audio_bytes)} bytes, format: {filename}")
        user_message = await voice_service.speech_to_text(audio_bytes, filename)
        logger.info(f"📝 Transcribed: {user_message}")
        
        # Step 2: Process through agent
        agent_result = await mcp_agent.process_message(
            message=user_message,
            session_id=session_id,
            conversation_history=conversation_history
        )
        
        response_text = agent_result.get("response", "I couldn't process that.")
        logger.info(f"💬 Agent response: {response_text[:100]}...")
        
        # Step 3: TTS - Convert text to speech (may return None if no TTS available)
        audio_response = await voice_service.text_to_speech(response_text)
        
        # Step 4: Save conversation (if authenticated)
        if user_id != "guest":
            await state_manager.save_conversation_turn(
                session_id, user_id, conversation_id, user_message, response_text
            )
        
        # Return audio if available, otherwise return JSON for browser TTS
        if audio_response:
            logger.info(f"🔊 Generated audio response: {len(audio_response)} bytes")
            return Response(
                content=audio_response,
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": "attachment; filename=response.mp3",
                    "X-Transcription": user_message,
                    "X-Response-Text": response_text[:200]
                }
            )
        else:
            # No audio - return JSON with text for browser TTS fallback
            logger.info("🔊 No server TTS, returning text for browser TTS")
            return JSONResponse(
                content={
                    "transcription": user_message,
                    "response": response_text,
                    "use_browser_tts": True
                },
                headers={
                    "X-Transcription": user_message,
                    "X-Response-Text": response_text[:200]
                }
            )
        
    except Exception as e:
        logger.error(f"❌ Voice chat error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice processing failed: {str(e)}"
        )


@app.get("/voice-chat")
async def voice_chat_page():
    """Serve voice chat UI with avatar (now unified in chat-widget)"""
    return FileResponse(str(STATIC_DIR / "chat-widget.html"))


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


@app.post("/chat", response_model=ChatResponse)
async def chat(
    message: str = Form(...),
    conversation_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    authorization: Optional[str] = Header(None)
):
    """Chat endpoint - PUBLIC - guests allowed, authentication optional
    
    Supports text messages and file uploads:
    - Audio files: Transcribed to text
    - Video files: Audio extracted and transcribed
    - Images: Analyzed with vision model
    - PDFs/Word: Text extracted
    """
    
    # Process file if uploaded
    file_content = None
    if file:
        try:
            file_data = await file.read()
            logger.info(f"📎 File uploaded: {file.filename} ({len(file_data)} bytes)")
            
            # Import file processor
            from .file_processor import file_processor, initialize_file_processor
            if not file_processor:
                from .voice_service import voice_service
                openai_client = None
                openai_key = os.environ.get("OPENAI_API_KEY")
                if openai_key:
                    try:
                        from openai import OpenAI
                        openai_client = OpenAI(api_key=openai_key)
                        logger.info("✓ OpenAI client initialized for file processing")
                    except Exception as e:
                        logger.warning(f"⚠️ OpenAI client failed: {e}")
                initialize_file_processor(openai_client, voice_service)
                logger.info("✓ File processor initialized")
            
            extracted_text, file_type = await file_processor.process_file(file_data, file.filename)
            file_content = f"\n\n{extracted_text}"
            logger.info(f"✓ File processed ({file_type}): {len(extracted_text)} chars extracted")
        except ValueError as e:
            # Unsupported file type
            logger.warning(f"⚠️ Unsupported file type: {e}")
            file_content = f"\n\n[File uploaded: {file.filename} - unsupported format]"
        except Exception as e:
            logger.error(f"❌ File processing error: {e}", exc_info=True)
            file_content = f"\n\n[File upload failed: {str(e)}]"
    
    # Combine message with file content
    full_message = message + (file_content or "")
    
    # Check if user is authenticated (optional)
    if authorization:
        try:
            token = get_token_from_header(authorization)
            session = await state_manager.get_session(token)
            
            if session:
                # Authenticated user - has history, can save conversations
                session_id = session["session_id"]
                user_id = session["user_id"]
                conv_id = conversation_id or str(uuid.uuid4())
                conversation_history = await state_manager.get_conversation_history(session_id)
            else:
                # Invalid session - fall back to guest mode
                session_id = str(uuid.uuid4())
                user_id = "guest"
                conv_id = conversation_id or str(uuid.uuid4())
                conversation_history = []
        except HTTPException:
            # Token validation failed - use guest mode
            session_id = str(uuid.uuid4())
            user_id = "guest"
            conv_id = conversation_id or str(uuid.uuid4())
            conversation_history = []
    else:
        # No token provided - guest mode
        session_id = str(uuid.uuid4())
        user_id = "guest"
        conv_id = conversation_id or str(uuid.uuid4())
        conversation_history = []
    
    # Process message through LangChain agent
    agent_result = await mcp_agent.process_message(
        message=full_message,
        session_id=session_id,
        conversation_history=conversation_history
    )
    
    # Log full result for analytics/debugging
    logger.info(f"🔍 Agent execution: tool_calls={len(agent_result.get('tool_calls', []))}, "
                f"execution_time={agent_result.get('execution_time', 0):.2f}s, "
                f"success={agent_result.get('success', False)}")
    if agent_result.get("tool_calls"):
        logger.debug(f"📋 Tools executed: {[tc.get('tool') for tc in agent_result['tool_calls']]}")
    
    response_text = agent_result.get("response", "I couldn't process that request.")
    
    # Save conversation only for authenticated users
    if user_id != "guest":
        await state_manager.save_conversation_turn(
            session_id, user_id, conv_id, full_message, response_text
        )
    
    return ChatResponse(
        response=response_text,
        conversation_id=conv_id
    )


@app.get("/conversations")
async def get_conversations(authorization: Optional[str] = Header(None)):
    """Get user conversations"""
    token = get_token_from_header(authorization)
    payload = decode_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    # TODO: Retrieve from database
    return {"conversations": []}


@app.get("/")
async def root():
    """Serve full page chat (default view)"""
    return FileResponse(STATIC_DIR / "full-page.html")


@app.get("/chat")
async def chat_page():
    """Serve full page chat"""
    return FileResponse(STATIC_DIR / "full-page.html")


@app.get("/widget")
async def widget_page():
    """Serve embeddable chat widget"""
    return FileResponse(STATIC_DIR / "chat-widget.html")


@app.get("/embed")
async def embed_page():
    """Serve embeddable chat widget (alias)"""
    return FileResponse(STATIC_DIR / "chat-widget.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
