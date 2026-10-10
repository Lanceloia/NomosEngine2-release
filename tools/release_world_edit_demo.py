"""Capture existing role and participant edits through real C0/K0 sessions."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import nomos_kernel
import yaml
from nomos_kernel._settlement_outcome_abi import K0Published

import nomos_c0
import nomos_t0
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_t0.witness_v0 import _trace_row

HERE = Path(__file__).resolve().parents[1]
INPUTS = HERE / "docs/showcase/world-edits"


def move_witch(assets):
    changed = deepcopy(assets)
    opening = changed["opening"]
    expected = {"B": "witch", "E": "villager"}
    for name, role in expected.items():
        rows = [row for row in opening["scene"]["roles"] if row["id"] == name]
        actor = opening[name.lower()]
        if len(rows) != 1 or rows[0]["role"] != role or actor["own_role"] != role:
            raise ValueError("expected B witch and E villager opening")
        if actor["healing_available"] is not (role == "witch"):
            raise ValueError("role and healing supply must agree")
        replacement = "villager" if name == "B" else "witch"
        rows[0]["role"] = actor["own_role"] = replacement
        actor["healing_available"] = replacement == "witch"
    return changed


def add_participants(source, assets):
    changed_source, changed_assets = deepcopy(source), deepcopy(assets)
    domain = changed_source["actor_domains"][0]
    opening = changed_assets["opening"]
    if domain["name"] != "participants" or domain["owners"] != list("abcdef"):
        raise ValueError("expected the declared six-person participant domain")
    if [row["id"] for row in opening["scene"]["players"]] != list("ABCDEF"):
        raise ValueError("expected the matching six-person opening")
    domain["owners"].extend(["g", "h"])
    for name in "GH":
        if name.lower() in opening:
            raise ValueError("new participant already has an opening")
        opening["scene"]["players"].append({"id": name, "alive": True})
        opening["scene"]["roles"].append({"id": name, "role": "villager"})
        actor = deepcopy(opening["f"])
        actor.update(name=name, own_role="villager", healing_available=False)
        opening[name.lower()] = actor
    return changed_source, changed_assets


def start(lib, ports, source, assets):
    nominal = check_nominal_lib(lib, source["actor_domains"])
    program = compile_owner_graph(check_graph_ports(ports, nominal), source)
    return program.start(deepcopy(assets))


def checkpoint(session):
    snapshot = session.author_snapshot()
    seats = {}
    for seat in session.program.seats:
        if session.offer_faults(seat.symbol):
            raise ValueError(f"offer projection fault for {seat.symbol}")
        seats[seat.symbol] = {
            "read": dict(asdict(session.read(seat.symbol))["fields"]),
            "offers": [{"entry": row.entry, "label": row.label, "payload": dict(row.payload)}
                       for row in session.offers(seat.symbol)],
        }
    return {
        "seats": seats,
        "owners": {name: asdict(owner) for name, owner in snapshot.owners},
        "published": [asdict(_trace_row(row)) for row in snapshot.occurrences],
    }


def request(session, seat, label):
    matches = [row for row in session.offers(seat) if row.label == label]
    if session.offer_faults(seat) or len(matches) != 1:
        raise ValueError(f"no unique current offer: {seat} / {label}")
    offer = matches[0]
    result = session.submit(seat, offer.entry, dict(offer.payload))
    if not isinstance(result, K0Published):
        raise ValueError(f"K0 did not publish {seat} / {label}")
    return {"seat": seat, "label": label, "entry": offer.entry,
            "payload": dict(offer.payload),
            "published": [asdict(_trace_row(row)) for row in result.occurrences]}


def role_version(lib, ports, source, assets, prefix, healer):
    session = start(lib, ports, source, assets)
    actions = [request(session, row["seat"], row["label"]) for row in prefix]
    ready = checkpoint(session)
    # Observe the missing candidate without issuing a forged or automatic action.
    before = session.author_snapshot()
    b_offers = [row.label for row in session.offers("B")]
    missing = "Save victim" not in b_offers
    if session.author_snapshot() != before:
        raise ValueError("read-only offer lookup changed the world")
    actions.append(request(session, healer, "Save victim"))
    return {"actions": actions, "before_save": ready, "after_save": checkpoint(session),
            "B_candidate_check": {"offer_found": not missing, "submitted": False}}


def size_version(lib, ports, source, assets, requests):
    session = start(lib, ports, source, assets)
    opening = checkpoint(session)
    actions = [request(session, row["seat"], row["label"]) for row in requests]
    return {"opening": opening, "actions": actions, "after_votes": checkpoint(session)}


def validate(report):
    roles = report["role_move"]
    for key, healer, other in (("witch_B", "B", "E"), ("witch_E", "E", "B")):
        version = roles[key]
        ready, after = version["before_save"], version["after_save"]
        own = ready["seats"][healer]["read"]
        notice = own[f"{healer.lower()}.witch_notice"]
        choice = after["owners"][healer.lower()]["witch_choices"][0]
        if not (
            len(version["actions"]) == 10 and len(after["published"]) == 14
            and notice["target"] == "B"
            and f"{other.lower()}.witch_notice" not in ready["seats"][other]["read"]
            and "scene.pending_attack" not in ready["seats"][other]["read"]
            and {row["label"] for row in ready["seats"][healer]["offers"]}
            == {"Save victim", "Do not heal"}
            and ready["seats"][other]["offers"] == []
            and after["owners"]["scene"]["phase"] == "day"
            and after["owners"]["scene"]["last_death"] is None
            and after["owners"][healer.lower()]["healing_available"] is False
            and choice["saved"] is True and choice["target"] == "B"
            and choice["action"]["value"]
            == version["actions"][-1]["published"][0]["occurrence"]
            and version["actions"][-1]["published"][0]["source"]
            == f"c0.six-seat.witch-{healer.lower()}"
            and [row for action in version["actions"] for row in action["published"]]
            == after["published"]
        ):
            raise ValueError("role evidence does not support the claim")
    left, right = roles["witch_B"], roles["witch_E"]
    if [(row["seat"], row["entry"], row["payload"]) for row in left["actions"][:9]] != [
        (row["seat"], row["entry"], row["payload"]) for row in right["actions"][:9]
    ] or right["B_candidate_check"] != {"offer_found": False, "submitted": False}:
        raise ValueError("role comparison changed the prefix or submitted the missing offer")
    for key, members in (("six", "ABCDEF"), ("eight", "ABCDEFGH")):
        version = report["size_change"][key]
        opening = version["opening"]
        if set(opening["seats"]) != set(members) or set(opening["owners"]) != {
            "scene", *members.lower()
        }:
            raise ValueError("participant seats or independent owners are missing")
        for seat in members:
            own = opening["seats"][seat]
            if not (
                own["read"][f"{seat.lower()}.name"] == seat
                and "scene.roles" not in own["read"]
                and {row["payload"]["target"] for row in own["offers"]} == set(members)
            ):
                raise ValueError("participant local view or targets are wrong")
    eight = report["size_change"]["eight"]
    actors = eight["after_votes"]["owners"]
    if not (
        len(eight["after_votes"]["published"]) == 2
        and actors["a"]["votes"][0]["target"] == "H"
        and actors["g"]["votes"][0]["target"] == "A"
        and not actors["h"]["votes"]
        and actors["a"]["votes"][0]["action"]["value"] == 1
        and actors["g"]["votes"][0]["action"]["value"] == 2
        and eight["actions"][1]["published"][0]["source"] == "c0.six-seat.vote-g"
    ):
        raise ValueError("new participant did not make the recorded real vote")


def compare(lib, ports, source, assets, requests):
    moved = move_witch(assets)
    expanded_source, expanded_assets = add_participants(source, assets)
    report = {
        "role_move": {
            "witch_B": role_version(lib, ports, source, assets, requests["role_prefix"], "B"),
            "witch_E": role_version(lib, ports, source, moved, requests["role_prefix"], "E"),
        },
        "size_change": {
            "six": size_version(lib, ports, source, assets, requests["six_votes"]),
            "eight": size_version(lib, ports, expanded_source, expanded_assets,
                                  requests["eight_votes"]),
        },
    }
    validate(report)
    return report, {
        "six.source.yaml": source, "eight.source.yaml": expanded_source,
        "witch-B.assets.yaml": assets, "witch-E.assets.yaml": moved,
        "eight.assets.yaml": expanded_assets,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--record", type=Path, help="save to a new directory, never overwrite")
    args = parser.parse_args(argv)
    if args.record is not None and args.record.exists():
        parser.error("evidence directory already exists")
    modules = (nomos_c0, nomos_t0, nomos_kernel)
    if args.record is not None and any(
        not Path(module.__file__).resolve().is_relative_to(HERE) for module in modules
    ):
        parser.error("run with C0/T0/K0 installed from this checkout")
    examples = Path(nomos_c0.__file__).resolve().parent / "examples"
    paths = {
        "lib": examples / "three_seat_werewolf_v0.lib.yaml",
        "ports": examples / "three_seat_werewolf_v0.ports.yaml",
        "source": examples / "six_seat_werewolf_v0.source.yaml",
        "assets": (Path(nomos_t0.__file__).resolve().parent
                   / "examples/werewolf_witch_b.assets.yaml"),
        "requests": INPUTS / "actions.yaml",
    }
    before = {name: path.read_bytes() for name, path in paths.items()}
    data = {name: read_author_document(path).to_data() for name, path in paths.items()}
    report, effective = compare(**data)
    if any(path.read_bytes() != before[name] for name, path in paths.items()):
        raise ValueError("authored inputs changed during capture")
    if args.record is not None:
        args.record.mkdir(parents=True, exist_ok=False)
        raw = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        (args.record / "result.json").write_text(raw, encoding="utf-8")
        for name, value in effective.items():
            (args.record / name).write_text(
                yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
        files = [Path(__file__)]
        for root in ("src/nomos_c0", "src/nomos_t0", "engine/kernel/src/nomos_kernel"):
            files.extend((HERE / root).rglob("*.py"))
        manifest = {
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "code_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=HERE, text=True).strip(),
            "capture_worktree_changes": subprocess.check_output(
                ["git", "status", "--short"], cwd=HERE, text=True).splitlines(),
            "python_version": sys.version,
            "module_origins": {module.__name__: module.__file__ for module in modules},
            "code_files_sha256": {str(path.relative_to(HERE)):
                                  hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in sorted(files)},
            "inputs": {name: {"path": str(paths[name]), "sha256": hashlib.sha256(raw).hexdigest()}
                       for name, raw in before.items()},
            "artifacts_sha256": {name: hashlib.sha256((args.record / name).read_bytes()).hexdigest()
                                 for name in ("result.json", *effective)},
            "inputs_modified": False,
            "note": "Trusted author audit, not player access or authenticated provenance.",
        }
        (args.record / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("换职业 B → E：通知与救人选项移到 E，真实行动来源 witch-e；B 旧选项消失。")
        print("扩人数 6 → 8：G/H 各有本人视图和八个投票目标；A 投 H，G 投 A，真实发布。")
        print("仅编辑开局／参与者声明；Lib 和 Ports 未修改，不写入世界结果。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
