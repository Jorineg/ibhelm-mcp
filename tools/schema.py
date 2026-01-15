"""
Schema exploration tools.
"""

import logging
from pydantic import Field

from config import abbrev_type
from database import get_pool, execute_query

logger = logging.getLogger("ibhelm.mcp.tools")


async def _get_schema_internal(schema: str | None = None, table: str | None = None, compact: bool = True) -> dict:
    """Internal schema retrieval - called by both get_schema tool and describe_table."""
    valid_schemas = ('public', 'teamwork', 'missive')
    if schema and schema not in valid_schemas:
        return {"error": f"❌ Invalid schema: '{schema}'\n\n💡 Valid schemas: {', '.join(valid_schemas)}"}
    
    if table and not table.replace('_', '').isalnum():
        return {"error": f"❌ Invalid table name: '{table}'\n\n💡 Table names can only contain letters, numbers, and underscores."}
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        conditions = ["t.table_schema IN ('public', 'teamwork', 'missive')"]
        if schema:
            conditions.append(f"t.table_schema = '{schema}'")
        if table:
            conditions.append(f"t.table_name = '{table}'")
        
        where = " AND ".join(conditions)
        
        # Get columns
        cols_query = f"""
        SELECT t.table_schema, t.table_name, c.column_name, c.data_type, c.udt_name,
               c.is_nullable, c.character_maximum_length
        FROM information_schema.tables t
        JOIN information_schema.columns c ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE {where} AND t.table_type IN ('BASE TABLE', 'VIEW')
        ORDER BY t.table_schema, t.table_name, c.ordinal_position
        """
        columns = await conn.fetch(cols_query)
        
        # Get PKs
        pk_query = f"""
        SELECT tc.table_schema, tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY' AND {where.replace('t.', 'tc.')}
        """
        pks = await conn.fetch(pk_query)
        pk_set = {(r['table_schema'], r['table_name'], r['column_name']) for r in pks}
        
        # Get FKs
        fk_query = f"""
        SELECT tc.table_schema, tc.table_name, kcu.column_name, ccu.table_name AS ref_table, ccu.column_name AS ref_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY' AND {where.replace('t.', 'tc.')}
        """
        fks = await conn.fetch(fk_query)
        fk_map = {(r['table_schema'], r['table_name'], r['column_name']): f"{r['ref_table']}.{r['ref_column']}" for r in fks}
        
        # Composite PKs
        cpk_query = f"""
        SELECT tc.table_schema, tc.table_name, array_agg(kcu.column_name ORDER BY kcu.ordinal_position) as pk_columns
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY' AND {where.replace('t.', 'tc.')}
        GROUP BY tc.table_schema, tc.table_name HAVING COUNT(*) > 1
        """
        cpks = await conn.fetch(cpk_query)
        cpk_map = {(r['table_schema'], r['table_name']): r['pk_columns'] for r in cpks}
        
        if compact:
            output = []
            current_schema = current_table = None
            table_cols = []
            
            for col in columns:
                s, t = col['table_schema'], col['table_name']
                
                if s != current_schema:
                    if current_table and table_cols:
                        cpk = cpk_map.get((current_schema, current_table))
                        line = f"**{current_table}**: " + ", ".join(table_cols)
                        if cpk:
                            line += f" [pk: {', '.join(cpk)}]"
                        output.append(line)
                    if current_schema:
                        output.append("")
                    output.append(f"# {s}")
                    output.append("")
                    current_schema, current_table, table_cols = s, None, []
                
                if t != current_table:
                    if current_table and table_cols:
                        cpk = cpk_map.get((current_schema, current_table))
                        line = f"**{current_table}**: " + ", ".join(table_cols)
                        if cpk:
                            line += f" [pk: {', '.join(cpk)}]"
                        output.append(line)
                    current_table, table_cols = t, []
                
                col_name = col['column_name']
                col_type = abbrev_type(col['data_type'], col['udt_name'])
                if col['character_maximum_length']:
                    col_type += f"({col['character_maximum_length']})"
                
                col_str = f"{col_name} {col_type}"
                if (s, t, col_name) in pk_set and (s, t) not in cpk_map:
                    col_str += " pk"
                fk_ref = fk_map.get((s, t, col_name))
                if fk_ref:
                    col_str += f" (→{fk_ref})"
                table_cols.append(col_str)
            
            if current_table and table_cols:
                cpk = cpk_map.get((current_schema, current_table))
                line = f"**{current_table}**: " + ", ".join(table_cols)
                if cpk:
                    line += f" [pk: {', '.join(cpk)}]"
                output.append(line)
            
            return {
                "schema": "\n".join(output),
                "meta": {
                    "tables": len(set((c['table_schema'], c['table_name']) for c in columns)),
                    "columns": len(columns),
                }
            }
        else:
            tables = {}
            for col in columns:
                key = f"{col['table_schema']}.{col['table_name']}"
                if key not in tables:
                    tables[key] = {"schema": col['table_schema'], "table": col['table_name'], "columns": []}
                col_info = {"name": col['column_name'], "type": col['data_type']}
                if (col['table_schema'], col['table_name'], col['column_name']) in pk_set:
                    col_info["pk"] = True
                fk = fk_map.get((col['table_schema'], col['table_name'], col['column_name']))
                if fk:
                    col_info["fk"] = fk
                tables[key]["columns"].append(col_info)
            return {"tables": list(tables.values())}


