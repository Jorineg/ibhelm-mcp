"""
Python code execution tool (experimental).
Allows running Python code with database access in a sandboxed environment.
"""

import re
import signal
import sys
import math
import json as json_module
import re as re_module
from io import StringIO
from contextlib import contextmanager
from datetime import datetime, timedelta, date
from collections import Counter, defaultdict
from pydantic import Field

from database import get_pool, validate_query


class PythonTimeoutError(Exception):
    pass


@contextmanager  
def timeout_context(seconds):
    """Context manager for timeout (Unix only)."""
    def handler(signum, frame):
        raise PythonTimeoutError(f"Execution timed out after {seconds}s")
    
    old_handler = signal.signal(signal.SIGALRM, handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


# Safe builtins for Python execution
SAFE_BUILTINS = {
    'abs': abs, 'all': all, 'any': any, 'bin': bin, 'bool': bool,
    'chr': chr, 'dict': dict, 'divmod': divmod, 'enumerate': enumerate,
    'filter': filter, 'float': float, 'format': format, 'frozenset': frozenset,
    'hash': hash, 'hex': hex, 'int': int, 'isinstance': isinstance,
    'issubclass': issubclass, 'iter': iter, 'len': len, 'list': list,
    'map': map, 'max': max, 'min': min, 'next': next, 'oct': oct,
    'ord': ord, 'pow': pow, 'print': print, 'range': range, 'repr': repr,
    'reversed': reversed, 'round': round, 'set': set, 'slice': slice,
    'sorted': sorted, 'str': str, 'sum': sum, 'tuple': tuple, 'type': type,
    'zip': zip, 'True': True, 'False': False, 'None': None,
}


def register_python_tools(mcp):
    """Register the Python execution tool."""
    
    @mcp.tool()
    async def run_python(
        code: str = Field(description="Python code to execute. Last expression value is returned."),
        timeout_seconds: int = Field(default=10, description="Max execution time (default 10, max 30)")
    ) -> dict:
        """Execute Python code with database access. EXPERIMENTAL.

Available in scope:
    - db_query(sql): Execute SQL and return rows as list of dicts
    - math, json, re, datetime, timedelta, date
    - Counter, defaultdict
    - print() output is captured
    - Basic builtins (no file/network access)

Example:
    ```python
    rows = db_query("SELECT name, status FROM teamwork.tasks LIMIT 100")
    by_status = Counter(r['status'] for r in rows)
    result = dict(by_status)
    ```

Returns:
    - result: Value of last expression (or None)
    - output: Captured print() output
    - error: Error message if failed
        """
        timeout_seconds = min(max(1, timeout_seconds), 30)
        
        # Pre-execute: scan code for db_query calls and execute them
        query_cache = {}
        query_count = 0
        MAX_QUERIES = 10
        
        # Get database pool once
        pool = await get_pool()
        
        async def execute_query_async(sql: str) -> list:
            """Execute a query and return results."""
            nonlocal query_count
            query_count += 1
            if query_count > MAX_QUERIES:
                raise ValueError(f"Too many queries (max {MAX_QUERIES})")
            
            is_valid, error = validate_query(sql)
            if not is_valid:
                raise ValueError(error)
            
            async with pool.acquire() as conn:
                await conn.execute("SET statement_timeout = '10s'")
                rows = await conn.fetch(sql)
                result = []
                for row in rows:
                    row_dict = {}
                    for key, value in dict(row).items():
                        if hasattr(value, 'isoformat'):
                            row_dict[key] = value.isoformat()
                        elif isinstance(value, (bytes, bytearray)):
                            row_dict[key] = f"<{len(value)} bytes>"
                        else:
                            row_dict[key] = value
                    result.append(row_dict)
                return result
        
        # Synchronous wrapper that uses cached results
        def db_query(sql: str) -> list:
            """Execute SQL query and return results as list of dicts."""
            normalized = ' '.join(sql.split())
            if normalized in query_cache:
                return query_cache[normalized]
            raise ValueError(f"Query not pre-cached: {sql[:50]}... Use string literals for db_query().")
        
        # Parse code to find all db_query calls and pre-execute them
        queries_in_code = []
        
        # Match triple-quoted strings FIRST (more specific)
        query_pattern_triple = r'db_query\s*\(\s*"""([\s\S]+?)"""\s*\)'
        queries_in_code.extend(re.findall(query_pattern_triple, code))
        query_pattern_triple2 = r"db_query\s*\(\s*'''([\s\S]+?)'''\s*\)"
        queries_in_code.extend(re.findall(query_pattern_triple2, code))
        
        # Then match single-line strings
        query_pattern_single = r'db_query\s*\(\s*"(?!"")([^"]+)"\s*\)'
        queries_in_code.extend(re.findall(query_pattern_single, code))
        query_pattern_single2 = r"db_query\s*\(\s*'(?!'')([^']+)'\s*\)"
        queries_in_code.extend(re.findall(query_pattern_single2, code))
        
        # Pre-execute all found queries
        for sql in queries_in_code:
            normalized = ' '.join(sql.split())
            if normalized not in query_cache:
                try:
                    query_cache[normalized] = await execute_query_async(normalized)
                except Exception as e:
                    return {"error": f"Query failed: {normalized[:100]}... - {str(e)}"}
        
        # Build execution environment
        env = {
            '__builtins__': SAFE_BUILTINS,
            'math': math,
            'json': json_module,
            're': re_module,
            'datetime': datetime,
            'timedelta': timedelta,
            'date': date,
            'Counter': Counter,
            'defaultdict': defaultdict,
            'db_query': db_query,
        }
        
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        
        try:
            result = None
            
            with timeout_context(timeout_seconds):
                try:
                    # Execute code
                    exec(compile(code, '<user_code>', 'exec'), env)
                    
                    # Try to evaluate last line as expression for return value
                    lines = code.strip().split('\n')
                    if lines:
                        last_line = lines[-1].strip()
                        skip_prefixes = ('#', 'import', 'from', 'def', 'class', 'if', 'for', 'while', 'try', 'with', 'return', 'raise', 'assert', 'pass', 'break', 'continue')
                        if last_line and not any(last_line.startswith(p) for p in skip_prefixes):
                            if '=' not in last_line or last_line.count('=') == last_line.count('=='):
                                try:
                                    result = eval(last_line, env)
                                except:
                                    pass
                except ImportError as e:
                    return {
                        "error": f"Import not allowed. Available: math, json, re, datetime, timedelta, date, Counter, defaultdict",
                        "output": captured_output.getvalue() or None
                    }
                except Exception as e:
                    return {"error": f"Execution error: {type(e).__name__}: {str(e)}", "output": captured_output.getvalue() or None}
            
            output = captured_output.getvalue()
            
            # Serialize result
            if result is not None:
                try:
                    if hasattr(result, 'isoformat'):
                        result = result.isoformat()
                    elif isinstance(result, (set, frozenset)):
                        result = list(result)
                    json_module.dumps(result)  # Test serializable
                except:
                    result = str(result)
            
            return {"result": result, "output": output if output else None}
            
        except PythonTimeoutError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Unexpected error: {type(e).__name__}: {str(e)}"}
        finally:
            sys.stdout = old_stdout

