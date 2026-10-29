"""Launch only on IPv4 loopback, never on a public interface."""

import argparse
import multiprocessing
import threading
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="Local TradingAgents research dashboard")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        import uvicorn

        from tradingagents.web.app import create_app
    except ModuleNotFoundError as exc:
        if exc.name in ("fastapi", "uvicorn", "starlette", "markdown_it"):
            parser.exit(1, 'Install dashboard dependencies with: pip install ".[web]"\n')
        raise
    multiprocessing.freeze_support()
    if not args.no_browser:
        timer = threading.Timer(1, webbrowser.open, args=(f"http://127.0.0.1:{args.port}",))
        timer.daemon = True
        timer.start()
    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=args.port,
        workers=1,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
