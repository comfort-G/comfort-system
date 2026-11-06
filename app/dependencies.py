# app/dependencies.py
from fastapi import Depends, HTTPException, Request, status
from app.database import get_db
from app.security import SESSION_COOKIE_NAME, read_session_token

def get_current_user(request: Request) -> dict:
    """
    Reads the session cookie, queries Neon to verify the user exists,
    ensures the account isn't suspended, and returns the user record.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in."
        )

    try:
        user_id, token_version = read_session_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please log in again.",
        ) from exc
    
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                id,
                member_id,
                full_name,
                email,
                phone,
                address,
                occupation,
                date_of_birth,
                next_of_kin_name,
                next_of_kin_relationship,
                next_of_kin_phone,
                avatar_url,
                avatar_public_id,
                role,
                status,
                override_status,
                must_change_password
            FROM public.members
            WHERE id = %s
              AND token_version = %s;
            """,
            (user_id, token_version)
        )
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or session expired."
            )
            
        if (user.get("status") or "").strip().casefold() == "suspended":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is suspended. Please contact an executive for assistance."
            )

        allowed_during_password_setup = {
            "/api/profile/settings",
            "/api/profile/me",
            "/api/profile/photo",
            "/api/profile/password",
            "/api/auth/me",
        }
        if (
            user.get("must_change_password")
            and request.url.path not in allowed_during_password_setup
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Change your temporary password before accessing the portal.",
            )
            
        return user

def require_role(allowed_roles: list[str]):
    """
    Dependency factory that checks if the currently logged-in user 
    has one of the allowed administrative or member roles.
    """
    def role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        user_role = current_user.get("role", "").lower()
        normalized_allowed = [r.lower() for r in allowed_roles]
        
        if user_role not in normalized_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires one of these roles: {allowed_roles}"
            )
        return current_user
    return role_checker