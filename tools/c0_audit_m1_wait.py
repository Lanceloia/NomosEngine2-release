"""Separate one real M1 wait transaction from checked expression evaluation."""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
from collections import Counter
from contextlib import ExitStack, nullcontext
from pathlib import Path
from statistics import median
from time import perf_counter
from unittest.mock import patch

from nomos_kernel import K0OccurrenceRef
from nomos_kernel import _atomic_inmemory_session as atomic
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0 import composable_value_v1 as value
from nomos_c0.composable_action_v1 import _Rule
from nomos_c0.program_runtime_v1 import C0OwnerGraphSession
from nomos_c0.source_bundle_v1 import compile_source_bundle, read_source_bundle
from tools.c0_profile_pipeline import _snapshot_digest


def is_wait(program):
    return (
        not program._tree["bindings"]
        and not program.effects
        and value._plain_tree(program.guard_ir.expression)
        == {"eq": [{"ref": "actor.name"}, {"ref": "payload.actor"}]}
        and value._plain_tree(program._tree["outputs"])
        == {"action": {"ref": "occurrence"}, "last_action_ref": {"ref": "occurrence"}}
    )


def checked_native_wait(program, roots, *, occurrence=None):
    """Diagnostic oracle only: same nominal boundary, no K0 settlement bypass."""
    if occurrence is not None and type(occurrence) is not K0OccurrenceRef:
        raise value.C0ValueStateError("value evaluation has a foreign occurrence")
    program._check_roots(roots, program._ports)
    if roots["actor"].name != roots["payload"].actor:
        return None
    if occurrence is None:
        raise value.C0ValueStateError("effect evaluation needs an actual occurrence")
    result = {"action": occurrence, "last_action_ref": occurrence}
    if any(
        not value._value_matches(item, program._ports.outputs[name])
        for name, item in result.items()
    ):
        raise value.C0ValueStateError("compiled value result has a foreign type")
    return result


def expression_comparison(program, roots, occurrence, iterations):
    if not is_wait(program):
        raise ValueError("native oracle accepts only the exact authored wait expression")
    if type(iterations) is not int or iterations < 1:
        raise ValueError("iterations must be positive")
    expected = program.evaluate(roots, occurrence=occurrence)
    if checked_native_wait(program, roots, occurrence=occurrence) != expected:
        raise ValueError("checked native expression differs from compiled expression")
    samples = {"compiled": [], "checked_native": []}
    # Pair and alternate order; this excludes all Session work and compile/start costs.
    for trial in range(4):
        order = ("compiled", "checked_native") if trial % 2 == 0 else ("checked_native", "compiled")
        for name in order:
            started = perf_counter()
            for _ in range(iterations):
                result = (
                    program.evaluate(roots, occurrence=occurrence)
                    if name == "compiled"
                    else checked_native_wait(program, roots, occurrence=occurrence)
                )
            elapsed = perf_counter() - started
            if result != expected:
                raise ValueError("expression result changed during timing")
            samples[name].append(elapsed / iterations)
    return {
        "iterations_per_sample": iterations,
        "seconds_per_evaluation": samples,
        "compiled_over_checked_native": (
            median(samples["compiled"]) / median(samples["checked_native"])
        ),
        "boundary": "expression only; same root/output checks; no Session equivalence claim",
    }


def one_wait(program, assets, *, observe=False):
    session = program.start(assets)
    frame = session.continue_form("adventurer")
    matches = [offer for offer in frame.offers if offer.entry == "wait_adventurer"]
    if frame.finished or frame.ready_seats != ("adventurer",) or len(matches) != 1:
        raise ValueError("audit requires exactly one currently offered player wait")
    before = session.author_snapshot()
    clones, views = Counter(), Counter()
    captured = []
    original_clone = atomic._clone_owner_state
    original_views = atomic._build_candidate_owner_views
    original_evaluate = value.C0ValueProgram.evaluate

    def clone(owner, state):
        clones[owner.key.value] += 1
        return original_clone(owner, state)

    def build_views(directory, read_owners):
        views.update(key.value for key in read_owners)
        return original_views(directory, read_owners)

    def evaluate(item, roots, *, occurrence=None):
        result = original_evaluate(item, roots, occurrence=occurrence)
        if is_wait(item) and roots["actor"].name == "adventurer":
            captured.append((item, dict(roots), occurrence))
        return result

    profiler = cProfile.Profile()
    with ExitStack() as stack:
        if observe:
            stack.enter_context(patch.object(atomic, "_clone_owner_state", clone))
            stack.enter_context(patch.object(atomic, "_build_candidate_owner_views", build_views))
            stack.enter_context(patch.object(value.C0ValueProgram, "evaluate", evaluate))
            stack.callback(profiler.disable)
            profiler.enable()
        started = perf_counter()
        result = session.submit("adventurer", matches[0].entry, dict(matches[0].payload))
        seconds = perf_counter() - started
        if observe:
            profiler.disable()
    if not isinstance(result, K0Published):
        raise ValueError("real wait Action did not publish")
    after = session.author_snapshot()
    previous = dict(before.owners)
    report = {
        "observed": observe,
        "submit_seconds": seconds,
        "before_time": before.time,
        "after_time": after.time,
        "owner_count": len(session._runtime._topology.owners),
        "changed_static_owners": [name for name, state in after.owners if previous[name] != state],
        "new_occurrence_count": len(after.occurrences) - len(before.occurrences),
        "state_digest": _snapshot_digest(after, session._runtime._individual_scope),
        "transaction_clones_by_owner": dict(clones),
        "candidate_read_views_by_owner": dict(views),
    }
    if observe:
        stats = pstats.Stats(profiler)
        report["profile_total_calls"] = stats.total_calls
        report["profile_self_seconds"] = stats.total_tt
        report["top_self"] = [
            {
                "file": key[0],
                "line": key[1],
                "function": key[2],
                "calls": row[1],
                "self_seconds": row[2],
            }
            for key, row in sorted(stats.stats.items(), key=lambda item: item[1][2], reverse=True)[
                :15
            ]
        ]
        if not captured:
            raise ValueError("no real wait evaluation captured")
        report["wait_evaluations"] = [
            {"occurrence": occurrence.value if occurrence is not None else None}
            for _, _, occurrence in captured
        ]
    return report, captured


