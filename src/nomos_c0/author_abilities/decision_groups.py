"""Expand explicit shared decision opportunities into existing fields and Action rules."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import C0OriginFrame

from .expression_syntax import _identifier


def _mark_resolution(body, effect, path, aliases, origin, depth=0):
    if not isinstance(body, Mapping) or depth > 64:
        raise C0LawError(path + ": bounded resolution object required")
    if "result" in body:
        effects = body.get("effects", [])
        if type(effects) is not list:
            raise C0LawError(path + ".effects: effects require a list")
        aliases.append((path + f".effects[{len(effects)}]", origin))
        body["effects"] = [*effects, effect]
        return
    children = (
        ("then", "else")
        if "when" in body
        else ("success", "failure")
        if "attempt" in body
        else ("then",)
        if "draw" in body
        else ()
    )
    if not children or any(key not in body for key in children):
        raise C0LawError(path + ": incomplete decision resolution")
    for key in children:
        _mark_resolution(body[key], effect, path + "." + key, aliases, origin, depth + 1)


def expand_decision_groups(lib, source, context):
    declarations = lib.get("decision_groups", {})
    if not isinstance(declarations, Mapping):
        raise C0LawError("decision_groups requires named groups")
    if not declarations:
        return lib, context, ()
    from .frontend import row

    if any(not isinstance(lib.get(key), Mapping) for key in ("values", "entities", "abilities")):
        raise C0LawError("decision groups require named values, entities and abilities")
    if not isinstance(source.get("use"), Mapping) or any(
        not isinstance(value, Mapping) for value in source["use"].values()
    ):
        raise C0LawError("decision groups require named Source bindings")
    lib = deepcopy(lib)
    groups, claimed, aliases, frames, markers = [], set(), [], [], []

    def lineage(sort):
        names = set()
        while sort is not None:
            if type(sort) is not str or sort in names or sort not in lib["entities"]:
                raise C0LawError("decision group actor needs an acyclic declared entity sort")
            names.add(sort)
            sort = lib["entities"][sort].get("extends")
        return names

    for name, declaration in declarations.items():
        path = "decision_groups." + str(name)
        if not _identifier(name):
            raise C0LawError("decision group requires an identifier")
        row(
            declaration,
            {"actor", "context", "epoch", "marker", "where", "alternatives"},
            {"views"},
            path=path,
        )
        actor = declaration["actor"]
        if not isinstance(actor, Mapping) or len(actor) != 1:
            raise C0LawError(path + ".actor: one named actor required")
        variable, reference = next(iter(actor.items()))
        kind = lib["values"].get(reference) if type(reference) is str else None
        if (
            variable == "epoch"
            or not _identifier(variable)
            or not isinstance(kind, Mapping)
            or set(kind) != {"ref"}
        ):
            raise C0LawError(path + ".actor: declared Person Ref required")
        sort = kind["ref"]
        parents = lineage(sort)
        if lib["entities"][sort]["kind"] != "person":
            raise C0LawError(path + ".actor: Person Ref required")
        marker = declaration["marker"]
        row(marker, {"field", "type", "initial"}, path=path + ".marker")
        field = marker["field"]
        if not _identifier(field) or type(marker["type"]) is not str:
            raise C0LawError(path + ".marker: named field and value type required")
        related = [child for child in lib["entities"] if child in parents or sort in lineage(child)]
        if any(field in lib["entities"][parent]["fields"] for parent in related) or any(
            old_field == field and (old_sort in parents or sort in lineage(old_sort))
            for old_sort, old_field in markers
        ):
            raise C0LawError(path + ".marker: field already declared or managed by another group")
        if any(type(declaration[key]) is not str for key in ("epoch", "where", "context")):
            raise C0LawError(path + ": context and expression text required")
        alternatives = declaration["alternatives"]
        if (
            type(alternatives) is not list
            or not alternatives
            or any(type(item) is not str or item not in lib["abilities"] for item in alternatives)
            or len(set(alternatives)) != len(alternatives)
            or claimed.intersection(alternatives)
        ):
            raise C0LawError(
                path + ".alternatives: unique ordinary abilities in one group required"
            )
        bindings = {
            selection.get("context")
            for selection in source["use"].values()
            if selection.get("definition") in alternatives
        }
        if len(bindings) > 1 or None in bindings:
            raise C0LawError(path + ": alternatives must bind one shared context instance")
        entity = lib["entities"][sort]
        entity["fields"][field] = marker["type"]
        entity.setdefault("initial", {})[field] = deepcopy(marker["initial"])
        for child in lib["entities"]:
            if sort in lineage(child):
                lib["entities"][child]["view"] = [*lib["entities"][child]["view"], field]
        markers.append((sort, field))
        origin = ("decision_groups", name)
        aliases.extend(
            [
                (f"entities.{sort}.fields.{field}", (*origin, "marker", "type")),
                (f"entities.{sort}.initial.{field}", (*origin, "marker", "initial")),
            ]
        )
        done = name + "_done"
        if any(done in lib.get(category, {}) for category in ("queries", "values", "facts")):
            raise C0LawError(path + ": generated completion query name conflicts")
        lib.setdefault("queries", {})[done] = {
            "parameters": {variable: reference, "epoch": marker["type"]},
            "returns": "Bool",
            "expression": f"{variable}.{field} == epoch",
        }
        aliases.append(("queries." + done, origin))
        individual_conditions = []
        for alternative in alternatives:
            ability = lib["abilities"][alternative]
            if not isinstance(ability, Mapping):
                raise C0LawError(path + ": alternative must be an ability object")
            for key in ("actor", "context", "epoch"):
                if key in ability:
                    raise C0LawError(path + f": alternative cannot override shared {key}")
                ability[key] = deepcopy(declaration[key])
                aliases.append((f"abilities.{alternative}.{key}", (*origin, key)))
            common_views, own_views = declaration.get("views", {}), ability.get("views", {})
            if not isinstance(common_views, Mapping) or not isinstance(own_views, Mapping):
                raise C0LawError(path + ".views: named views required")
            if set(common_views) & set(own_views):
                raise C0LawError(path + ": alternative cannot override shared views")
            ability["views"] = {**deepcopy(common_views), **own_views}
            for alias in common_views:
                aliases.append(
                    (f"abilities.{alternative}.views.{alias}", (*origin, "views", alias))
                )
            where = declaration["where"]
            if "where" in ability:
                if type(ability["where"]) is not str:
                    raise C0LawError(path + ": alternative condition must be expression text")
                individual_conditions.append((alternative, ability["where"]))
                where = f"({where}) and ({ability['where']})"
            else:
                aliases.append((f"abilities.{alternative}.where", (*origin, "where")))
            ability["where"] = f"({where}) and {variable}.{field} != ({declaration['epoch']})"
            _mark_resolution(
                ability.get("resolve"),
                f"set({variable}.{field}, {declaration['epoch']})",
                f"abilities.{alternative}.resolve",
                aliases,
                (*origin, "marker"),
            )
            if context is not None:
                frames.append(
                    (
                        f"abilities.{alternative}",
                        (
                            C0OriginFrame(
                                "decision_group",
                                name,
                                path,
                                context.locate(path),
                            ),
                        ),
                    )
                )
        claimed.update(alternatives)
        groups.append(
            (
                name,
                tuple(alternatives),
                marker["type"],
                declaration["where"],
                declaration["epoch"],
                tuple(individual_conditions),
            )
        )
    if context is not None:
        resolved = {
            alias: context.indexed_path(".".join(origin)) or origin
            for alias, origin in aliases
        }
        context = replace(
            context,
            aliases=tuple({**dict(context.aliases), **resolved}.items()),
            scoped_frames=(*context.scoped_frames, *frames),
        )
    return lib, context, tuple(groups)


def check_group_epochs(groups, abilities):
    for name, alternatives, type_name, *_ in groups:
        for plan in abilities:
            if plan.definition in alternatives and plan.epoch.result.name != type_name:
                raise C0LawError(f"decision_groups.{name}.epoch: marker and epoch types must match")


def check_group_conditions(groups, definition, compiler):
    """Check authored expression parts before their generated conjunction loses offsets."""
    for name, alternatives, type_name, where, epoch, individual in groups:
        if definition not in alternatives:
            continue
        compiler.expression(epoch, type_name, f"decision_groups.{name}.epoch", context="actor")
        compiler.expression(where, "Bool", f"decision_groups.{name}.where", context="actor")
        if definition in dict(individual):
            compiler.expression(
                dict(individual)[definition],
                "Bool",
                f"abilities.{definition}.where",
                context="actor",
            )
