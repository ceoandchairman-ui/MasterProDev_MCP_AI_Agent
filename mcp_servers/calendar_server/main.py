"""Calendar MCP Server - Google Calendar Integration"""


import asyncio
import os
import json
from typing import Any, Dict, List
from datetime import datetime, timedelta
from mcp_servers.base_server import BaseMCPServer
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

# Google Calendar API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

from mcp_servers.calendar_server.config import calendar_settings


class CalendarMCPServer(BaseMCPServer):
    """MCP Server for Google Calendar operations"""

    def __init__(self):
        super().__init__(
            name="Calendar Server",
            description="Google Calendar integration via MCP"
        )
        self.service = None  # Lazily initialized Calendar service
        self._scopes = ["https://www.googleapis.com/auth/calendar"]
        self._token_path = os.path.join(os.path.dirname(__file__), "token.json")
        self._creds_path = os.path.join(os.path.dirname(__file__), "credentials.json")
        self._auth_flow = None  # Store flow for callback
        self._auth_state = None  # Store state for callback
        
        # Register OAuth callback endpoint
        @self.app.get("/callback")
        async def oauth_callback(code: str = None, state: str = None, error: str = None):
            """Handle OAuth callback from Google"""
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
                        <p>Google Calendar is now connected.</p>
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
        
        # Register OAuth login endpoint
        @self.app.get("/auth")
        async def start_auth():
            """Start OAuth flow and return authorization URL"""
            try:
                flow = Flow.from_client_secrets_file(
                    self._creds_path,
                    scopes=self._scopes,
                    redirect_uri="http://localhost:8001/callback"
                )
                
                auth_url, state = flow.authorization_url(prompt='consent')
                
                # Store flow for later use in callback
                self._auth_flow = flow
                self._auth_state = state
                
                return HTMLResponse(f"""
                <html>
                    <head>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                                max-width: 600px;
                                margin: 50px auto;
                                padding: 20px;
                                background: #f5f5f5;
                            }}
                            .container {{
                                background: white;
                                padding: 30px;
                                border-radius: 8px;
                                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                            }}
                            h1 {{
                                color: #1f2937;
                            }}
                            .auth-link {{
                                display: inline-block;
                                padding: 12px 24px;
                                background: #4285f4;
                                color: white;
                                text-decoration: none;
                                border-radius: 4px;
                                margin-top: 20px;
                            }}
                            .auth-link:hover {{
                                background: #357ae8;
                            }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <h1>🔐 Google Calendar Authorization</h1>
                            <p>Click the button below to authorize access to your Google Calendar:</p>
                            <a href="{auth_url}" class="auth-link">Authorize with Google</a>
                            <p style="margin-top: 20px; color: #666;">You will be redirected back after authorization.</p>
                        </div>
                    </body>
                </html>
                """)
            except Exception as e:
                return HTMLResponse(f"""
                <html>
                    <body style="text-align: center; padding: 50px; font-family: Arial; color: red;">
                        <h1>✗ Authorization Error</h1>
                        <p>Error: {str(e)}</p>
                        <p>Make sure credentials.json exists in the calendar_server directory.</p>
                    </body>
                </html>
                """)

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Return available calendar tools"""
        return [
            {
                "name": "get_events",
                "description": "Get upcoming calendar events",
                "params": {
                    "days": {"type": "int", "description": "Number of days ahead", "default": 7}
                }
            },
            {
                "name": "create_event",
                "description": "Create a new calendar event",
                "params": {
                    "title": {"type": "string", "required": True},
                    "start_time": {"type": "string", "required": True, "format": "ISO8601"},
                    "end_time": {"type": "string", "required": True, "format": "ISO8601"},
                    "description": {"type": "string", "required": False}
                }
            },
            {
                "name": "delete_event",
                "description": "Delete a calendar event",
                "params": {
                    "event_id": {"type": "string", "required": True}
                }
            }
        ]

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Execute calendar tool"""
        if tool_name == "get_events":
            return await self._get_events(params)
        elif tool_name == "create_event":
            return await self._create_event(params)
        elif tool_name == "delete_event":
            return await self._delete_event(params)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    async def _get_calendar_service(self):
        """Return an authenticated Google Calendar service instance"""
        if self.service is not None:
            return self.service

        service = await asyncio.to_thread(self._build_calendar_service)
        if service is None:
            # OAuth is pending - return None so caller can handle
            return None
        self.service = service
        return service

    def _build_calendar_service(self):
        creds = self._load_credentials()
        if creds is None:
            # OAuth is pending, return None to signal we need to wait
            return None
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

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
                    "Missing credentials.json. Provide Google OAuth credentials in mcp_servers/calendar_server/credentials.json."
                )
            
            # Create Flow for web-based OAuth
            flow = Flow.from_client_secrets_file(
                self._creds_path,
                scopes=self._scopes,
                redirect_uri="http://localhost:8001/callback"
            )
            
            # Generate authorization URL
            auth_url, state = flow.authorization_url(
                prompt="consent",
                access_type="offline"
            )
            
            # Store flow for callback handler
            self._auth_flow = flow
            self._auth_state = state
            
            print("================ GOOGLE AUTH REQUIRED ================", flush=True)
            print("Open this URL in your browser to authorize access:", flush=True)
            print(auth_url, flush=True)
            print("================ Waiting for OAuth callback ================", flush=True)
            
            # Return None to signal OAuth is pending - let the callback handler complete
            # The request will be retried after OAuth succeeds
            return None

        return creds

    def _serialize_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Return simplified event payload for the host"""
        start = event.get("start", {})
        end = event.get("end", {})
        return {
            "id": event.get("id"),
            "title": event.get("summary"),
            "description": event.get("description", ""),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "location": event.get("location"),
            "attendees": [att.get("email") for att in event.get("attendees", []) if att.get("email")],
            "htmlLink": event.get("htmlLink"),
        }

    async def _get_events(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get upcoming events"""
        days = params.get("days", 7)
        if days < 1:
            days = 1
        if days > 30:
            days = 30

        try:
            service = await self._get_calendar_service()
            if service is None:
                return {
                    "status": "pending_auth",
                    "message": "Google Calendar authorization pending. Check calendar server logs for OAuth URL."
                }
            
            now = datetime.utcnow().isoformat() + "Z"
            max_time = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"

            def fetch():
                return service.events().list(
                    calendarId="primary",
                    timeMin=now,
                    timeMax=max_time,
                    singleEvents=True,
                    orderBy="startTime"
                ).execute()

            events_result = await asyncio.to_thread(fetch)
            items = events_result.get("items", [])
            events = [self._serialize_event(item) for item in items]

            return {
                "status": "success",
                "events": events,
                "count": len(events)
            }

        except HttpError as error:
            return {"status": "error", "error": f"Google Calendar API error: {error}"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def _create_event(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create new event in Google Calendar"""
        required_fields = ["title", "start_time", "end_time"]
        for field in required_fields:
            if field not in params:
                return {
                    "status": "error",
                    "error": f"Missing required field: {field}"
                }

        try:
            service = await self._get_calendar_service()
            if service is None:
                return {
                    "status": "pending_auth",
                    "message": "Google Calendar authorization pending. Check calendar server logs for OAuth URL."
                }

            def create():
                event_body = {
                    "summary": params["title"],
                    "description": params.get("description", ""),
                    "start": {"dateTime": params["start_time"], "timeZone": "UTC"},
                    "end": {"dateTime": params["end_time"], "timeZone": "UTC"},
                }
                return service.events().insert(calendarId="primary", body=event_body).execute()

            created_event = await asyncio.to_thread(create)
            return {
                "status": "success",
                "message": f"Event '{params['title']}' created in Google Calendar",
                "event": self._serialize_event(created_event)
            }
        except HttpError as error:
            return {"status": "error", "error": f"Google Calendar API error: {error}"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def _delete_event(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete event - FIX 7: Enhanced validation and error handling"""
        event_id = params.get("event_id")
        
        # Enhanced validation
        if not event_id:
            return {
                "status": "error",
                "error": "event_id is required to delete an event",
                "suggestion": "First call get_calendar_events to find the event_id, then delete_calendar_event with that ID"
            }
        
        if event_id == "[REQUIRES_ID_FROM_ABOVE]":
            return {
                "status": "error",
                "error": "Invalid placeholder event_id",
                "suggestion": "The event_id must be obtained from get_calendar_events results first"
            }

        try:
            service = await self._get_calendar_service()
            if service is None:
                return {
                    "status": "pending_auth",
                    "message": "Google Calendar authorization pending. Check calendar server logs for OAuth URL."
                }

            def delete():
                service.events().delete(calendarId="primary", eventId=event_id).execute()

            await asyncio.to_thread(delete)
            return {
                "status": "success",
                "message": f"Event {event_id} deleted successfully"
            }
        except HttpError as error:
            if error.resp.status == 404:
                return {
                    "status": "error",
                    "error": f"Event not found: {event_id}",
                    "suggestion": "The event may have already been deleted or the ID is incorrect"
                }
            return {"status": "error", "error": f"Google Calendar API error: {error}"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}


# Create server instance
calendar_server = CalendarMCPServer()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(calendar_server.app, host="0.0.0.0", port=8001)

app = calendar_server.app
