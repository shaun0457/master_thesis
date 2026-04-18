# agents/de.py
"""
Data Engineer (DE) Agent with SQL sandbox integration.
Executes SQL queries against TEP database.
"""

import re
from .base import BaseAgent
from mas.tools import SQLSandbox


class DataEngineerAgent(BaseAgent):
    """
    Data Engineer agent with SQL sandbox for safe database queries.

    Capabilities:
    - SQL query execution (SELECT only)
    - Automatic query detection in responses
    - Result storage to blackboard
    - Peer judging for DS and ME from data perspective
    """

    def __init__(self, bb_store, router, **kwargs):
        """
        Initialize Data Engineer with SQL sandbox.

        Args:
            bb_store: BlackboardStore instance
            router: Router instance
            **kwargs: Additional args passed to BaseAgent
        """
        super().__init__("de", bb_store, router, **kwargs)

        # Initialize SQL sandbox
        try:
            self.sql = SQLSandbox()
            self.sql_enabled = True
            schema = self.sql.get_schema_info()
            print(f"[DE] [OK] SQL sandbox initialized: {schema['total_tables']} tables available")
        except Exception as e:
            self.sql = None
            self.sql_enabled = False
            print(f"[DE] [WARN]  SQL sandbox not available: {e}")

    def process_response(self, response: str) -> str:
        """
        Detect and execute SQL queries in the response.

        Args:
            response: Raw agent response

        Returns:
            str: Response with SQL execution results appended
        """
        if not self.sql_enabled:
            return response

        # Find SQL code blocks - try standard markdown format first
        sql_pattern_standard = r'```sql\n(.*?)\n```'
        matches = re.findall(sql_pattern_standard, response, re.DOTALL | re.IGNORECASE)

        # If no matches, try format without backticks (e.g., "sql\nSELECT...")
        if not matches:
            sql_pattern_loose = r'(?:^|\n)sql\n(.*?)(?:\n\n|\Z)'
            matches = re.findall(sql_pattern_loose, response, re.DOTALL | re.IGNORECASE | re.MULTILINE)

        if not matches:
            return response

        # Execute each SQL query and append results
        results_text = "\n\n# SQL Execution Results\n"
        data_uris = []  # Track all data URIs for easy access

        for i, query in enumerate(matches):
            result = self.sql.execute(query.strip())

            if result.success:
                results_text += f"\n## Query {i+1} Results\n"
                results_text += f"- Status: [OK] Success\n"
                results_text += f"- Rows: {result.row_count}\n"

                if result.row_count > 0:
                    # Write data to blackboard as Parquet (efficient for tabular data)
                    bb_uri = f"bb://data/sql_result_{i+1}.parquet"
                    bb_path = self.bb_store.resolve(bb_uri)
                    bb_path.parent.mkdir(parents=True, exist_ok=True)

                    result.data.to_parquet(str(bb_path), index=False, engine='pyarrow')
                    data_uris.append(bb_uri)

                    results_text += f"- Data URI: **{bb_uri}**\n"
                    results_text += f"- Format: Parquet (use `pd.read_parquet()` to load)\n"
                    results_text += f"- Columns: {', '.join(result.data.columns.tolist())}\n"

                    # Show preview (first 3 rows)
                    preview = result.data.head(3).to_string()
                    results_text += f"\nPreview:\n{preview}\n"
                else:
                    results_text += "- Data: No rows returned\n"

                print(f"[DE] [OK] SQL query {i+1} executed: {result.row_count} rows")
            else:
                results_text += f"\n## Query {i+1} Error\n"
                results_text += f"- Status: [ERR] Failed\n"
                results_text += f"- Error: {result.error}\n"
                print(f"[DE] [ERR] SQL query {i+1} failed: {result.error}")

        # Add summary section with all data URIs
        if data_uris:
            results_text += f"\n## Data Artifacts Summary\n"
            results_text += f"Total datasets created: {len(data_uris)}\n\n"
            for uri in data_uris:
                results_text += f"- `{uri}`\n"

        final_response = response + results_text
        print(f"[DE] [DEBUG] Original response length: {len(response)} chars")
        print(f"[DE] [DEBUG] Results text length: {len(results_text)} chars")
        print(f"[DE] [DEBUG] Final response length: {len(final_response)} chars")
        print(f"[DE] [DEBUG] Data URIs created: {data_uris}")
        return final_response
