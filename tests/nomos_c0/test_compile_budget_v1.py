"""Short structural limits and a real compile/start/settle above 64 Actions."""

from __future__ import annotations

from copy import deepcopy

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published
from test_actor_binding_v1 import Actor, _actor_event_source, _source
from test_world_binding_v1 import ROOT, _compile, _documents

from nomos_c0.actor_binding_v1 import expand_actor_bindings
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.compile_budget_v1 import COMPILE_BUDGET, C0CompileLimitError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib


def test_shared_budget_changes_only_record_and_law_capacity():
    assert (
        COMPILE_BUDGET.nominal_records,
        COMPILE_BUDGET.law_definitions,
        COMPILE_BUDGET.actions,
        COMPILE_BUDGET.causal_edges,
        COMPILE_BUDGET.event_results,
        COMPILE_BUDGET.value_read_paths,
    ) == (256, 256, 512, 4096, 512, 8192)


def _expand(source, owners):
    return expand_actor_bindings(
        source,
        owners,
        {"attack": next(iter(owners))},
        frozenset(),
        actor_event_templates=frozenset({"notice"}),
    )


def test_action_family_boundary_and_failure_leave_source_unchanged():
    owners = {f"a{i}": (Actor, "name") for i in range(64)}
    source = _source()
    source["actor_domains"][0]["owners"] = list(owners)
    source["events"] = []
    family = source["actions"][0]
    source["actions"] = []
    for i in range(COMPILE_BUDGET.actions // len(owners)):
        item = deepcopy(family)
        item.update(family=f"use{i}", source_prefix=f"sample.use{i}")
        source["actions"].append(item)
    assert len(_expand(source, owners)["actions"]) == COMPILE_BUDGET.actions
    item = deepcopy(family)
    item.update(family="overflow", source_prefix="sample.overflow")
    source["actions"].append(item)
    before = deepcopy(source)
    with pytest.raises(C0CompileLimitError) as caught:
        _expand(source, owners)
    assert source == before
    error = caught.value
    assert (error.resource, error.actual, error.limit, error.stage) == (
        "actions",
        COMPILE_BUDGET.actions + 1,
        COMPILE_BUDGET.actions,
        "Actor expansion",
    )


def test_explicit_actions_use_the_same_budget():
    source = _source()
    source["actions"] = [{"name": f"a{i}"} for i in range(COMPILE_BUDGET.actions + 1)]
    source["actor_domains"][0]["owners"] = ["a"]
    source["events"] = []
    with pytest.raises(C0CompileLimitError, match="actions=513.*limit=512"):
        _expand(source, {"a": (Actor, "name")})


def test_shared_result_budget_counts_results_not_causal_edges():
    owners = {f"a{i}": (Actor, "name") for i in range(64)}
    source = _actor_event_source()
    source["actor_domains"][0]["owners"] = list(owners)
    source["events"][0].update(actor_domain="participants", share_result=True)
    expanded = _expand(source, owners)
    assert len(expanded["events"]) == COMPILE_BUDGET.causal_edges
    assert len({event["source_key"] for event in expanded["events"]}) == 64
    other = deepcopy(source["events"][0])
    other.update(family="another_notice", source_prefix="sample.another-notice")
    source["events"].append(other)
    with pytest.raises(C0CompileLimitError, match="causal_edges=4097.*limit=4096"):
        _expand(source, owners)


def test_independent_results_have_their_own_limit():
    owners = {f"a{i}": (Actor, "name") for i in range(23)}
    source = _actor_event_source()
    source["actor_domains"][0]["owners"] = list(owners)
    source["events"][0]["actor_domain"] = "participants"
    with pytest.raises(C0CompileLimitError) as caught:
        _expand(source, owners)
    assert (caught.value.resource, caught.value.actual, caught.value.limit) == (
        "event_results",
        529,
        COMPILE_BUDGET.event_results,
    )


def test_above_64_actions_compile_and_settle_with_exact_source_identity():
    lib, ports, source = _documents("parcel_delivery_v0")
    source["game_form"] = {"mode": "manual"}
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    exemplar = source["actions"][1]
    for i in range(63):
        item = deepcopy(exemplar)
        item.update(
            name=f"confirm_{i}",
            source_key=f"sample.confirm-{i}",
            event_type=f"sample.confirm-{i}.action",
        )
        source["actions"].append(item)
    receiver = source["seats"][1]
    receiver["entries"].append("confirm_62")
    offer = deepcopy(receiver["offers"][0])
    offer.update(entry="confirm_62", label="Confirm through last compiled Action")
    receiver["offers"].append(offer)
    program = _compile(lib, ports, source)
    assert len(program.actions) == 65
    session = program.start(assets)
    dispatch = session.offers("sender")[0]
    assert isinstance(session.submit("sender", dispatch.entry, dict(dispatch.payload)), K0Published)
    session.advance("sender", 2)
    confirm = next(offer for offer in session.offers("receiver") if offer.entry == "confirm_62")
    published = session.submit("receiver", confirm.entry, dict(confirm.payload))
    assert isinstance(published, K0Published)
    assert published.occurrences[0].source.value == "sample.confirm-62"
    assert dict(session.author_snapshot().owners)["receiver"].receipt is not None


def test_ports_above_64_share_the_action_budget_and_last_template_runs():
    lib, ports, source = _documents("parcel_delivery_v0")
    source["game_form"] = {"mode": "manual"}
    template = ports["actions"][1]
    action = source["actions"][1]
    for index in range(63):
        symbol = f"confirm_template_{index}"
        ports["actions"].append(deepcopy(dict(template, symbol=symbol)))
        source["actions"].append(
            deepcopy(
                dict(
                    action,
                    name=f"confirm_{index}",
                    template=symbol,
                    source_key=f"sample.confirm-{index}",
                    event_type=f"sample.confirm-{index}.action",
                )
            )
        )
    receiver = source["seats"][1]
    receiver["entries"].append("confirm_62")
    receiver["offers"].append(dict(receiver["offers"][0], entry="confirm_62"))
    program = _compile(lib, ports, source)
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    session = program.start(assets)
    dispatch = session.offers("sender")[0]
    session.submit("sender", dispatch.entry, dict(dispatch.payload))
    session.advance("sender", 2)
    offer = next(row for row in session.offers("receiver") if row.entry == "confirm_62")
    result = session.submit("receiver", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert result.occurrences[0].source.value == "sample.confirm-62"
    before = deepcopy(ports)
    ports["actions"] = [{} for _ in range(COMPILE_BUDGET.actions + 1)]
    with pytest.raises(C0CompileLimitError) as caught:
        check_graph_ports(ports, check_nominal_lib(lib))
    assert caught.value.stage == "Ports action templates"
    assert caught.value.actual == 513
    assert ports["actions"] == [{} for _ in range(513)]
    assert len(before["actions"]) == 65


def _lawdef_documents(count, library_count=0):
    lib, ports, source = _documents("parcel_delivery_v0")
    definitions = source["lawdefs"]
    exemplar = next(row for row in definitions if row["name"] == "action.confirm")
    while len(definitions) < count:
        definitions.append(deepcopy(dict(exemplar, name=f"action.confirm_{len(definitions)}")))
    source["actions"][1]["law"]["ref"] = definitions[-1]["name"]
    lib["lawdefs"] = definitions[:library_count]
    source["lawdefs"] = definitions[library_count:]
    return lib, ports, source


@pytest.mark.parametrize("count", [129, 256])
@pytest.mark.parametrize("allocation", ["source", "split", "library"])
def test_library_and_source_share_one_combined_lawdef_budget(count, allocation):
    library_count = {"source": 0, "split": count // 2, "library": count}[allocation]
    lib, ports, source = _lawdef_documents(count, library_count)
    before = deepcopy((lib, ports, source))
    program = _compile(lib, ports, source)
    assert len(program.actions) == 2
    assert (lib, ports, source) == before


@pytest.mark.parametrize(
    ("library_count", "stage", "actual"),
    [
        (0, "Source declarations", 257),
        (257, "Lib declarations", 257),
        (128, "Program LawDefs", 257),
    ],
)
def test_lawdef_overflow_names_the_stage_and_never_mutates_inputs(library_count, stage, actual):
    lib, ports, source = _lawdef_documents(257, library_count)
    before = deepcopy((lib, ports, source))
    with pytest.raises(C0CompileLimitError) as caught:
        _compile(lib, ports, source)
    assert (lib, ports, source) == before
    error = caught.value
    assert (error.resource, error.actual, error.limit, error.stage) == (
        "law_definitions",
        actual,
        256,
        stage,
    )


def _use_last_record(lib, ports, source, count):
    receipt = next(row for row in lib["records"] if row["name"] == "Receipt")
    while len(lib["records"]) < count:
        lib["records"].append(deepcopy(dict(receipt, name=f"Receipt{len(lib['records'])}")))
    last_type = lib["records"][-1]["name"]
    receiver = next(row for row in lib["records"] if row["name"] == "Receiver")
    receiver["fields"][-1]["type"] = {"optional": last_type}
    ports["actions"][1]["value"]["outputs"]["receipt"] = last_type
    ports["actions"][1]["value"]["construct"] = [last_type]
    definitions = lib["lawdefs"] + source["lawdefs"]
    definitions[-1]["body"]["value"]["outputs"]["receipt"]["record"]["type"] = last_type
    return last_type


@pytest.mark.parametrize("count", [129, 256])
@pytest.mark.parametrize("allocation", ["source", "split", "library"])
def test_last_record_and_lawdef_run_with_actual_action_and_event_sources(count, allocation):
    library_count = {"source": 0, "split": count // 2, "library": count}[allocation]
    lib, ports, source = _lawdef_documents(count, library_count)
    last_type = _use_last_record(lib, ports, source, count)
    source["game_form"] = {"mode": "manual"}
    before = deepcopy((lib, ports, source))
    program = _compile(lib, ports, source)
    assert (lib, ports, source) == before
    assert len(lib["records"]) == count
    assert len(lib["lawdefs"] + source["lawdefs"]) == count
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    session = program.start(assets)
    dispatch = session.offers("sender")[0]
    sent = session.submit("sender", dispatch.entry, dict(dispatch.payload))
    assert isinstance(sent, K0Published)
    assert sent.occurrences[0].source.value == "c0.parcel.dispatch"
    session.advance("sender", 2)
    confirm = session.offers("receiver")[0]
    result = session.submit("receiver", confirm.entry, dict(confirm.payload))
    assert isinstance(result, K0Published)
    assert result.occurrences[0].source.value == "c0.parcel.confirm"
    receipt = dict(session.author_snapshot().owners)["receiver"].receipt
    assert type(receipt) is program.world_layout.owners.record_layout.record(last_type)
    receipt.validate_for_k0()
    assert receipt.action == result.occurrences[0].occurrence
    assert {"c0.parcel.depart", "c0.parcel.notice", "c0.parcel.arrive.due"} <= {
        row.source.value for row in session._runtime.occurrence_history()
    }
    assert (lib, ports, source) == before


def test_record_overflow_keeps_lib_stage_and_inputs_unchanged():
    lib, ports, source = _lawdef_documents(256)
    _use_last_record(lib, ports, source, 257)
    before = deepcopy((lib, ports, source))
    with pytest.raises(C0CompileLimitError) as caught:
        _compile(lib, ports, source)
    error = caught.value
    assert (error.resource, error.actual, error.limit, error.stage) == (
        "nominal_records",
        257,
        256,
        "Lib declarations",
    )
    assert (lib, ports, source) == before


def test_empty_library_is_valid_when_source_supplies_lawdefs():
    lib, ports, source = _documents("parcel_delivery_v0")
    lib["lawdefs"] = []
    assert check_nominal_lib(lib).lawdefs == ()
    assert len(_compile(lib, ports, source).actions) == 2
