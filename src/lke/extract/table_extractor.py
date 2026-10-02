"""Tables -> attribute/value relationships."""

from __future__ import annotations

from lke.models.records import ComparisonItem


def subjects_and_dimensions(items: list[ComparisonItem]) -> tuple[list[str], list[str]]:
    """Distinct subjects and attributes, in first-seen order."""
    subjects: list[str] = []
    dimensions: list[str] = []
    for item in items:
        if item.subject and item.subject not in subjects:
            subjects.append(item.subject)
        if item.attribute and item.attribute not in dimensions:
            dimensions.append(item.attribute)
    return subjects, dimensions


def table_to_triples(rows: list[list[str]]) -> list[tuple[str, str, str]]:
    """Header row = subjects, first column = attributes -> (subject, attribute, value).

    Used to check comparison records against tables found in the PDF.
    """
    if len(rows) < 2 or len(rows[0]) < 2:
        return []
    header = rows[0]
    triples = []
    for row in rows[1:]:
        attribute = row[0]
        for col, value in enumerate(row[1:], 1):
            if col < len(header) and header[col] and value:
                triples.append((header[col], attribute, value))
    return triples
