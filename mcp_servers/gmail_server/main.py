"""Gmail MCP Server - Google Gmail Integration"""

import sys
import os
import base64
import asyncio
from email.mime.text import MIMEText

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_servers.base_server import BaseMCPServer
from typing import Any, Dict, List
from datetime import datetime
from pydantic_settings import BaseSettings

# Google Gmail API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request


class GmailSettings(BaseSettings):
    # ...existing fields...
    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore"
    }


class GmailMCPServer(BaseMCPServer):
    """MCP Server for Gmail operations"""

    def __init__(self):
        super().__init__(
            name="Gmail Server",
            description="Gmail integration via MCP"
        )
        self.service = None  # Gmail service (placeholder)
        self._scopes = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]
        self._token_path = os.path.join(os.path.dirname(__file__), "token.json")
        self._creds_path = os.path.join(os.path.dirname(__file__), "credentials.json")
        self._auth_flow = None
        self._auth_state = None
        
        # Register OAuth authorization endpoint
        @self.app.get("/auth")
        async def auth_endpoint():
            """Start OAuth flow"""
            from fastapi.responses import HTMLResponse
            
            if not os.path.exists(self._creds_path):
                return HTMLResponse("""
                <html>
                    <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                        <h1>✗ Missing credentials.json</h1>
                        <p>Gmail credentials file not found.</p>
                    </body>
                </html>
                """)
            
            # Create Flow for web-based OAuth
            flow = Flow.from_client_secrets_file(
                self._creds_path,
                scopes=self._scopes,
                redirect_uri="http://localhost:8002/callback"
            )
            
            # Generate authorization URL
            auth_url, state = flow.authorization_url(
                prompt="consent",
                access_type="offline"
            )
            
            # Store flow for callback handler
            self._auth_flow = flow
            self._auth_state = state
            
            return HTMLResponse(f"""
            <html>
                <head>
                    <title>Gmail Authorization</title>
                </head>
                <body style="text-align: center; padding: 50px; font-family: Arial;">
                    <h1>Gmail Authorization</h1>
                    <p>Click the button below to authorize Gmail access</p>
                    <a href="{auth_url}" style="
                        display: inline-block;
                        padding: 15px 30px;
                        background-color: #4285f4;
                        color: white;
                        text-decoration: none;
                        border-radius: 5px;
                        font-size: 16px;
                        margin-top: 20px;
                    ">Authorize with Google</a>
                </body>
            </html>
            """)
        
        # Register OAuth callback endpoint
        @self.app.get("/callback")
        async def oauth_callback(code: str = None, state: str = None, error: str = None):
            """Handle OAuth callback from Google"""
            from fastapi import HTTPException
            from fastapi.responses import HTMLResponse
            
            if error:
                return HTMLResponse(f"""
                <html>
                    <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                        <h1>✗ Authorization Denied</h1>
                        <p>Error: {error}</p>
                    </body>
                </html>
                """)
            
            if not code:
                raise HTTPException(status_code=400, detail="Missing authorization code")
            
            if not self._auth_flow:
                raise HTTPException(status_code=400, detail="No pending authorization flow")
            
            try:
                # Exchange code for token
                self._auth_flow.fetch_token(code=code)
                creds = self._auth_flow.credentials
                
                # Save token to file
                with open(self._token_path, "w") as token_file:
                    token_file.write(creds.to_json())
                
                # Reset service to force reload with new credentials
                self.service = None
                self._auth_flow = None
                self._auth_state = None
                
                return HTMLResponse("""
                <html>
                    <body style="text-align: center; padding: 50px; font-family: Arial;">
                        <h1 style="color: green;">✓ Authorization Successful</h1>
                        <p>Gmail is now connected.</p>
                        <p>You can close this window and return to your application.</p>
                    </body>
                </html>
                """)
            except Exception as e:
                return HTMLResponse(f"""
                <html>
                    <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                        <h1>✗ Authorization Failed</h1>
                        <p>Error: {str(e)}</p>
                        <p>Please try again.</p>
                    </body>
                </html>
                """)

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Return available Gmail tools"""
        return [
            {
                "name": "get_emails",
                "description": "Get recent emails",
                "params": {
                    "limit": {"type": "int", "description": "Number of emails to fetch", "default": 10},
                    "query": {"type": "string", "description": "Search query", "required": False}
                }
            },
            {
                "name": "send_email",
                "description": "Send an email",
                "params": {
                    "to": {"type": "string", "required": True},
                    "subject": {"type": "string", "required": True},
                    "body": {"type": "string", "required": True},
                    "cc": {"type": "string", "required": False},
                    "bcc": {"type": "string", "required": False}
                }
            },
            {
                "name": "read_email",
                "description": "Read full email content",
                "params": {
                    "email_id": {"type": "string", "required": True}
                }
            }
        ]

    async def _get_gmail_service(self):
        """Return an authenticated Gmail service instance"""
        if self.service is not None:
            return self.service

        service = await asyncio.to_thread(self._build_gmail_service)
        if service is None:
            # OAuth is pending - return None so caller can handle
            return None
        self.service = service
        return service

    def _build_gmail_service(self):
        creds = self._load_credentials()
        if creds is None:
            # OAuth is pending, return None to signal we need to wait
            return None
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _load_credentials(self):
        """Load OAuth credentials or trigger flow if needed"""
        creds = None
        if os.path.exists(self._token_path):
            creds = Credentials.from_authorized_user_file(self._token_path, self._scopes)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        if not creds or not creds.valid:
            if not os.path.exists(self._creds_path):
                raise RuntimeError(
                    "Missing credentials.json. Provide Google OAuth credentials in mcp_servers/gmail_server/credentials.json."
                )
            
            # Create Flow for web-based OAuth
            flow = Flow.from_client_secrets_file(
                self._creds_path,
                scopes=self._scopes,
                redirect_uri="http://localhost:8002/callback"
            )
            
            # Generate authorization URL
            auth_url, state = flow.authorization_url(
                prompt="consent",
                access_type="offline"
            )
            
            # Store flow for callback handler
            self._auth_flow = flow
            self._auth_state = state
            
            print("================ GMAIL AUTH REQUIRED ================", flush=True)
            print("Open this URL in your browser to authorize access:", flush=True)
            print(auth_url, flush=True)
            print("================ Waiting for OAuth callback ================", flush=True)
            
            # Return None to signal OAuth is pending
            return None

        return creds

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Execute Gmail tool"""
        if tool_name == "get_emails":
            return await self._get_emails(params)
        elif tool_name == "send_email":
            return await self._send_email(params)
        elif tool_name == "read_email":
            return await self._read_email(params)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    async def _get_emails(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get recent emails"""
        limit = params.get("limit", 10)
        query = params.get("query", "")
        
        try:
            service = await self._get_gmail_service()
            if service is None:
                return {
                    "status": "pending_auth",
                    "message": "Gmail authorization pending. Check gmail server logs for OAuth URL."
                }
            
            def fetch():
                return service.users().messages().list(
                    userId="me",
                    q=query,
                    maxResults=limit
                ).execute()
            
            result = await asyncio.to_thread(fetch)
            messages = result.get("messages", [])
            
            # Fetch full details for each message
            emails = []
            for msg in messages[:limit]:
                try:
                    def get_msg():
                        return service.users().messages().get(
                            userId="me",
                            id=msg["id"],
                            format="metadata",
                            metadataHeaders=["From", "Subject", "Date"]
                        ).execute()
                    
                    msg_detail = await asyncio.to_thread(get_msg)
                    headers = {h["name"]: h["value"] for h in msg_detail["payload"].get("headers", [])}
                    
                    emails.append({
                        "id": msg["id"],
                        "from": headers.get("From", "Unknown"),
                        "subject": headers.get("Subject", "(No Subject)"),
                        "timestamp": headers.get("Date", datetime.utcnow().isoformat())
                    })
                except Exception:
                    continue
            
            return {
                "status": "success",
                "emails": emails,
                "count": len(emails)
            }
        except HttpError as error:
            return {"status": "error", "error": f"Gmail API error: {error}"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
        return {
            "status": "success",
            "emails": emails[:limit],
            "count": len(emails)
        }

    async def _send_email(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send email via Gmail"""
        required_fields = ["to", "subject", "body"]
        for field in required_fields:
            if field not in params:
                return {
                    "status": "error",
                    "error": f"Missing required field: {field}"
                }
        
        try:
            service = await self._get_gmail_service()
            if service is None:
                return {
                    "status": "pending_auth",
                    "message": "Gmail authorization pending. Check gmail server logs for OAuth URL."
                }
            
            # Build email message
            message = MIMEText(params.get("body", ""))
            message["to"] = params.get("to")
            message["subject"] = params.get("subject")
            
            if params.get("cc"):
                message["cc"] = params.get("cc")
            if params.get("bcc"):
                message["bcc"] = params.get("bcc")
            
            # Encode for API
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            
            def send():
                return service.users().messages().send(
                    userId="me",
                    body={"raw": raw_message}
                ).execute()
            
            result = await asyncio.to_thread(send)
            return {
                "status": "success",
                "message": f"Email sent successfully to {params['to']}",
                "message_id": result.get("id"),
                "timestamp": datetime.utcnow().isoformat()
            }
        except HttpError as error:
            return {"status": "error", "error": f"Gmail API error: {error}"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def _read_email(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Read full email"""
        email_id = params.get("email_id")
        if not email_id:
            return {
                "status": "error",
                "error": "Missing email_id"
            }
        
        try:
            service = await self._get_gmail_service()
            if service is None:
                return {
                    "status": "pending_auth",
                    "message": "Gmail authorization pending. Check gmail server logs for OAuth URL."
                }
            
            def fetch():
                return service.users().messages().get(
                    userId="me",
                    id=email_id,
                    format="full"
                ).execute()
            
            msg = await asyncio.to_thread(fetch)
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            
            # Extract body
            body = ""
            if "parts" in msg["payload"]:
                for part in msg["payload"]["parts"]:
                    if part["mimeType"] == "text/plain":
                        data = part["body"].get("data", "")
                        if data:
                            body = base64.urlsafe_b64decode(data).decode()
                        break
            else:
                data = msg["payload"]["body"].get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode()
            
            return {
                "status": "success",
                "email": {
                    "id": email_id,
                    "from": headers.get("From", "Unknown"),
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", "(No Subject)"),
                    "body": body,
                    "timestamp": headers.get("Date", datetime.utcnow().isoformat())
                }
            }
        except HttpError as error:
            return {"status": "error", "error": f"Gmail API error: {error}"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}


# Create server instance
gmail_server = GmailMCPServer()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(gmail_server.app, host="0.0.0.0", port=8002)

# Expose FastAPI app instance for Uvicorn
app = gmail_server.app
