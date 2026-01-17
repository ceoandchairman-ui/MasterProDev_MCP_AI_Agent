"""FastAPI server for MCP Host"""

from fastapi import FastAPI, HTTPException, Depends, status, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.openapi.utils import get_openapi
from slowapi import Limiter
from slowapi.util import get_remote_address
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from pydantic_settings import BaseSettings
import logging
import uuid
import httpx
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
async def login_page():
    """Login page to access API documentation"""
    return FileResponse(str(STATIC_DIR / "login-docs.html"))


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
        return FileResponse(content=response.content, media_type="text/html")
    except Exception as e:
        logger.error(f"❌ Calendar auth proxy error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Calendar auth failed: {str(e)}")


@app.get("/integrations/google/calendar/callback")
async def calendar_callback_proxy(code: str = None, state: str = None, error: str = None):
    """Proxy calendar OAuth callback - passes code to calendar-server"""
    if error:
        return FileResponse(
            content=f"""
            <html>
                <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                    <h1>✗ Authorization Denied</h1>
                    <p>Error: {error}</p>
                </body>
            </html>
            """.encode(),
            media_type="text/html"
        )
    
    try:
        logger.info(f"📅 Calendar callback: code={code[:10] if code else 'None'}...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.CALENDAR_SERVER_URL}/callback",
                params={"code": code, "state": state}
            )
        logger.info(f"📅 Calendar callback processed, status={response.status_code}")
        return FileResponse(content=response.content, media_type="text/html")
    except Exception as e:
        logger.error(f"❌ Calendar callback proxy error: {e}", exc_info=True)
        return FileResponse(
            content=f"""
            <html>
                <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                    <h1>✗ Authorization Failed</h1>
                    <p>Error: {str(e)}</p>
                </body>
            </html>
            """.encode(),
            media_type="text/html"
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
        return FileResponse(content=response.content, media_type="text/html")
    except Exception as e:
        logger.error(f"❌ Gmail auth proxy error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Gmail auth failed: {str(e)}")


@app.get("/integrations/google/gmail/callback")
async def gmail_callback_proxy(code: str = None, state: str = None, error: str = None):
    """Proxy Gmail OAuth callback - passes code to gmail-server"""
    if error:
        return FileResponse(
            content=f"""
            <html>
                <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                    <h1>✗ Authorization Denied</h1>
                    <p>Error: {error}</p>
                </body>
            </html>
            """.encode(),
            media_type="text/html"
        )
    
    try:
        logger.info(f"📧 Gmail callback: code={code[:10] if code else 'None'}...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.GMAIL_SERVER_URL}/callback",
                params={"code": code, "state": state}
            )
        logger.info(f"📧 Gmail callback processed, status={response.status_code}")
        return FileResponse(content=response.content, media_type="text/html")
    except Exception as e:
        logger.error(f"❌ Gmail callback proxy error: {e}", exc_info=True)
        logger.error(f"Gmail callback proxy error: {e}")
        return FileResponse(
            content=f"""
            <html>
                <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                    <h1>✗ Authorization Failed</h1>
                    <p>Error: {str(e)}</p>
                </body>
            </html>
            """.encode(),
            media_type="text/html"
        )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, authorization: Optional[str] = Header(None)):
    """Chat endpoint - PUBLIC - guests allowed, authentication optional for features"""
    
    # Check if user is authenticated (optional)
    if authorization:
        try:
            token = get_token_from_header(authorization)
            session = await state_manager.get_session(token)
            
            if session:
                # Authenticated user - has history, can save conversations
                session_id = session["session_id"]
                user_id = session["user_id"]
                conversation_id = request.conversation_id or str(uuid.uuid4())
                conversation_history = await state_manager.get_conversation_history(session_id)
            else:
                # Invalid session - fall back to guest mode
                session_id = str(uuid.uuid4())
                user_id = "guest"
                conversation_id = request.conversation_id or str(uuid.uuid4())
                conversation_history = []
        except HTTPException:
            # Token validation failed - use guest mode
            session_id = str(uuid.uuid4())
            user_id = "guest"
            conversation_id = request.conversation_id or str(uuid.uuid4())
            conversation_history = []
    else:
        # No token provided - guest mode
        session_id = str(uuid.uuid4())
        user_id = "guest"
        conversation_id = request.conversation_id or str(uuid.uuid4())
        conversation_history = []
    
    # Process message through LangChain agent
    agent_result = await mcp_agent.process_message(
        message=request.message,
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
            session_id, user_id, conversation_id, request.message, response_text
        )
    
    return ChatResponse(
        response=response_text,
        conversation_id=conversation_id
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
    """Serve public chat page for guests"""
    chat_path = STATIC_DIR / "chat-embed.html"
    return FileResponse(chat_path)


@app.get("/chat")
async def chat_page():
    """Serve authenticated chat page"""
    embed_path = STATIC_DIR / "chat-embed.html"
    return FileResponse(embed_path)


@app.get("/chat-embed")
async def chat_embed():
    """Serve chat embed page (legacy)"""
    embed_path = STATIC_DIR / "chat-embed.html"
    return FileResponse(embed_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
