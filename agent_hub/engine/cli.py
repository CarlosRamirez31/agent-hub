"""Task namespace: never discover, sync or launch native agents implicitly."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import unicodedata

from ..cache import Cache
from .tasks import COMPLEXITIES, STATES, TaskStore


def clean(value):
    return ''.join(c if not unicodedata.category(c).startswith('C') else ' ' for c in str(value))


def read_contract(path):
    if path == '-':
        content = sys.stdin.read(1024 * 1024 + 1)
    else:
        with Path(path).open(encoding='utf-8') as source:
            content = source.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError('El contrato supera 1 MiB.')
    return json.loads(content)


def parser():
    root = argparse.ArgumentParser(prog='agent-hub task', description='Tareas persistentes, sin iniciar modelos.')
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    common.add_argument('--demo', action='store_true', default=argparse.SUPPRESS, help='estado efímero en memoria')
    root.add_argument('--json', action='store_true')
    root.add_argument('--demo', action='store_true')
    actions = root.add_subparsers(dest='command', required=True)
    create = actions.add_parser('create', parents=[common])
    create.add_argument('--contract', help='JSON UTF-8 o - para stdin')
    create.add_argument('--title')
    create.add_argument('--objective')
    create.add_argument('--complexity', choices=COMPLEXITIES)
    create.add_argument('--agent', help='asignación fixed; no selecciona un reemplazo')
    create.add_argument('--depends-on', action='append', default=[])
    update = actions.add_parser('update', parents=[common])
    update.add_argument('id')
    update.add_argument('--contract', required=True)
    update.add_argument('--reason', required=True)
    listing = actions.add_parser('list', parents=[common])
    listing.add_argument('--status', choices=STATES)
    for name in ('show', 'events'):
        child = actions.add_parser(name, parents=[common])
        child.add_argument('id')
    status = actions.add_parser('status', parents=[common])
    status.add_argument('id')
    status.add_argument('status', choices=STATES)
    status.add_argument('--expected-revision', type=int)
    status.add_argument('--reason')
    depend = actions.add_parser('depend', parents=[common])
    depend.add_argument('id')
    depend.add_argument('dependency')
    depend.add_argument('--remove', action='store_true')
    return root


def main(argv):
    args = parser().parse_args(argv)
    cache = None
    try:
        # No Manager: tasks must work with no agents installed or reachable.
        state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'agent-hub'
        cache = Cache(':memory:' if args.demo else state/'index.sqlite')
        store = TaskStore(cache.conn)
        if args.command == 'create':
            if args.contract:
                if any((args.title, args.objective, args.complexity, args.agent)):
                    raise ValueError('Usa --contract o los campos individuales, no ambos.')
                contract = read_contract(args.contract)
            else:
                title = args.title
                if not title and sys.stdin.isatty():
                    title = input('Título: ').strip()
                    if not title:
                        raise ValueError('Creación cancelada: título vacío.')
                contract = {'title': title, 'objective': args.objective or title}
                if args.complexity:
                    contract['complexity'] = args.complexity
                if args.agent:
                    contract['assignment'] = {'mode': 'fixed', 'agent': args.agent}
            value = store.create(contract, args.depends_on).json()
        elif args.command == 'update':
            value = store.replace_contract(args.id, read_contract(args.contract), args.reason).json()
        elif args.command == 'list':
            value = [task.json() for task in store.list(args.status)]
        elif args.command == 'show':
            value = store.get(args.id).json()
        elif args.command == 'status':
            value = store.status(args.id, args.status, args.expected_revision, args.reason).json()
        elif args.command == 'depend':
            value = store.dependency(args.id, args.dependency, args.remove).json()
        else:
            value = store.events(args.id)
        if args.json:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        elif args.command == 'update':
            value = store.replace_contract(args.id, read_contract(args.contract), args.reason).json()
        elif args.command == 'list':
            for task in value:
                print(clean(f"{task['id']}  {task['status']:18}  {task['contract']['title']}"))
        elif args.command == 'events':
            for event in value:
                print(clean(f"{event['id']}  {event['type']}  {json.dumps(event['payload'], ensure_ascii=False)}"))
        else:
            print(clean(f"{value['id']} · {value['status']} · {value['contract']['title']}"))
            if args.command == 'show':
                print(json.dumps(value, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, EOFError) as error:
        print('agent-hub task: ' + clean(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if cache:
            cache.close()
