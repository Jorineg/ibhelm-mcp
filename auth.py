"""
Authentication for IBHelm MCP Server.
- Supabase GoTrue OAuth integration
- JWT verification for HS256 tokens
- Static bearer token support for direct API access
"""

import logging
import jwt as pyjwt
from pydantic import AnyHttpUrl
from fastmcp.server.auth import OAuthProxy, TokenVerifier, AccessToken

from config import (
    SUPABASE_URL, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, 
    MCP_SERVER_URL, SUPABASE_JWT_SECRET, MCP_BEARER_TOKENS
)

logger = logging.getLogger("ibhelm.mcp.auth")


def parse_bearer_tokens(tokens_str: str) -> dict[str, dict]:
    """Parse MCP_BEARER_TOKENS env var into {token: {client_id, email}} dict.
    Format: token1:client_id1:email1,token2:client_id2:email2
    Email is optional, defaults to client_id@api.local
    """
    if not tokens_str:
        return {}
    result = {}
    for entry in tokens_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 2)
        token = parts[0].strip()
        client_id = parts[1].strip() if len(parts) > 1 else "api-client"
        email = parts[2].strip() if len(parts) > 2 else f"{client_id}@api.local"
        result[token] = {"client_id": client_id, "email": email}
    return result


class HybridTokenVerifier(TokenVerifier):
    """Verify both static bearer tokens and Supabase HS256 JWTs."""
    
    def __init__(self):
        self.static_tokens = parse_bearer_tokens(MCP_BEARER_TOKENS)
        self.required_scopes: list[str] = []  # Required by OAuthProxy
        if self.static_tokens:
            logger.info(f"Loaded {len(self.static_tokens)} static bearer token(s)")
    
    async def verify_token(self, token: str) -> AccessToken | None:
        token_preview = f"{token[:20]}..." if len(token) > 20 else token
        logger.debug(f"Verifying token: {token_preview}")
        
        # Check static bearer tokens first
        if token in self.static_tokens:
            info = self.static_tokens[token]
            client_id = info["client_id"]
            email = info["email"]
            logger.info(f"Static token verified: client_id={client_id} email={email}")
            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=['mcp:read'],
                expires_at=None,
                resource=f"{MCP_SERVER_URL}/mcp",
                claims={"client_id": client_id, "email": email, "sub": client_id, "type": "bearer"}
            )
        
        # Fall back to Supabase JWT verification
        try:
            decoded = pyjwt.decode(
                token, SUPABASE_JWT_SECRET or "", 
                algorithms=["HS256"], audience="authenticated",
                options={"verify_signature": bool(SUPABASE_JWT_SECRET), "verify_iss": False}
            )
            email = decoded.get('email', 'unknown')
            sub = decoded.get('sub', 'unknown')
            logger.info(f"JWT verified: user={email} sub={sub}")
            return AccessToken(
                token=token, 
                client_id=decoded.get('sub') or "anon",
                scopes=['mcp:read'], 
                expires_at=decoded.get('exp'),
                resource=f"{MCP_SERVER_URL}/mcp",
                claims={"sub": decoded.get('sub'), "email": decoded.get('email')}
            )
        except pyjwt.ExpiredSignatureError:
            logger.warning(f"Token expired: {token_preview}")
            return None
        except pyjwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            return None


class IBHelmOAuthProxy(OAuthProxy):
    """Custom OAuth proxy to fix FastMCP path handling issues."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Fix double /mcp/mcp path issue
        if self._jwt_issuer and self._jwt_issuer.audience.endswith('/mcp/mcp'):
            from fastmcp.server.auth.jwt_issuer import JWTIssuer
            self._jwt_issuer = JWTIssuer(
                issuer=self._jwt_issuer.issuer,
                audience=self._jwt_issuer.audience.replace('/mcp/mcp', '/mcp'),
                signing_key=self._jwt_issuer._signing_key,
            )
    
    def _get_resource_url(self, path: str | None = None) -> AnyHttpUrl | None:
        return self.base_url


def create_auth_provider() -> IBHelmOAuthProxy:
    """Create the OAuth provider for MCP authentication."""
    auth_base = f"{SUPABASE_URL}/auth/v1"
    return IBHelmOAuthProxy(
        upstream_authorization_endpoint=f"{auth_base}/oauth/authorize",
        upstream_token_endpoint=f"{auth_base}/oauth/token",
        upstream_revocation_endpoint=None,
        upstream_client_id=OAUTH_CLIENT_ID,
        upstream_client_secret=OAUTH_CLIENT_SECRET or "placeholder",
        token_verifier=HybridTokenVerifier(),
        base_url=f"{MCP_SERVER_URL}/mcp",
        redirect_path="/auth/callback",
        token_endpoint_auth_method="none",
        # Only email/profile scopes - openid triggers ID token generation which fails with HS256
        valid_scopes=["email", "profile"],
        # Allow all redirect URIs - PKCE provides protection against code interception
        # This enables any MCP client to work (Cursor, Claude Desktop, web tools, etc.)
        allowed_client_redirect_uris=[
            "http://*",                # Any HTTP (localhost, etc.)
            "https://*",               # Any HTTPS
            "*://*",                   # Any custom URI scheme (cursor://, vscode://, claude://, etc.)
        ],
        require_authorization_consent=True,
    )

