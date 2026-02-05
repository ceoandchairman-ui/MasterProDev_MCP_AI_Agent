"""Pydantic models for requests and responses"""

from pydantic import BaseModel
from typing import Optional, List
from enum import Enum
from datetime import datetime


class UserType(str, Enum):
    CUSTOMER = "customer"
    EMPLOYEE = "employee"


class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"


# Request Models
class LoginRequest(BaseModel):
    email: str
    password: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    user_type: UserType


# Response Models
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime


class ChatResponse(BaseModel):
    response: str
    tool_used: Optional[str] = None
    context: Optional[List[str]] = None
    conversation_id: str
    pending_auth: Optional[bool] = False
    auth_url: Optional[str] = None


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class UserProfileResponse(BaseModel):
    id: str
    email: str
    name: str
    user_type: UserType
    role: UserRole


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    services: dict


class ErrorResponse(BaseModel):
    error: str
    status_code: int
    details: Optional[str] = None
