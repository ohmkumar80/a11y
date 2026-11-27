from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class SignupIn(BaseModel):
    organization_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(max_length=1024)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=1024)


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


class EmailIn(BaseModel):
    email: EmailStr


class ResetConfirmIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=1024)


class InviteIn(BaseModel):
    email: EmailStr
    role: Literal["COMPANY_ADMIN", "STANDARD_USER"] = "STANDARD_USER"


class InviteAcceptIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=1024)


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    organization_id: str
    organization_name: str


class SessionOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
    user: UserOut


class Problem(BaseModel):
    """Error body. ``field`` lets the web UI attach the message to an input (SC 3.3.1)."""

    detail: str
    code: str | None = None
    field: str | None = None
