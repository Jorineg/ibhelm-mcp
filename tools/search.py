"""
Search convenience tools for emails and tasks.
"""

import logging
from pydantic import Field

from database import execute_query

logger = logging.getLogger("ibhelm.mcp.tools")


def register_search_tools(mcp):
    """Register search tools."""
    
    @mcp.tool()
    async def search_emails(
        subject: str | None = Field(default=None, description="Filter by subject (case-insensitive partial match)"),
        from_email: str | None = Field(default=None, description="Filter by sender email (exact match)"),
        has_attachment: bool | None = Field(default=None, description="Filter for messages with/without attachments"),
        min_attachment_size: int | None = Field(default=None, description="Minimum attachment size in bytes (e.g., 40000000 for 40MB)"),
        min_attachments: int | None = Field(default=None, description="Minimum number of attachments"),
        attachment_type: str | None = Field(default=None, description="Filter by attachment type (e.g., 'pdf', 'image', 'xlsx')"),
        label: str | None = Field(default=None, description="Filter by Missive label name"),
        search_text: str | None = Field(default=None, description="Search in subject and body"),
        limit: int = Field(default=50, description="Maximum results (default 50, max 200)")
    ) -> dict:
        """Search email messages with attachment filtering.

Returns:
    Messages with attachment details where applicable
    
Examples:
    - Emails with attachments > 40MB: min_attachment_size=40000000
    - Emails with at least 3 PDFs: min_attachments=3, attachment_type="pdf"
        """
        logger.info(f"search_emails: subject={subject}, from={from_email}, text={search_text}, limit={limit}")
        limit = min(limit, 200)
        conditions = []
        joins = ["FROM missive.messages m", "LEFT JOIN missive.contacts c ON m.from_contact_id = c.id"]
        select_cols = ["m.id", "m.subject", "m.preview", "m.delivered_at", "c.name as from_name"]
        
        if has_attachment is not None or min_attachment_size or min_attachments or attachment_type:
            joins.append("LEFT JOIN missive.attachments a ON m.id = a.message_id")
            select_cols.extend(["COUNT(a.id) as attachment_count", "SUM(a.size) as total_size"])
            if has_attachment is True:
                conditions.append("a.id IS NOT NULL")
            elif has_attachment is False:
                conditions.append("a.id IS NULL")
            if attachment_type:
                safe = attachment_type.replace("'", "''").lower()
                conditions.append(f"(a.extension ILIKE '{safe}' OR a.media_type ILIKE '%{safe}%')")
        
        if label:
            joins.extend(["JOIN missive.conversation_labels cl ON m.conversation_id = cl.conversation_id",
                          "JOIN missive.shared_labels sl ON cl.label_id = sl.id"])
            conditions.append(f"sl.name ILIKE '%{label.replace(chr(39), chr(39)*2)}%'")
        
        if subject:
            conditions.append(f"m.subject ILIKE '%{subject.replace(chr(39), chr(39)*2)}%'")
        if from_email:
            conditions.append(f"c.email = '{from_email.replace(chr(39), chr(39)*2)}'")
        if search_text:
            safe = search_text.replace("'", "''")
            conditions.append(f"(m.subject ILIKE '%{safe}%' OR m.body_plain_text ILIKE '%{safe}%')")
        
        where = " AND ".join(conditions) if conditions else "TRUE"
        group_by = "m.id, m.subject, m.preview, m.delivered_at, c.name"
        having = []
        if min_attachment_size:
            having.append(f"SUM(a.size) >= {min_attachment_size}")
        if min_attachments:
            having.append(f"COUNT(a.id) >= {min_attachments}")
        having_clause = f"HAVING {' AND '.join(having)}" if having else ""
        
        query = f"SELECT {', '.join(select_cols)} {' '.join(joins)} WHERE {where} GROUP BY {group_by} {having_clause} ORDER BY m.delivered_at DESC LIMIT {limit}"
        return await execute_query(query)

    @mcp.tool()
    async def search_tasks(
        project_name: str | None = Field(default=None, description="Filter by project name (case-insensitive partial match)"),
        status: str | None = Field(default=None, description="Filter by status (e.g., 'completed', 'new', 'in progress')"),
        assignee_email: str | None = Field(default=None, description="Filter by assignee email"),
        search_text: str | None = Field(default=None, description="Search in task name and description"),
        tag: str | None = Field(default=None, description="Filter by tag name"),
        overdue_only: bool = Field(default=False, description="Only show overdue incomplete tasks"),
        limit: int = Field(default=50, description="Maximum results (default 50, max 200)")
    ) -> dict:
        """Search tasks with various filters.

**Index Tips:** Filter by project_id, status, or assignee for best performance.
        """
        logger.info(f"search_tasks: project={project_name}, status={status}, text={search_text}, limit={limit}")
        limit = min(limit, 200)
        conditions = []
        joins = ["FROM teamwork.tasks t", "LEFT JOIN teamwork.projects p ON t.project_id = p.id",
                 "LEFT JOIN teamwork.task_assignees ta ON t.id = ta.task_id",
                 "LEFT JOIN teamwork.users u ON ta.user_id = u.id"]
        
        if project_name:
            conditions.append(f"p.name ILIKE '%{project_name.replace(chr(39), chr(39)*2)}%'")
        if status:
            conditions.append(f"t.status = '{status.replace(chr(39), chr(39)*2)}'")
        if assignee_email:
            conditions.append(f"u.email = '{assignee_email.replace(chr(39), chr(39)*2)}'")
        if search_text:
            safe = search_text.replace("'", "''")
            conditions.append(f"(t.name ILIKE '%{safe}%' OR t.description ILIKE '%{safe}%')")
        if tag:
            joins.extend(["JOIN teamwork.task_tags tt ON t.id = tt.task_id", "JOIN teamwork.tags tg ON tt.tag_id = tg.id"])
            conditions.append(f"tg.name ILIKE '%{tag.replace(chr(39), chr(39)*2)}%'")
        if overdue_only:
            conditions.extend(["t.due_date < NOW()", "t.status != 'completed'"])
        
        where = " AND ".join(conditions) if conditions else "TRUE"
        query = f"SELECT DISTINCT t.id, t.name as task_name, t.description, t.status, t.priority, t.due_date, t.created_at, p.name as project_name, u.email as assignee_email {' '.join(joins)} WHERE {where} ORDER BY t.created_at DESC LIMIT {limit}"
        return await execute_query(query)

