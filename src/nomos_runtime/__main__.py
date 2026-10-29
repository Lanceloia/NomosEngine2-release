"""Open a trusted generated Python world and independent opening data."""

import argparse
from pathlib import Path

from .artifacts import load_world
from .documents import read_data
from .errors import AdmissionError, SettlementDefect
from .expressions import ExpressionError, ValueBindingError
from .terminal import OutputError, Terminal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", type=Path, help="generated world.py")
    parser.add_argument("--assets", type=Path, required=True, help="independent opening YAML/JSON")
    parser.add_argument(
        "--actor", help="opening actor; default is the declared player or first actor"
    )
    parser.add_argument("--manual", action="store_true", help="trusted all-Actor debugging")
    args = parser.parse_args(argv)
    try:
        with load_world(args.world) as world:
            try:
                session = world.PROGRAM.start(read_data(args.assets), controllers=world.CONTROLLERS)
                terminal = Terminal(session, actor=args.actor, manual=args.manual)
            except (
                OSError,
                ValueError,
                ValueBindingError,
                ExpressionError,
                AdmissionError,
            ) as error:
                parser.exit(2, f"开局失败：{error}\n")
            try:
                terminal.run()
            except SettlementDefect as error:
                parser.exit(4, f"结算缺陷，本次会话已停止：{error}\n")
            except OutputError as error:
                parser.exit(3, f"{error}\n")
            except (ValueError, AdmissionError, ExpressionError, ValueBindingError) as error:
                parser.exit(3, f"运行读取失败：{error}\n")
    except (OSError, ValueError, ImportError, SyntaxError) as error:
        parser.exit(2, f"产物加载失败：{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
