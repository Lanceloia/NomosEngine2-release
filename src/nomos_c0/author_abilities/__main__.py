"""Inspect checked author declarations; execution consumes generated Python separately."""

import argparse
from pathlib import Path

from nomos_c0.author_contract_v1 import C0LawError

from .assembly import compile_author_files, read_author_modules
from .entity_reads import compile_entity_reads
from .expressions import compile_pure_values
from .value_types import EntitySort, compile_value_types


def show_library(path, *, pure):
    document = read_author_modules(path)
    data = document.to_data()
    entities = data.get("entities", {})
    if (
        type(entities) is not dict
        or "values" not in data
        or any(type(row) is not dict or "kind" not in row for row in entities.values())
    ):
        raise C0LawError("Lib 类型片段需要 values 和正确的 entities sort 声明")
    sorts = tuple(
        EntitySort(name, row["kind"], () if "extends" not in row else (row["extends"],))
        for name, row in entities.items()
    )
    table = compile_value_types(data["values"], sorts=sorts, context=document.context())
    library = None
    if pure:
        reads = compile_entity_reads(table, entities, data.get("relations", {}))
        library = compile_pure_values(
            table, data.get("queries", {}), context=document.context(), entities=reads
        )
    print("TypeTable · 类型声明检查完成")
    for name, value in table.definitions:
        alias = "" if name == value.name else f" -> {value.name}"
        print(f"  {name}{alias}: {value.kind}")
    if library is not None:
        print("PureLibrary · 纯定义检查完成")
        for name, definition in library.definitions:
            arguments = ", ".join(f"{key}: {plan.name}" for key, plan in definition.parameters)
            print(f"  {name}({arguments}) -> {definition.returns.name}")
            print(
                "    reads:",
                ", ".join(
                    read.root + "".join("[]" if step == "[]" else "." + step for step in read.steps)
                    for read in definition.body.reads
                )
                or "none",
            )
            print(
                "    owner reads:",
                ", ".join(
                    f"{read.selector.root if read.selector else '?'}: {read.sort}.{read.field}"
                    + (f" via {read.relation}" if read.relation else "")
                    for read in definition.body.owner_reads
                )
                or "none",
            )


def show_plan(program, controllers):
    if program.random is not None:
        print(f"RandomMechanism<{program.random.mechanism}>")
    for information in program.information:
        print(f"{information.name}: OpeningInformation<{information.projection.value.result.name}>")
    for projection in program.projections:
        print(f"{projection.name}: Projection<{projection.value.result.name}>")
        print("  Context:", projection.context.name)
    if program.terminal is not None:
        terminal = program.terminal
        print(f"{terminal.name}: Terminal<{terminal.value.result.name}>")
        print("  Boundary:", terminal.boundary, "·", terminal.pending)
    for context in program.contexts:
        if context.state is not None:
            print(f"{context.name}: SharedState<{context.definition}>")
            print("  Public:", ", ".join(context.state.public) or "none")
    for activity in program.activities:
        print(f"{activity.completion.name}: Activity<{activity.completion.definition}>")
        print("  Duration:", activity.duration.source.text)
        print("  Cancellation:", "selected" if activity.cancellation else "none")
    for periodic in program.periodic:
        print(f"{periodic.event.name}: Periodic<{periodic.event.definition}>")
        print("  Interval:", periodic.interval, "· First after:", periodic.first_after)
    for schedule in () if program.time is None else program.time.schedules:
        print(f"{schedule.family}: ActorSchedule<{schedule.definition}>")
        print("  Speed:", schedule.speed.source.text, "· Initial:", schedule.initial)
    for strategy in () if controllers is None else controllers.strategies:
        print(f"{strategy.controller}: LocalStrategy<{strategy.definition}>")
    if program.play is not None:
        print(f"PlayMechanism<{program.play.mechanism}>")
    for ability in program.abilities:
        print(
            f"{ability.name}("
            + ", ".join(f"{name}: {sort}" for name, sort in ability.inputs.base)
            + ")"
        )
        print("  Input order:", ", ".join(ability.inputs.order) or "none")
        print("  Result type:", ability.resolution.leaves()[0].result.result.name)
        if ability.epoch is not None:
            print("  Request epoch:", ability.epoch.source.text)
        if ability.process is not None:
            print("  Process point:", ability.process.point)
        print(
            "  Write paths:",
            ", ".join(f"{write.sort}.{write.field}" for write in ability.summary.writes) or "none",
        )
        if ability.summary.context_writes:
            print(
                "  Context writes:", ability.context.name, ", ".join(ability.summary.context_writes)
            )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="检查作者声明；运行使用 nomos_runtime 生成产物入口"
    )
    parser.add_argument("world", nargs="?", type=Path, help="作者文件前缀")
    parser.add_argument("--plan", action="store_true", help="显示编译期能力计划")
    parser.add_argument("--ai", type=Path, help="独立 AI 配置；计划默认检查同前缀 .ai.yaml")
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--types", type=Path, help="检查 Lib 的共同值类型")
    phase.add_argument("--pure", type=Path, help="检查 Lib 类型与纯定义")
    args = parser.parse_args(argv)
    if args.types is not None or args.pure is not None:
        if args.world is not None or args.plan or args.ai is not None:
            parser.error("--types/--pure 是独立编译阶段")
        try:
            show_library(args.types or args.pure, pure=args.pure is not None)
        except (ValueError, OSError) as error:
            parser.exit(2, f"编译阶段检查失败：{error}\n")
        return
    if args.world is None or not args.plan:
        parser.error(
            "作者检查需提供前缀和 --plan；请先用 nomos_c0.python_codegen 构建，"
            "再用 nomos_runtime 运行"
        )
    try:
        program = compile_author_files(
            Path(f"{args.world}.lib.yaml"), Path(f"{args.world}.source.yaml")
        )
        from .strategies import read_controllers

        ai = args.ai or Path(f"{args.world}.ai.yaml")
        controllers = read_controllers(program, ai) if args.ai or ai.exists() else None
    except (ValueError, OSError) as error:
        parser.exit(2, f"编译失败：{error}\n")
    show_plan(program, controllers)


if __name__ == "__main__":
    main()
