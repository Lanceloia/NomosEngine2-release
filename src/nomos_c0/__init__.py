"""Errors shared by the current declarative compiler and its live bindings."""

from .author_contract_v1 import C0BindingError, C0LawError

__all__ = (
    "C0BindingError",
    "C0LawError",
)
