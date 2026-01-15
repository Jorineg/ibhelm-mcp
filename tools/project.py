"""
Project summary and dashboard tools.
"""

import logging
from pydantic import Field
from mcp.server.fastmcp import Context

from database import get_pool, execute_query, set_user_context, _set_rls_context

logger = logging.getLogger("ibhelm.mcp.tools")


def _extract_user_email(ctx: Context | None) -> str | None:
    """Extract user email from MCP context."""
    if not ctx:
        return None
    try:
        if hasattr(ctx, 'access_token') and ctx.access_token:
            claims = getattr(ctx.access_token, 'claims', {}) or {}
            return claims.get('email')
        if hasattr(ctx, 'request_context') and ctx.request_context:
            access_token = getattr(ctx.request_context, 'access_token', None)
            if access_token:
                claims = getattr(access_token, 'claims', {}) or {}
                return claims.get('email')
    except Exception:
        pass
    return None


def register_project_tools(mcp):
    """Register project-related tools."""
    
    @mcp.tool()
    async def get_project_summary(
        project_id: int | None = Field(default=None, description="Project ID (integer)"),
        project_name: str | None = Field(default=None, description="Project name (case-insensitive partial match)"),
        ctx: Context = None
    ) -> dict:
        """Get project summary with task statistics.

Returns:
    Project info with task counts by status, overdue count, and recent activity
        """
        user_email = _extract_user_email(ctx)
        if user_email:
            set_user_context(user_email)
        logger.info(f"get_project_summary (user={user_email}): id={project_id}, name={project_name}")
        if not project_id and not project_name:
            return {"error": "Provide either project_id or project_name"}
        
        if project_id:
            cond = f"p.id = {int(project_id)}"
        else:
            cond = f"p.name ILIKE '%{project_name.replace(chr(39), chr(39)*2)}%'"
        
        query = f"""
        SELECT p.id, p.name, p.description, p.status, p.start_date, p.end_date, p.created_at,
               COUNT(t.id) as total_tasks,
               COUNT(CASE WHEN t.status = 'completed' THEN 1 END) as completed,
               COUNT(CASE WHEN t.status = 'new' THEN 1 END) as new_tasks,
               COUNT(CASE WHEN t.status NOT IN ('completed', 'new') THEN 1 END) as in_progress,
               COUNT(CASE WHEN t.due_date < NOW() AND t.status != 'completed' THEN 1 END) as overdue,
               MAX(t.updated_at) as last_activity
        FROM teamwork.projects p
        LEFT JOIN teamwork.tasks t ON p.id = t.project_id
        WHERE {cond}
        GROUP BY p.id ORDER BY p.name LIMIT 10
        """
        return await execute_query(query)

    @mcp.tool()
    async def get_project_dashboard(
        project_id: int | None = Field(default=None, description="Project ID (integer)"),
        project_name: str | None = Field(default=None, description="Project name (case-insensitive partial match)"),
        ctx: Context = None
    ) -> dict:
        """Get comprehensive project dashboard with recent activity across all sources.

Returns:
    - project: Basic project info and task counts
    - recent_activity: Last 10 activities (tasks, emails, files combined)
    - recent_tasks: Last 5 task updates with status
    - recent_emails: Last 5 emails from project conversations
    - recent_files: Last 5 files linked to project
    - contacts: Key people involved
        """
        user_email = _extract_user_email(ctx)
        if user_email:
            set_user_context(user_email)
        logger.info(f"get_project_dashboard (user={user_email}): id={project_id}, name={project_name}")
        if not project_id and not project_name:
            return {"error": "Provide either project_id or project_name"}
        
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Set RLS context for email visibility
            await _set_rls_context(conn, user_email)
            # Find project
            if project_id:
                proj = await conn.fetchrow("SELECT id, name FROM teamwork.projects WHERE id = $1", project_id)
            else:
                proj = await conn.fetchrow(
                    "SELECT id, name FROM teamwork.projects WHERE name ILIKE $1 LIMIT 1",
                    f"%{project_name}%"
                )
            
            if not proj:
                return {"error": f"Project not found: {project_name or project_id}"}
            
            pid, pname = proj['id'], proj['name']
            
            # Task stats
            stats = await conn.fetchrow("""
                SELECT COUNT(*) as total,
                       COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                       COUNT(CASE WHEN status = 'new' THEN 1 END) as new,
                       COUNT(CASE WHEN status NOT IN ('completed','new') THEN 1 END) as in_progress,
                       COUNT(CASE WHEN due_date < NOW() AND status != 'completed' THEN 1 END) as overdue
                FROM teamwork.tasks WHERE project_id = $1
            """, pid)
            
            # Recent tasks
            tasks = await conn.fetch("""
                SELECT id, name, status, priority, due_date, updated_at
                FROM teamwork.tasks 
                WHERE project_id = $1 AND status != 'completed'
                ORDER BY updated_at DESC LIMIT 5
            """, pid)
            
            # Recent emails
            emails = await conn.fetch("""
                SELECT m.id, m.subject, m.preview, m.delivered_at, c.name as from_name
                FROM missive.messages m
                JOIN public.project_conversations pc ON m.conversation_id = pc.m_conversation_id
                LEFT JOIN missive.contacts c ON m.from_contact_id = c.id
                WHERE pc.tw_project_id = $1
                ORDER BY m.delivered_at DESC LIMIT 5
            """, pid)
            
            # Recent files
            files = await conn.fetch("""
                SELECT f.id, f.full_path, fc.storage_path, f.db_created_at
                FROM public.files f
                JOIN public.file_contents fc ON f.content_hash = fc.content_hash
                WHERE f.project_id = $1 AND f.deleted_at IS NULL
                ORDER BY f.db_created_at DESC LIMIT 5
            """, pid)
            
            # Key contacts
            contacts = await conn.fetch("""
                SELECT c.name, c.email, COUNT(*) as msg_count
                FROM missive.messages m
                JOIN public.project_conversations pc ON m.conversation_id = pc.m_conversation_id
                JOIN missive.contacts c ON m.from_contact_id = c.id
                WHERE pc.tw_project_id = $1 AND c.email NOT LIKE '%@ibhelm.de'
                GROUP BY c.name, c.email
                ORDER BY msg_count DESC LIMIT 5
            """, pid)
            
            # Combined recent activity
            activity = await conn.fetch("""
                WITH combined AS (
                    SELECT 'task' as type, name as title, updated_at as ts FROM teamwork.tasks WHERE project_id = $1
                    UNION ALL
                    SELECT 'email', m.subject, m.delivered_at
                    FROM missive.messages m
                    JOIN public.project_conversations pc ON m.conversation_id = pc.m_conversation_id
                    WHERE pc.tw_project_id = $1
                    UNION ALL
                    SELECT 'file', f.full_path, f.db_created_at
                    FROM public.files f
                    WHERE f.project_id = $1 AND f.deleted_at IS NULL
                )
                SELECT DISTINCT ON (DATE_TRUNC('hour', ts), type, LEFT(title, 50)) 
                       type, title, ts
                FROM combined WHERE ts IS NOT NULL
                ORDER BY DATE_TRUNC('hour', ts) DESC, type, LEFT(title, 50), ts DESC
                LIMIT 10
            """, pid)
            
            def to_dict(row):
                d = dict(row)
                for k, v in d.items():
                    if hasattr(v, 'isoformat'):
                        d[k] = v.isoformat()
                return d
            
            return {
                "project": {"id": pid, "name": pname, "tasks": dict(stats)},
                "recent_activity": [to_dict(r) for r in activity],
                "recent_tasks": [to_dict(r) for r in tasks],
                "recent_emails": [to_dict(r) for r in emails],
                "recent_files": [to_dict(r) for r in files],
                "key_contacts": [to_dict(r) for r in contacts],
            }

