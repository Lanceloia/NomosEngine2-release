"""Observe owner validation identities without skipping or replacing callbacks."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from nomos_kernel import _owner_state_runtime as owners

from nomos_c0.declarative_nominal_v0 import _DeclaredOwner
from nomos_c0.program_runtime_v1 import C0OwnerGraphSession
from tools.c0_benchmark_m1_continue import measure


class _Operation:
    def __init__(self, serial, kind, parent, owner, state):
        self.serial, self.kind, self.parent = serial, kind, parent
        self.references = {}
        self.input = self.token(state)
        self.token(owner)
        self.calls = []

    def token(self, value):
        key = id(value)
        prior = self.references.get(key)
        if prior is None:
            prior = (value, len(self.references) + 1)
            self.references[key] = prior
        assert prior[0] is value
        return prior[1]


class ValidationShadow:
    """Thread-local diagnostic observer; records calls, not validation success."""

    def __init__(self, *, run_codes=(), sample_limit=8):
        if type(sample_limit) is not int or sample_limit < 0:
            raise ValueError("sample limit must be a nonnegative integer")
        self.run_codes = tuple(run_codes)
        self.run_code_ids = frozenset(id(code) for code in self.run_codes)
        self.sample_limit = sample_limit
        self.operations = []
        self.run_frames = set()
        self.validation_frames = {}
        self.samples = []
        self.patterns = Counter()
        self.counts = Counter()
        self.serial = 0
        self.active = False
        self.used = False
        self.callback = self._observe
        self.operation_codes = {
            id(owners._isolate_candidate_owner_state.__code__): (
                owners._isolate_candidate_owner_state.__code__,
                "isolate",
            ),
            id(owners._clone_owner_state.__code__): (owners._clone_owner_state.__code__, "clone"),
        }
        self.validation_code = _DeclaredOwner.validate_state.__code__
        phase_codes = {
            owners._isolate_candidate_owner_state.__code__: "kernel_isolate",
            owners._clone_owner_state.__code__: "kernel_clone",
            _DeclaredOwner.isolate_candidate_state.__code__: "c0_isolate",
            _DeclaredOwner.read_view.__code__: "c0_read_view",
            _DeclaredOwner.encode_state.__code__: "c0_encode",
            _DeclaredOwner.decode_state.__code__: "c0_decode",
        }
        self.phases = {id(code): (code, phase) for code, phase in phase_codes.items()}

    def __enter__(self):
        if self.used or sys.getprofile() is not None:
            raise RuntimeError(
                "shadow observer requires a fresh instance and an empty profiler slot"
            )
        self.used = self.active = True
        sys.setprofile(self.callback)
        return self

    def __exit__(self, *errors):
        replaced = sys.getprofile() is not self.callback
        if not replaced:
            sys.setprofile(None)
        self.active = False
        self.operations.clear()
        self.run_frames.clear()
        self.validation_frames.clear()
        if replaced:
            raise RuntimeError("shadow profiler was replaced during observation")

    def _observe(self, frame, event, arg):
        if event not in ("call", "return"):
            return
        code = frame.f_code
        code_id = id(code)
        if code_id in self.run_code_ids:
            if event == "call":
                self.run_frames.add(frame)
            else:
                self.run_frames.discard(frame)
        if self.run_codes and not self.run_frames:
            return
        if event == "call":
            if code_id in self.operation_codes:
                local = frame.f_locals
                self.serial += 1
                parent = self.operations[-1][1].serial if self.operations else None
                operation = _Operation(
                    self.serial,
                    self.operation_codes[code_id][1],
                    parent,
                    local["owner"],
                    local["state"],
                )
                self.operations.append((frame, operation))
            elif code is self.validation_code:
                self.counts["owner_validation_calls"] += 1
                if not self.operations:
                    self.counts["outside_operation_calls"] += 1
                    return
                local = frame.f_locals
                operation = self.operations[-1][1]
                call = {
                    "owner": operation.token(local["self"]),
                    "state": operation.token(local["state"]),
                    "phase": self.phases.get(id(frame.f_back.f_code), (None, "other"))[1],
                    "direct_callees": [],
                }
                operation.calls.append(call)
                self.validation_frames[frame] = (operation, call)
            else:
                parent = self.validation_frames.get(frame.f_back)
                if parent is not None:
                    operation, call = parent
                    # This is executed code identity, not callable purity or a dependency proof.
                    call["direct_callees"].append((operation.token(code), code.co_qualname))
        else:
            self.validation_frames.pop(frame, None)
            if self.operations and self.operations[-1][0] is frame:
                _, operation = self.operations.pop()
                self._finish(operation, arg)

    def _finish(self, operation, result):
        calls = operation.calls
        pairs = {(row["owner"], row["state"]) for row in calls}
        implementations = {
            (row["owner"], row["state"], tuple(row["direct_callees"])) for row in calls
        }
        self.counts[f"{operation.kind}_operations"] += 1
        self.counts["scoped_owner_validation_calls"] += len(calls)
        self.counts["same_owner_state_reentries"] += len(calls) - len(pairs)
        self.counts["same_owner_state_code_reentries"] += len(calls) - len(implementations)
        output = None if result is None else operation.token(result)
        if output is not None and output != operation.input:
            self.counts["distinct_output_operations"] += 1
        pattern = (
            operation.kind,
            output is not None,
            tuple(
                (row["phase"], row["owner"], row["state"], tuple(row["direct_callees"]))
                for row in calls
            ),
        )
        self.patterns[pattern] += 1
        if len(self.samples) < self.sample_limit:
            self.samples.append(
                {
                    "operation": operation.serial,
                    "kind": operation.kind,
                    "parent": operation.parent,
                    "input": operation.input,
                    "output": output,
                    "calls": calls,
                }
            )
        operation.references.clear()

    def report(self):
        if self.active or self.operations or self.validation_frames:
            raise RuntimeError("finish observation before reading its report")
        return {
            "schema": "c0.validation-shadow.v1",
            "coverage": "registered C0 owner validate_state calls inside selected Python thread",
            "counts": dict(self.counts),
            "patterns": [
                {
                    "kind": key[0],
                    "value_returned": key[1],
                    "calls": [
                        {"phase": phase, "owner": owner, "state": state, "direct_callees": callees}
                        for phase, owner, state, callees in key[2]
                    ],
                    "operations": amount,
                }
                for key, amount in self.patterns.most_common()
            ],
            "samples": self.samples,
            "qualification": "none; repeated calls are not permission to skip validation",
            "limits": [
                "An observed return does not distinguish a void success from exception unwinding.",
                "Code identity does not prove callable closure, metadata or state stability.",
                "Bookkeeping changes measured overhead; elapsed time is not normal runtime speed.",
                "Numbers identify objects only within one operation and are not world identities.",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    observer = ValidationShadow(
        run_codes=(C0OwnerGraphSession.continue_form.__code__, C0OwnerGraphSession.submit.__code__)
    )
    benchmark = measure(args.bundle, run_observer=observer)
    report = {"shadow_instrumented": True, "benchmark": benchmark, "shadow": observer.report()}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["shadow"]["counts"], indent=2))


if __name__ == "__main__":
    main()