def _paired_wait_comparison(program, assets, baseline_name, selected_name, control):
    normal = {baseline_name: [], selected_name: []}
    observed = {}
    for trial in range(3):
        order = (baseline_name, selected_name)
        if trial % 2:
            order = tuple(reversed(order))
        for mode in order:
            with control() if mode == baseline_name else nullcontext():
                normal[mode].append(one_wait(program, assets)[0])
    for mode in normal:
        with control() if mode == baseline_name else nullcontext():
            observed[mode] = one_wait(program, assets, observe=True)[0]
    rows = [row for group in normal.values() for row in group] + list(observed.values())
    if len({row["state_digest"] for row in rows}) != 1:
        raise ValueError("diagnostic control changed the normalized snapshot")
    baseline = median(row["submit_seconds"] for row in normal[baseline_name])
    selected = median(row["submit_seconds"] for row in normal[selected_name])
    return {
        "normal_submit": normal,
        "observed_submit": observed,
        f"median_{baseline_name}_seconds": baseline,
        f"median_{selected_name}_seconds": selected,
        "median_reduction_percent": (baseline - selected) / baseline * 100,
    }


def projection_comparison(program, assets):
    report = _paired_wait_comparison(
        program,
        assets,
        "full_menu",
        "selected_entry",
        lambda: patch.object(C0OwnerGraphSession, "_can_project_entry", return_value=False),
    )
    report["boundary"] = "same Program/Assets; force full-menu path only in diagnostic control"
    return report


def _repeat_publication_outputs(self, rule_input):
    """Timing control only; never installed by a production build or Session."""
    evaluation = _SINGLE_ACTION_EVALUATE(self, rule_input)
    outputs = self.program._outputs(rule_input)
    envelope = self.program.envelope_type(
        **{field: outputs[output] for field, output in self.program.envelope_fields}
    )
    envelope.validate_for_k0()
    if envelope != evaluation.envelope:
        raise ValueError("repeated output evaluation changed the semantic envelope")
    return evaluation


_SINGLE_ACTION_EVALUATE = _Rule.evaluate


def action_evaluation_comparison(program, assets):
    report = _paired_wait_comparison(
        program,
        assets,
        "repeated_outputs",
        "single_outputs",
        lambda: patch.object(_Rule, "evaluate", _repeat_publication_outputs),
    )
    report["boundary"] = (
        "same current Program/Assets; repeat removed Action output/envelope work only in "
        "diagnostic control; not a historical binary or whole-game speedup"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=2000)
    comparison = parser.add_mutually_exclusive_group()
    comparison.add_argument("--compare-entry-projection", action="store_true")
    comparison.add_argument("--compare-action-evaluation", action="store_true")
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    started = perf_counter()
    bundle = read_source_bundle(args.bundle)
    program = compile_source_bundle(bundle)
    compile_seconds = perf_counter() - started
    assets = bundle.assets.to_data()
    if args.compare_entry_projection or args.compare_action_evaluation:
        name, compare = (
            ("entry_projection_comparison", projection_comparison)
            if args.compare_entry_projection
            else ("action_evaluation_comparison", action_evaluation_comparison)
        )
        report = {
            "compile_including_load_seconds": compile_seconds,
            name: compare(program, assets),
        }
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return
    normal = [one_wait(program, assets)[0] for _ in range(3)]
    observed, captured = one_wait(program, assets, observe=True)
    if any(row["state_digest"] != observed["state_digest"] for row in normal):
        raise ValueError("observed wait does not have the same normalized snapshot")
    expression, roots, occurrence = captured[-1]
    report = {
        "compile_including_load_seconds": compile_seconds,
        "normal_submit": normal,
        "observed_submit": observed,
        "expression_comparison": expression_comparison(
            expression, roots, occurrence, args.iterations
        ),
        "limitations": [
            "only one real wait; not whole-game or cold-pulse measurement",
            "observer counters cover atomic module calls, not all isolation/validation paths",
            "snapshot digest normalizes local identity scopes; not cross-session authentication",
            "native oracle never replaces the production rule or K0 Session",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
