import argparse
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="haven",
        description="Haven - 个人慢病管理智能体",
    )
    subparsers = parser.add_subparsers(dest="command")

    web_parser = subparsers.add_parser("web", help="启动 Web 交互界面")
    web_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="绑定地址（默认 127.0.0.1）",
    )
    web_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="绑定端口（默认 8000）",
    )
    web_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="不自动打开浏览器",
    )

    args = parser.parse_args()

    if args.command == "web":
        if not args.no_browser:
            webbrowser.open(f"http://{args.host}:{args.port}")
        uvicorn.run(
            "haven.interface.app:app",
            host=args.host,
            port=args.port,
            reload=False,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()