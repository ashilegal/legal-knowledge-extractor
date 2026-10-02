"""Content-type classification."""

from lke.classify.classifier import SectionClass, classify_section
from lke.classify.rules import CONTENT_TYPES

__all__ = ["CONTENT_TYPES", "SectionClass", "classify_section"]
