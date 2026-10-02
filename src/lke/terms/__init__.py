"""Legal terms handling."""

from lke.terms.glossary import key, normalise, same
from lke.terms.patterns import Term, find_terms
from lke.terms.protected_terms import ProtectedTerms, protected_terms

__all__ = ["ProtectedTerms", "Term", "find_terms", "key", "normalise", "protected_terms", "same"]
