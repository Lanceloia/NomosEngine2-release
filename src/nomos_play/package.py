"""Package trusted generated Python and opening data, with no author compilation at Run."""

import argparse
import hashlib
import json
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

import yaml

from nomos_runtime.artifacts import load_world
from nomos_runtime.documents import read_data
from nomos_runtime.errors import SettlementDefect
from nomos_runtime.expressions import ExpressionError, ValueBindingError
from nomos_runtime.play import require_controllers

MAX_FILES, MAX_BYTES = 512, 64 * 1024 * 1024
CHECKS = ["artifact", "display", "controllers", "opening"]
LAUNCHER = '''"""Run this generated world using the installed Nomos desktop."""
import argparse
from pathlib import Path
from nomos_play.package import serve_package

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nomos game package")
    parser.add_argument("--port", type=int, default=8860)
    args = parser.parse_args()
    serve_package(Path(__file__).resolve().parent, port=args.port)
'''
README = """# 生成运行包

安装匹配的 NomosEngine2 运行依赖后，从任意工作目录运行：

```bash
python /path/to/package/play.py --port 8860
python -m nomos_play.package check /path/to/package
```

`world.py` 是已编译的规则与显示，`assets.yaml` 是独立开局数据。
运行器验证文件内容与实际开局，随后直接执行生成 Python。
修改作者规则后重新编译、导出；每次 Start 的本局身份和状态独立。
生成文件是受信 Python 代码，运行前请确认其来源。
世界资产及其改编许可遵循作者声明；引擎和前端由安装的运行依赖提供。
"""


def relative(root, name):
    if type(name) is not str or not name or "\\" in name:
        raise ValueError("package paths require POSIX-relative names")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", "..", ".") for part in name.split("/")):
        raise ValueError("package path escapes its directory")
    result = (root / path).resolve()
    if not result.is_relative_to(root):
        raise ValueError("package path resolves outside its directory")
    return result


def validated_world(world):
    program, assets, display, controllers = world
    if program.play is None or program.play.mechanism != "tabletop" or display is None:
        raise ValueError("playable package requires generated tabletop rules and display")
    require_controllers(program.start(assets, controllers=controllers), None)
    return program, assets, display, controllers


def export_package(world, assets, output):
    world, assets = Path(world).resolve(), Path(assets).resolve()
    output = Path(output).absolute()
    output = output.parent.resolve() / output.name
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists; choose a new package directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".nomos-package-", dir=output.parent) as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir()
        (stage / "world.py").write_bytes(world.read_bytes())
        (stage / "assets.yaml").write_bytes(assets.read_bytes())
        with load_world(stage / "world.py") as module:
            loaded = validated_world(
                (
                    module.PROGRAM,
                    read_data(stage / "assets.yaml"),
                    module.DISPLAY,
                    module.CONTROLLERS,
                )
            )
            name = loaded[2].specification["title"]
        (stage / "play.py").write_text(LAUNCHER, encoding="utf-8")
        (stage / "README.md").write_text(README, encoding="utf-8")
        records = []
        for file in sorted(stage.iterdir()):
            content = file.read_bytes()
            records.append(
                {
                    "path": file.name,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        if sum(record["bytes"] for record in records) > MAX_BYTES:
            raise ValueError("playable package byte budget exceeded")
        manifest = {
            "schema": "nomos.play.package",
            "name": name,
            "world": "world.py",
            "assets": "assets.yaml",
            "engine": {"distribution": "nomos-engine2", "version": version("nomos-engine2")},
            "checks": CHECKS,
            "files": records,
        }
        (stage / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        output.mkdir()
        try:
            stage.rename(output)
        except OSError:
            output.rmdir()
            raise
    return manifest


def manifest_at(directory):
    root = Path(directory).resolve()
    manifest = read_data(relative(root, "manifest.yaml"))
    if (
        set(manifest) != {"schema", "name", "world", "assets", "engine", "checks", "files"}
        or manifest["schema"] != "nomos.play.package"
    ):
        raise ValueError("expected generated nomos.play.package manifest")
    if (
        type(manifest["name"]) is not str
        or not manifest["name"].strip()
        or manifest["checks"] != CHECKS
    ):
        raise ValueError("invalid package name or check declaration")
    engine = manifest["engine"]
    if (
        type(engine) is not dict
        or set(engine) != {"distribution", "version"}
        or engine["distribution"] != "nomos-engine2"
        or type(engine["version"]) is not str
        or not engine["version"].strip()
    ):
        raise ValueError("invalid engine dependency")
    records = manifest["files"]
    if type(records) is not list or not 1 <= len(records) <= MAX_FILES:
        raise ValueError("invalid package file list")
    declared, total = set(), 0
    for record in records:
        if type(record) is not dict or set(record) != {"path", "bytes", "sha256"}:
            raise ValueError("invalid package file record")
        file = relative(root, record["path"])
        if record["path"] in declared or record["path"] == "manifest.yaml":
            raise ValueError("duplicate or reserved package file")
        declared.add(record["path"])
        size = record["bytes"]
        if type(size) is not int or size < 0 or file.stat().st_size != size:
            raise ValueError("package size changed: " + record["path"])
        total += size
        if total > MAX_BYTES or hashlib.sha256(file.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("package content changed: " + record["path"])
    relative(root, manifest["world"])
    relative(root, manifest["assets"])
    if not {manifest["world"], manifest["assets"], "play.py", "README.md"} <= declared:
        raise ValueError("package entry files missing")
    return manifest


@contextmanager
def _loaded_package(directory):
    root = Path(directory).resolve()
    manifest = manifest_at(root)
    with load_world(relative(root, manifest["world"])) as module:
        yield (
            manifest,
            (
                module.PROGRAM,
                read_data(relative(root, manifest["assets"])),
                module.DISPLAY,
                module.CONTROLLERS,
            ),
        )


@contextmanager
def check_package(directory):
    with _loaded_package(directory) as (manifest, world):
        yield manifest, validated_world(world)


def serve_package(directory, *, port=8860):
    from .catalog import GameCatalog, GameEntry
    from .server import make_server

    root = Path(directory).resolve()
    manifest = manifest_at(root)

    @contextmanager
    def loader(entry):
        with _loaded_package(root) as (_, world):
            yield world

    entry = GameEntry(
        "game", manifest["name"], "", root / manifest["world"], root / manifest["assets"]
    )
    server = make_server(GameCatalog([entry], loader), port)
    print(f"{manifest['name']}：http://127.0.0.1:{server.server_address[1]}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="打包与检查生成的桌游")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("world", type=Path)
    export.add_argument("assets", type=Path)
    export.add_argument("output", type=Path)
    check = commands.add_parser("check")
    check.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "export":
            manifest = export_package(args.world, args.assets, args.output)
        else:
            with check_package(args.directory) as (manifest, _):
                pass
    except (ValueError, OSError, ValueBindingError, ExpressionError, SettlementDefect) as error:
        parser.exit(2, f"运行包检查失败：{error}\n")
    print(
        json.dumps(
            {
                "name": manifest["name"],
                "files": len(manifest["files"]),
                "checks": manifest["checks"],
                "engine": manifest["engine"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
