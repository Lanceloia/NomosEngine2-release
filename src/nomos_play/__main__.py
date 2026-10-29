"""Command-line startup for the local tabletop server."""

import argparse
from pathlib import Path

from . import server as http_server
from .catalog import GameCatalog, GameEntry


def main():
    parser = argparse.ArgumentParser(description="Nomos 桌游：规则编译后直接游玩")
    parser.add_argument("world", nargs="?", type=Path, help="已生成的 Python 世界文件")
    parser.add_argument("--assets", type=Path, help="独立开局数据文件")
    parser.add_argument("--catalog", type=Path, help="游戏目录配置，默认使用内置四桌游目录")
    parser.add_argument("--port", type=int, default=8860)
    args = parser.parse_args()
    if args.world is not None and args.catalog is not None:
        parser.error("请选择单个 Python 产物或 --catalog")
    if (args.world is None) != (args.assets is None):
        parser.error("单个 Python 产物必须配合 --assets")
    try:
        catalog = (
            GameCatalog(
                [GameEntry("game", "打开桌游", "", args.world.resolve(), args.assets.resolve())]
            )
            if args.world is not None
            else GameCatalog.read(args.catalog or Path(__file__).with_name("games.yaml"))
        )
        server = http_server.make_server(catalog, args.port)
    except (ValueError, OSError) as error:
        parser.exit(2, f"桌游启动失败：{error}\n")
    print(f"Nomos 桌游：http://127.0.0.1:{server.server_address[1]}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
