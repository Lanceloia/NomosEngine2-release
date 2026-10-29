"""Compile structured guarantees and normalize acquired public arguments only."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError
from nomos_cognition.state import Term

from .expression_syntax import _identifier, parse_expression
from .expressions import compile_value_expression


@dataclass(frozen=True)
class LocalConstraint:
    kind: str
    members: object
    labels: object
    minimum: object | None
    maximum: object | None
    relation: Term
    check: object


def constraint_formula(definition, path, *, reserved=()):
    from .frontend import row

    row(
        definition,
        {"parameters", "variables", "realize"},
        {"holds", "cardinality", "allocation"},
        path=path,
    )
    forms = set(definition) & {"holds", "cardinality", "allocation"}
    if len(forms) != 1:
        raise C0LawError(path + ": select exactly one constraint form")
    kind = next(iter(forms))
    if kind == "holds":
        return definition[kind]
    shape = definition[kind]
    row(
        shape,
        {"entries", "subject", "label", "members", "classification"}
        | ({"matching", "minimum"} if kind == "cardinality" else {"labels"}),
        {"maximum", "exact_entries"} if kind == "cardinality" else {"exact_entries"},
        path=path + "." + kind,
    )
    if any(not _identifier(shape[k]) for k in ("entries", "subject", "label", "classification")):
        raise C0LawError(path + ": local entries and fields need declared identifiers")
    if (
        not isinstance(definition["variables"], dict)
        or shape["entries"] not in definition["variables"]
    ):
        raise C0LawError(path + ": local entries must select a declared finite variable")
    if any(
        type(v) is not str
        for k, v in shape.items()
        if k not in ("entries", "subject", "label", "exact_entries")
    ):
        raise C0LawError(path + ": local arguments require pure expressions")
    if "exact_entries" in shape and type(shape["exact_entries"]) is not bool:
        raise C0LawError(path + ": exact_entries requires a boolean")
    used = set(reserved) | set(definition["parameters"]) | set(definition["variables"])
    for key in ("members", "labels", "matching", "minimum", "maximum"):
        if key not in shape:
            continue
        pending = [parse_expression(shape[key], path=path + "." + kind + "." + key)]
        while pending:
            node = pending.pop()
            if node.operation in ("name", "lambda"):
                used.add(node.value)
            pending.extend(node.children)

    def fresh(prefix):
        while prefix in used:
            prefix += "X"
        used.add(prefix)
        return prefix

    p, i, r = fresh("localSubject"), fresh("localEntry"), fresh("localLabel")
    entries, subject, label = shape["entries"], shape["subject"], shape["label"]
    members = "(" + shape["members"] + ")"
    coverage = f"forall({members}, {p} => exactly_one({entries}, {i} => {i}.{subject} == {p}))"
    if shape.get("exact_entries", False):
        coverage += (
            f" and size({entries}) == size({members}) and "
            f"forall({entries}, {i} => {i}.{subject} in {members})"
        )
    if kind == "allocation":
        labels = "(" + shape["labels"] + ")"
        return (
            f"{coverage} and size({members}) == size({labels}) and "
            f"forall({labels}, {r} => "
            f"sum_by({entries}, {i} => 1 if {i}.{subject} in {members} "
            f"and {i}.{label} == {r} else 0)"
            f" == sum_by({labels}, {i} => 1 if {i} == {r} else 0))"
        )
    matching = "(" + shape["matching"] + ")"
    count = (
        f"sum_by({entries}, {i} => 1 if {i}.{subject} in {members} "
        f"and exists({matching}, {r} => {i}.{label} == {r}) else 0)"
    )
    low = "(" + shape["minimum"] + ")"
    high = "(" + shape.get("maximum", f"size({members})") + ")"
    return (
        f"{coverage} and 0 <= {low} and {low} <= {count} and "
        f"{count} <= {high} and {high} <= size({members})"
    )


def compile_local_constraint(definition, table, pure, entities, path):
    kind = next((k for k in ("cardinality", "allocation") if k in definition), None)
    if kind is None:
        return None
    shape = definition[kind]
    entries = table[definition["variables"][shape["entries"]]]
    fields = dict(entries.element.fields) if entries.kind in ("set", "sequence") else {}
    if (
        entries.element is None
        or entries.element.kind != "record"
        or not {shape["subject"], shape["label"]} <= set(fields)
    ):
        raise C0LawError(path + ": local entries require subject/label record fields")

    def expression(text, suffix):
        value = compile_value_expression(
            text,
            table,
            definition["parameters"],
            returns=None,
            library=pure,
            entities=entities,
            context="world",
            path=path + "." + kind + "." + suffix,
        )
        if value.summary.owner_reads or value.summary.reference_domains:
            raise C0LawError(path + ": local normalization can only read public arguments")
        return value

    members = expression(shape["members"], "members")
    labels = expression(shape["matching" if kind == "cardinality" else "labels"], "labels")
    if (
        members.result.kind != "set"
        or members.result.element.kind != "ref"
        or fields[shape["subject"]].type_id != members.result.element.type_id
        or labels.result.kind not in ("set", "sequence")
        or labels.result.element.kind != "enum"
        or fields[shape["label"]].type_id != labels.result.element.type_id
        or kind == "allocation"
        and labels.result.kind != "sequence"
    ):
        raise C0LawError(
            path + ": local constraints require nominal reference sets and enum labels"
        )
    low = expression(shape["minimum"], "minimum") if kind == "cardinality" else None
    high = expression(shape["maximum"], "maximum") if "maximum" in shape else None
    if any(v is not None and v.result.kind != "int" for v in (low, high)):
        raise C0LawError(path + ": local bounds require integer expressions")
    reserved = set(dict(table.definitions)) | set(dict(pure.definitions))
    subject = "classificationSubject"
    while subject in reserved:
        subject += "X"
    classification = compile_value_expression(
        shape["classification"] + "(" + subject + ")",
        table,
        {subject: members.result.element.name},
        returns=labels.result.element.name,
        library=pure,
        entities=entities,
        context="world",
        path=path + ".classification",
    )
    reserved |= set(definition["parameters"]) | set(definition["variables"])
    while subject in reserved:
        subject += "X"
    entry = "classificationEntry"
    while entry in reserved or entry == subject:
        entry += "X"
    check = compile_value_expression(
        f"forall(({shape['members']}), {subject} => "
        f"exactly_one({shape['entries']}, {entry} => {entry}.{shape['subject']} == {subject} "
        f"and {entry}.{shape['label']} == {shape['classification']}({subject})))",
        table,
        {**definition["parameters"], **definition["variables"]},
        returns="Bool",
        library=pure,
        entities=entities,
        context="world",
        path=path + ".classification_check",
    )
    relation = Term(
        "Classification", labels.result.element.type_id.signature, classification.read_key
    )
    return LocalConstraint(kind, members, labels, low, high, relation, check)
