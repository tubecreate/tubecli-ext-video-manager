"""
Token Resolver — resolves valid OAuth access tokens from Auth Manager.
Supports lookup by email, credential_id, or auto-detect by provider+scope.

IMPORTANT: Auth Manager uses token_id (not credential_id) in get_active_token().
list_tokens() returns keys: token_id, credential_id, authorized_email, scopes (short names), status, has_refresh
"""
import logging
from typing import Optional

logger = logging.getLogger("VideoManager.TokenResolver")


def _get_auth_manager():
    """Lazy import Auth Manager singleton."""
    try:
        from tubecli.extensions.auth_manager.extension import auth_manager
        return auth_manager
    except ImportError:
        try:
            import sys, os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "tubecli"))
            from tubecli.extensions.auth_manager.extension import auth_manager
            return auth_manager
        except ImportError:
            logger.error("Auth Manager not available — cannot resolve token")
            return None


def resolve_token(
    email: str = "",
    cred_id: str = "",
    provider: str = "google",
    required_scope_keyword: str = "youtube",
    strict: bool = False,  # If True + cred_id given: don't fallback to other accounts
) -> Optional[str]:
    """
    Get an active access token from Auth Manager.

    scopes in list_tokens() are short names: 'youtube', 'youtube_upload', 'calendar', etc.

    Priority:
    1. token_id / cred_id match  (strict=True stops here if cred_id provided)
    2. email match among tokens for that provider
    3. scope keyword auto-detect (e.g. 'youtube' in scopes list)
    4. fallback: any active/expired-with-refresh token for provider
    """
    am = _get_auth_manager()
    if not am:
        return None

    all_tokens = am.list_tokens(provider=provider)

    if not all_tokens:
        logger.warning(f"No tokens found for provider='{provider}'")
        return None

    # 1. Exact cred_id match — find the token_id for this credential
    if cred_id:
        for t in all_tokens:
            if t.get("credential_id") == cred_id or t.get("token_id") == cred_id:
                tok = am.get_active_token(t["token_id"])
                if tok:
                    return tok
        logger.warning(f"No active token for cred_id='{cred_id}'")
        # IMPORTANT: when a specific account was requested but is not active,
        # do NOT silently fall through to another account's token.
        # Return None so the caller can force-refresh or show a clear error.
        if strict or cred_id:
            return None

    # 2. Email match
    if email:
        for t in all_tokens:
            if t.get("authorized_email", "").lower() == email.lower():
                tok = am.get_active_token(t["token_id"])
                if tok:
                    return tok
        logger.warning(f"No active token for email='{email}' on provider='{provider}'")

    # 3. Scope-based auto-detect (scopes are short names like 'youtube', 'youtube_upload')
    if required_scope_keyword:
        # Active tokens first, then expired-with-refresh
        for status_priority in [["active"], ["expired"]]:
            for t in all_tokens:
                if t.get("status") not in status_priority:
                    continue
                scopes = t.get("scopes", [])
                if any(required_scope_keyword in s for s in scopes):
                    tok = am.get_active_token(t["token_id"])
                    if tok:
                        return tok

    # 4. Fallback: any token for provider (active preferred, then expired+refresh)
    for status_priority in [["active"], ["expired"]]:
        for t in all_tokens:
            if t.get("status") not in status_priority:
                continue
            tok = am.get_active_token(t["token_id"])
            if tok:
                return tok

    logger.error(f"No valid token found for provider='{provider}' scope='{required_scope_keyword}'")
    return None


def list_authorized_accounts(provider: str = "google", scope_keyword: str = "youtube") -> list:
    """
    List all authorized accounts that have a token (active or refreshable) for this provider+scope.
    Used by UI to populate account selector dropdown.
    
    scopes in list_tokens() are short names: 'youtube', 'youtube_upload', etc.
    """
    am = _get_auth_manager()
    if not am:
        return []

    accounts = []
    seen_emails = set()
    tokens = am.list_tokens(provider=provider)

    for t in tokens:
        email = t.get("authorized_email", "")
        if not email or email in seen_emails:
            continue

        scopes = t.get("scopes", [])

        # Filter by scope keyword (short name match)
        if scope_keyword and not any(scope_keyword in s for s in scopes):
            continue

        # Only include tokens that are active OR expired-but-refreshable
        status = t.get("status", "")
        if status not in ("active", "expired"):
            continue

        seen_emails.add(email)
        accounts.append({
            "email": email,
            "credential_id": t.get("credential_id", ""),
            "token_id": t.get("token_id", ""),
            "credential_name": t.get("credential_name", ""),
            "status": status,
            "has_refresh": t.get("has_refresh", False),
            "scopes": scopes,
            "authorized_at": t.get("authorized_at", ""),
        })

    return accounts
