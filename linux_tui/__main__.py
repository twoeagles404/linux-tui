import argparse
import json
import sys
from . import __version__
from .core import ACTIONS, catalog, discover, run_action


def show(value):
    print(json.dumps(value, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Portable Linux TUI — read-only foundation')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--discover', action='store_true', help='Print environment discovery as JSON')
    parser.add_argument('--catalog', action='store_true', help='Print implemented diagnostics and availability')
    parser.add_argument('--run', choices=[action.id for action in ACTIONS], help='Run an allowlisted read-only diagnostic')
    args = parser.parse_args()
    if args.discover:
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
            while True:
                print('\nLinux TUI | 0.1.0 | read-only foundation\n')
                print('d. Environment discovery')
                for index, action in enumerate(catalog(), 1):
                    reason = action['unavailable_reason']
                    suffix = f' [unavailable: {reason}]' if reason else ''
                    print(f"{index:2}. {action['category']} / {action['title']}{suffix}")
                choice = input('\nChoose a diagnostic, d, or q: ').strip().lower()
                if choice == 'q':
                    break
                if choice == 'd':
                    show(discover())
                elif choice.isdigit() and 1 <= int(choice) <= len(ACTIONS):
                    show(run_action(ACTIONS[int(choice) - 1].id))
                else:
                    print('Choose one of the listed entries.')
        except (EOFError, KeyboardInterrupt):
            print('\nExited.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
