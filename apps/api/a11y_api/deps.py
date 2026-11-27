from fastapi import Depends, HTTPException, Request, status

from .security import Principal, decode_access_token


def _decode(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    p = decode_access_token(token) if scheme.lower() == "bearer" else None
    if p is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return p


def current_principal(request: Request) -> Principal:
    """A signed-in member of an organisation. Super Admins use /admin routes instead."""
    p = _decode(request)
    if p.org_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This endpoint is for organisation members")
    return p


def require_company_admin(p: Principal = Depends(current_principal)) -> Principal:
    if p.role != "COMPANY_ADMIN":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return p


def require_super_admin(request: Request) -> Principal:
    p = _decode(request)
    if p.role != "SUPER_ADMIN":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform administrator access required")
    return p
