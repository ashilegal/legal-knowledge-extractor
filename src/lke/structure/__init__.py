"""Document structure."""

from lke.structure.headings import Heading, detect_headings
from lke.structure.sectioner import make_sections, page_marker
from lke.structure.topic_tree import TopicNode, build_tree, clean_title, find_headings

__all__ = [
    "Heading", "TopicNode", "build_tree", "clean_title", "detect_headings",
    "find_headings", "make_sections", "page_marker",
]
