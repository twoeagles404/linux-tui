import argparse
import json
import sys
from pathlib import Path
from . import __version__
from .core import ACTIONS, catalog, discover, run_action


def show(value):
    print(json.dumps(value, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Portable Linux administration with full-screen category menus')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--discover', action='store_true', help='Print environment discovery as JSON')
    parser.add_argument('--catalog', action='store_true', help='Print implemented diagnostics and availability')
    parser.add_argument('--run', choices=[action.id for action in ACTIONS], help='Run an allowlisted read-only diagnostic')
    parser.add_argument('--ui', choices=['auto', 'curses'], default='auto', help='Interactive menu backend')
    parser.add_argument('--monitor', action='store_true', help='Run the authenticated read-only web monitor')
    parser.add_argument('--host', default='127.0.0.1', help='Monitor listen address (default: localhost)')
    parser.add_argument('--port', type=int, default=8008, help='Monitor port (default: 8008)')
    parser.add_argument('--monitor-state', type=Path, help='Monitor token and metrics directory')
    args = parser.parse_args()
    if args.monitor:
        if sys.platform != 'linux':
            parser.error('The resource monitor requires Linux.')
        if not 1 <= args.port <= 65535:
            parser.error('--port must be 1–65535')
        from .monitor import serve, DEFAULT_STATE
        try:
            serve(args.host, args.port, args.monitor_state or DEFAULT_STATE)
        except KeyboardInterrupt:
            pass
        except (OSError, ValueError) as error:
            parser.exit(1, str(error) + '\n')
    elif args.discover:
        show(discover())
    elif args.catalog:
        show(catalog())
    elif args.run:
        result = run_action(args.run)
        show(result)
        return 0 if result['ok'] else 1
    elif not sys.stdin.isatty():
        parser.print_help()
    else:
        try:
            if sys.platform != 'linux':
                parser.exit(1, 'Interactive menus require Linux. Use --catalog or --discover for preview.\n')
            from .menus import launch
            return launch(args.ui)
        except (EOFError, KeyboardInterrupt):
            print('\nExited.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
