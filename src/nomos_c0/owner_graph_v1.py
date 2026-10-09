"""Compile composition; declarations, binding and execution have their own modules."""

from __future__ import annotations

from . import author_document_v1, graph_contracts_v1, graph_frontend_v1, program_runtime_v1

__all__ = ["compile_owner_graph"]


def compile_owner_graph(
    library: graph_contracts_v1.C0GraphLibrary,
    source: str
    | dict[str, object]
    | author_document_v1.C0AuthorDocument
    | author_document_v1.C0AssembledSource,
) -> program_runtime_v1.C0OwnerGraphProgram:
    from .program_binding_v1 import bind_program

    ir, layout = graph_frontend_v1.check_owner_graph(library, source)
    return bind_program(ir, layout)
