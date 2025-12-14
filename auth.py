"""
Authentication for IBHelm MCP Server.
- Supabase GoTrue OAuth integration
- JWT verification for HS256 tokens
"""

import jwt as pyjwt
from pydantic import AnyHttpUrl
from fastmcp.server.auth import OAuthProxy, TokenVerifier, AccessToken

from config import (
    SUPABASE_URL, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, 
    MCP_SERVER_URL, SUPABASE_JWT_SECRET
)


class SupabaseTokenVerifier(TokenVerifier):
    """Verify Supabase HS256 tokens."""
    
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            decoded = pyjwt.decode(
                token, SUPABASE_JWT_SECRET or "", 
                algorithms=["HS256"], audience="authenticated",
                options={"verify_signature": bool(SUPABASE_JWT_SECRET), "verify_iss": False}
            )
            return AccessToken(
                token=token, 
                client_id=decoded.get('sub') or "anon",
                scopes=['mcp:read'], 
                expires_at=decoded.get('exp'),
                resource=f"{MCP_SERVER_URL}/mcp",
                claims={"sub": decoded.get('sub'), "email": decoded.get('email')}
            )
        except Exception:
            return None


class IBHelmOAuthProxy(OAuthProxy):
    """Custom OAuth proxy to fix FastMCP path handling issues."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Fix double /mcp/mcp path issue
        if self._jwt_issuer.audience.endswith('/mcp/mcp'):
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
        token_verifier=SupabaseTokenVerifier(),
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

