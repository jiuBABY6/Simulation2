"""Literature search and management.

Academic literature search (MCP), workspace indexing, formatting, and full-text helpers.
"""

from agentsociety2.skills.literature.models import LiteratureEntry, LiteratureIndex
from agentsociety2.skills.literature.formatter import (
    sanitize_filename,
    format_article_as_markdown,
)
from agentsociety2.skills.literature.search import (
    search_literature_and_save,
    generate_summary,
    format_search_results,
    load_literature_index,
)
from agentsociety2.skills.literature.core import (
    search_literature,
    is_chinese_text,
)

__all__ = [
    # Models
    "LiteratureEntry",
    "LiteratureIndex",
    "format_article_as_markdown",
    "format_search_results",
    "generate_summary",
    "is_chinese_text",
    "load_literature_index",
    # Formatter
    "sanitize_filename",
    # Core
    "search_literature",
    # Search
    "search_literature_and_save",
]