def register_schema_tools(mcp):
    """Register schema exploration tools."""
    
    @mcp.tool()
    async def get_schema(
        schema: str | None = Field(default=None, description="Filter by schema (public, teamwork, missive). None = all schemas."),
        table: str | None = Field(default=None, description="Filter by specific table. Requires schema to be set."),
        compact: bool = Field(default=True, description="If True, returns minimal TOON-like format. If False, returns full details.")
    ) -> dict:
        """Get database schema in a compact, LLM-friendly format.

Args:
    schema: Filter by schema (public, teamwork, missive). None = all schemas.
    table: Filter by specific table. Requires schema to be set.
    compact: If True, returns minimal TOON-like format. If False, returns full details.

Returns:
    Compact schema with columns, types, PKs, and foreign key references.
    
Format (compact=True):
    **table_name**: col1 type [pk], col2 type (→ref_table.ref_col), ...

Example:
    **tasks**: id int pk, project_id int (→projects.id), name text, status varchar

**Key Views (query these like tables):**
- `unified_items_secure`: Master view combining tasks, emails, files, craft docs (emails filtered by user visibility)
- `project_overview`: Projects with task/file/conversation counts
- `file_details`, `unified_person_details`, `location_hierarchy`

**Useful Functions (call via SELECT):**
- `search_projects_autocomplete(text)` → matching projects
- `search_persons_autocomplete(text)` → matching people  
- `search_locations_autocomplete(text)` → matching locations
- `get_sync_status()` → data freshness per source
        """
        logger.info(f"get_schema: schema={schema}, table={table}, compact={compact}")
        return await _get_schema_internal(schema, table, compact)

    @mcp.tool()
    async def describe_table(
        schema: str = Field(description="Schema name (public, teamwork, missive)"),
        table: str = Field(description="Table name"),
        sample_rows: int = Field(default=3, description="Number of sample rows to show (default 3, max 10)")
    ) -> dict:
        """Get table overview: schema, sample rows, and column statistics.

Combines get_schema + sample query + stats in one call.
Great for exploring unfamiliar tables.

Returns:
    - columns: List of column definitions with types, PKs, FKs
    - sample: First N rows from the table
    - stats: Row count and column value distributions
        """
        logger.info(f"describe_table: {schema}.{table}, sample_rows={sample_rows}")
        valid_schemas = ('public', 'teamwork', 'missive')
        if schema not in valid_schemas:
            return {"error": f"❌ Invalid schema: '{schema}'\n\n💡 Valid schemas: {', '.join(valid_schemas)}"}
        
        if not table.replace('_', '').isalnum():
            return {"error": f"❌ Invalid table name: '{table}'"}
        
        sample_rows = min(max(1, sample_rows), 10)
        
        # Get schema info
        schema_result = await _get_schema_internal(schema=schema, table=table)
        if "error" in schema_result:
            return schema_result
        
        # Get sample rows with stats
        sample_query = f"SELECT * FROM {schema}.{table} LIMIT {sample_rows}"
        sample_result = await execute_query(sample_query, include_stats=True)
        if "error" in sample_result:
            return {"schema": schema_result.get("schema"), "error": sample_result["error"]}
        
        # Get total row count
        count_query = f"SELECT COUNT(*) as total FROM {schema}.{table}"
        count_result = await execute_query(count_query)
        total_rows = count_result.get("rows", [{}])[0].get("total", "?") if "rows" in count_result else "?"
        
        # Common column patterns to suggest
        suggestions = []
        schema_str = schema_result.get("schema", "")
        if "created_at" in schema_str:
            suggestions.append("ORDER BY created_at DESC - for recent records")
        if "_id" in schema_str:
            suggestions.append("JOIN on *_id columns for related data")
        if "email" in schema_str:
            suggestions.append("Filter by email with ILIKE for case-insensitive match")
        
        return {
            "table": f"{schema}.{table}",
            "total_rows": total_rows,
            "columns": schema_result.get("schema", ""),
            "sample": sample_result.get("data", sample_result.get("rows", [])),
            "column_stats": sample_result.get("meta", {}).get("columns", {}),
            "query_tips": suggestions[:3] if suggestions else ["Use LIMIT to preview data", "Use ILIKE for text search"]
        }

