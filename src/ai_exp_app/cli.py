"""Operate the same workspace as the desktop app, without a browser."""
import argparse
import json
import sys
import urllib.error
from pathlib import Path
from urllib.parse import quote

from .client import APIError, Client
from .config import Config


class ConfirmationRequired(Exception):
    pass


def document(path):
    try:
        text = sys.stdin.read() if path == '-' else Path(path).expanduser().read_text(encoding='utf-8')
    except OSError as exc:
        raise ValueError('Cannot read input file: ' + str(exc)) from exc
    return json.loads(text)


def confirm(args, message):
    if getattr(args, 'yes', False):
        return
    if not sys.stdin.isatty():
        raise ConfirmationRequired(message + '; use --yes after reviewing the target')
    if input(message + ' [y/N] ').strip().lower() not in {'y', 'yes'}:
        raise ConfirmationRequired('Cancelled')


def output(value, args):
    path = getattr(args, 'output', None)
    if isinstance(value, bytes) and not path:
        raise ValueError('Binary exports require --output PATH')
    if path:
        target = Path(path).expanduser()
        if target.exists() and not getattr(args, 'force', False):
            raise ValueError('Output already exists; use a new path or --force')
        data = value if isinstance(value, bytes) else (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)) + '\n'
        try:
            with target.open('wb' if isinstance(data, bytes) else 'w', **({} if isinstance(data, bytes) else {'encoding': 'utf-8'})) as stream:
                stream.write(data)
        except OSError as exc:
            raise ValueError('Cannot write output file: ' + str(exc)) from exc
        print(json.dumps({'output': str(target.resolve())}, ensure_ascii=False))
    elif isinstance(value, str) and not args.json:
        print(value, end='' if value.endswith('\n') else '\n')
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def parser():
    root = argparse.ArgumentParser(description=__doc__, epilog='Exit codes: 0 success, 2 input, 3 connection/service, 4 API error, 5 confirmation required/cancelled.')
    root.add_argument('--url', help='Connect to an existing localhost service instead of starting the shared service')
    root.add_argument('--json', action='store_true', help='Print machine-readable JSON (also accepted after a subcommand)')
    groups = root.add_subparsers(dest='group', required=True)

    def group(name, description):
        command = groups.add_parser(name, help=description)
        return command.add_subparsers(dest='action', required=True)

    def leaf(commands, name, description, identities=(), export=False, dangerous=False):
        command = commands.add_parser(name, help=description)
        command.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
        for identity in identities:
            command.add_argument(identity)
        if export:
            command.add_argument('--output', '-o'); command.add_argument('--force', action='store_true')
        if dangerous:
            command.add_argument('--yes', action='store_true', help='Confirm this specific action without an interactive prompt')
        return command

    commands = group('service', 'Manage the shared local service')
    leaf(commands, 'run', 'Run the local service in the foreground')
    leaf(commands, 'start', 'Start or reuse the shared service')
    leaf(commands, 'status', 'Inspect without starting a service')
    leaf(commands, 'stop', 'Stop the local service; remote training continues', dangerous=True)
    command = groups.add_parser('desktop', help='Open the independent desktop window')
    command.add_argument('--smoke-test', help=argparse.SUPPRESS)
    command.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    commands = group('config', 'Inspect or update private workspace settings')
    leaf(commands, 'show', 'Show settings and their file location')
    command = leaf(commands, 'set', 'Merge a JSON settings object'); command.add_argument('--file', required=True)
    command = groups.add_parser('doctor', help='Check local health/settings; optionally verify cloud access')
    command.add_argument('--remote', action='store_true'); command.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    command = groups.add_parser('install-agent', help='Deploy the remote agent using private workspace settings')
    command.add_argument('--read-only', action='store_true'); command.add_argument('--json', action='store_true', default=argparse.SUPPRESS)

    commands = group('project', 'Manage cloud code directories and integrations')
    leaf(commands, 'list', 'List registered projects')
    command = leaf(commands, 'add', 'Register a remote code directory'); command.add_argument('--name', required=True); command.add_argument('--path', required=True); command.add_argument('--alias'); command.add_argument('--config-file')
    command = leaf(commands, 'update', 'Update project fields', ('project_id',)); command.add_argument('--file', required=True)
    leaf(commands, 'remove', 'Remove a project from favorites', ('project_id',), dangerous=True)
    leaf(commands, 'inspect', 'Inspect code and Git metadata', ('project_id',))
    command = leaf(commands, 'schema', 'Read parameter definitions', ('project_id',)); command.add_argument('--ref'); command.add_argument('--cached', action='store_true')
    commands = group('preset', 'Manage named parameter groups')
    leaf(commands, 'list', 'List parameter groups', ('project_id',))
    command = leaf(commands, 'save', 'Create or replace a group', ('project_id',)); command.add_argument('--name', required=True); command.add_argument('--file', required=True); command.add_argument('--id')
    command = leaf(commands, 'import', 'Import and repair a JSON parameter group', ('project_id',)); command.add_argument('--file', required=True); command.add_argument('--name')
    command = leaf(commands, 'export', 'Export JSON or Markdown', ('project_id', 'preset_id'), export=True); command.add_argument('--format', choices=['json', 'md'], default='json')
    leaf(commands, 'delete', 'Delete a parameter group', ('project_id', 'preset_id'), dangerous=True)

    commands = group('run', 'Submit, inspect and control training')
    leaf(commands, 'list', 'List monitored experiments')
    leaf(commands, 'show', 'Show one experiment', ('run_id',))
    for action in ('start', 'queue'):
        command = leaf(commands, action, 'Submit from JSON, a preset, or last-used parameters', ('project_id',))
        source = command.add_mutually_exclusive_group(); source.add_argument('--parameters'); source.add_argument('--preset'); command.add_argument('--name'); command.add_argument('--ref'); command.add_argument('--set', action='append', default=[], metavar='NAME=JSON_OR_TEXT')
    command = leaf(commands, 'resume', 'Load verified remote history and submit a strict resume', ('history_id',)); command.add_argument('--queue', action='store_true'); command.add_argument('--name')
    for action in ('stop', 'pause'):
        command = leaf(commands, action, 'Confirm stopping the selected process', ('run_id',), dangerous=True); command.add_argument('--pause-queue', action='store_true')
    leaf(commands, 'adopt', 'Adopt a verified external process', ('run_id',))
    leaf(commands, 'remove', 'Hide an ended monitor record', ('run_id',), dangerous=True)
    command = leaf(commands, 'log', 'Read the experiment log', ('run_id',), export=True); command.add_argument('--offset', type=int, default=0)
    commands = group('queue', 'Inspect and reorder the queue')
    leaf(commands, 'list', 'Show queue and revision')
    leaf(commands, 'pause', 'Pause scheduling')
    leaf(commands, 'resume', 'Resume scheduling')
    command = leaf(commands, 'order', 'Replace the order with every queued run ID'); command.add_argument('run_ids', nargs='+')
    leaf(commands, 'remove', 'Remove a queued experiment', ('run_id',), dangerous=True)
    commands = group('history', 'Manage cached experiments and their sources')
    leaf(commands, 'list', 'List imported experiments')
    command = leaf(commands, 'import', 'Import one local or remote run'); command.add_argument('--source', choices=['local', 'remote'], default='local'); command.add_argument('--path', required=True); command.add_argument('--alias'); command.add_argument('--name')
    leaf(commands, 'sync', 'Refresh imported histories from their sources')
    leaf(commands, 'sync-running', 'Import or refresh active experiments')
    command = leaf(commands, 'update', 'Update notes, tags or display fields', ('history_id',)); command.add_argument('--file', required=True)
    command = leaf(commands, 'rename', 'Change a display name', ('history_id',)); command.add_argument('name')
    for action in ('archive', 'restore', 'remove'):
        leaf(commands, action, 'Change history visibility; keep original files', ('history_id',))
    leaf(commands, 'export', 'Download the cached experiment ZIP', ('history_id',), export=True)
    leaf(commands, 'resume', 'Export verified resume parameters', ('history_id',), export=True)
    command = leaf(commands, 'delete', 'Preview and permanently delete selected files', ('history_id',), dangerous=True); command.add_argument('--scope', choices=['local', 'remote', 'both'], default='local')
    for name in ('table', 'plot'):
        command = groups.add_parser(name, help='Export cached ' + ('Markdown comparison tables' if name == 'table' else 'PNG curves'))
        command.add_argument('history_ids', nargs='+'); command.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
        command.add_argument('--output', '-o'); command.add_argument('--force', action='store_true'); command.add_argument('--request-file')
        if name == 'table':
            command.add_argument('--template'); command.add_argument('--baseline')
        else:
            command.add_argument('--metric'); command.add_argument('--axis', choices=['tokens', 'step', 'elapsed_s']); command.add_argument('--title')
    command = groups.add_parser('api', help='Advanced access to the same local API')
    command.add_argument('method', choices=['GET', 'POST', 'PUT', 'PATCH', 'DELETE']); command.add_argument('path'); command.add_argument('--file'); command.add_argument('--yes', action='store_true'); command.add_argument('--output', '-o'); command.add_argument('--force', action='store_true'); command.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    return root


def service_module():
    from . import platform_runtime
    return platform_runtime


def client_for(args, config):
    return Client(args.url or service_module().start_service(config)['url'])


def dispatch(args):
    config = Config.load()
    if args.group == 'service':
        if args.url:
            raise ValueError('Service lifecycle uses the selected workspace, not --url; select it with AI_EXP_DATA_DIR and AI_EXP_PORT')
        manager = service_module()
        if args.action == 'status':
            return manager.service_status(config) or {'running': False}
        if args.action == 'start':
            return manager.start_service(config)
        confirm(args, 'Stop the local workbench service? Remote experiments keep running')
        return {'stopped': manager.stop_service(config)}
    if args.group == 'install-agent':
        from .remote_install import install_agent
        return install_agent(config, read_only=args.read_only)
    if args.group == 'config' and args.action == 'show' and not args.url:
        return {'config_file': str(config.config_file), 'configured': config.configured, 'local_settings': config.local_settings}
    client = client_for(args, config)
    call = client.request
    group, action = args.group, getattr(args, 'action', None)
    identity = lambda value: quote(value, safe='')
    if group == 'config':
        return call('GET', '/api/settings/local') if action == 'show' else call('PUT', '/api/settings/local', document(args.file))
    if group == 'doctor':
        value = {'health': client.get('/api/health'), 'settings': client.get('/api/settings/local')}
        if args.remote:
            value['connection'] = client.post('/api/connection/refresh')
        return value
    if group == 'api':
        if args.method == 'DELETE' or args.path.rstrip('/').endswith(('/stop', '/pause', '/delete-confirm', '/shutdown')):
            confirm(args, 'Execute ' + args.method + ' ' + args.path + '?')
        return call(args.method, args.path, document(args.file) if args.file else None)
    if group == 'project':
        base = '/api/projects'
        if action == 'list': return client.get(base)
        if action == 'add':
            body = {'name': args.name, 'remote_path': args.path}
            if args.alias: body['ssh_alias'] = args.alias
            if args.config_file: body['config'] = document(args.config_file)
            return client.post(base, body)
        base += '/' + identity(args.project_id)
        if action == 'remove':
            confirm(args, 'Remove project ' + args.project_id + ' from favorites?')
            return call('DELETE', base)
        if action == 'update': return call('PATCH', base, document(args.file))
        body = {'refresh': not args.cached} if action == 'schema' else {}
        if action == 'schema' and args.ref: body['code'] = {'kind': 'ref', 'ref': args.ref}
        return client.post(base + '/' + action, body)
    if group == 'preset':
        base = '/api/projects/' + identity(args.project_id) + '/presets'
        if action == 'list': return client.get(base)
        if action == 'save':
            body = {'name': args.name, 'parameters': document(args.file)}
            return call('PUT' if args.id else 'POST', base + ('/' + identity(args.id) if args.id else ''), body)
        if action == 'import': return client.post(base + '/import', {'document': document(args.file), 'name': args.name})
        base += '/' + identity(args.preset_id)
        if action == 'delete':
            confirm(args, 'Delete parameter group ' + args.preset_id + '?')
            return call('DELETE', base)
        return client.get(base + '/export?format=' + args.format)
    if group == 'run':
        if action == 'list': return client.get('/api/runs')
        if action in {'start', 'queue', 'resume'}:
            if action == 'resume':
                parameters = client.post('/api/history/' + identity(args.history_id) + '/resume-editor')
                project_id = parameters['project_id']; mode = 'queue' if args.queue else 'start'
            else:
                project_id, mode = args.project_id, action
                if args.parameters:
                    parameters = document(args.parameters)
                elif args.preset:
                    presets = client.get('/api/projects/' + identity(project_id) + '/presets')
                    preset = next((p for p in presets if p['id'] == args.preset or p['name'] == args.preset), None)
                    if preset is None: raise ValueError('Parameter group not found: ' + args.preset)
                    parameters = preset['parameters']
                else:
                    parameters = client.get('/api/projects/' + identity(project_id) + '/editor-initial')
                if 'parameters' in parameters: parameters = parameters['parameters']
                if 'training' not in parameters: parameters = {'training': parameters, 'runtime': {'gpu_count': 1}}
                for setting in args.set:
                    if '=' not in setting: raise ValueError('--set requires NAME=VALUE')
                    key, value = setting.split('=', 1)
                    try: value = json.loads(value)
                    except ValueError: pass
                    parameters['training'][key] = value
            body = {'project_id': project_id, 'parameters': parameters, 'mode': mode,
                    'display_name': args.name or parameters.get('display_name')}
            if parameters.get('resume'): body['resume_ticket'] = parameters['resume']['ticket']
            if getattr(args, 'ref', None): body['code'] = {'kind': 'ref', 'ref': args.ref}
            return client.post('/api/runs', body)
        base = '/api/runs/' + identity(args.run_id)
        if action == 'show': return client.get(base)
        if action == 'log': return client.get(base + '/log?offset=' + str(args.offset))['text']
        if action in {'stop', 'pause', 'remove'}:
            confirm(args, action.capitalize() + ' experiment ' + args.run_id + '?')
            return client.post(base + '/' + action, {'confirmed': True, 'pause_queue': getattr(args, 'pause_queue', False)})
        return client.post(base + '/' + action)
    if group == 'queue':
        if action == 'list': return client.get('/api/queue')
        if action == 'order':
            queue = client.get('/api/queue')
            return call('PUT', '/api/queue/order', {'run_ids': args.run_ids, 'revision': queue['revision']})
        if action == 'remove':
            confirm(args, 'Remove queued experiment ' + args.run_id + '?')
            return call('DELETE', '/api/queue/' + identity(args.run_id))
        return client.post('/api/queue/' + action)
    if group == 'history':
        if action == 'list': return client.get('/api/history')
        if action == 'import':
            source = {'kind': args.source, 'path': args.path}
            if args.source == 'local': source['path'] = str(Path(args.path).expanduser().resolve())
            if args.alias: source['ssh_alias'] = args.alias
            return client.post('/api/history/import', {'source': source, 'name': args.name})
        if action in {'sync', 'sync-running'}: return client.post('/api/history/' + ('refresh' if action == 'sync' else action))
        base = '/api/history/' + identity(args.history_id)
        if action == 'export': return client.get(base + '/export')
        if action == 'resume': return client.post(base + '/resume-editor')
        if action == 'update': return call('PATCH', base, document(args.file))
        if action == 'delete':
            preview = client.post(base + '/delete-preview', {'scope': args.scope})
            confirm(args, 'Permanently delete: ' + ', '.join(preview['targets']) + '?')
            return client.post(base + '/delete-confirm', {'confirmation_token': preview['confirmation_token']})
        if action == 'remove': return call('DELETE', base)
        return call('PATCH', base, {'name': args.name} if action == 'rename' else {'visibility': 'archived' if action == 'archive' else 'visible'})
    body = document(args.request_file) if args.request_file else {}
    body['history_ids'] = args.history_ids
    if group == 'table':
        if args.template is not None: body['template_id'] = args.template
        if args.baseline is not None: body['baseline_id'] = args.baseline
        result = client.post('/api/analysis/table', body)
        if not args.json:
            for warning in result.get('warnings', []): print('Warning: ' + str(warning), file=sys.stderr)
        return result if args.json else result['markdown']
    if args.metric is not None: body['metric'] = args.metric
    if args.axis is not None: body['x_axis'] = args.axis
    if args.title is not None: body['title'] = args.title
    result = client.post('/api/analysis/plot/png', body)
    for warning in json.loads(getattr(client, 'last_headers', {}).get('X-Experiment-Warnings', '[]')):
        print('Warning: ' + str(warning), file=sys.stderr)
    return result


def main(argv=None):
    # Redirected Windows streams otherwise inherit an ANSI code page.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = parser().parse_args(argv)
    try:
        if args.group == 'service' and args.action == 'run':
            from .desktop import main as serve
            serve()
            return 0
        if args.group == 'desktop':
            from .native import main as native
            native(smoke_test=args.smoke_test)
            return 0
        if (args.group == 'plot' or args.group == 'history' and args.action == 'export') and not args.output:
            raise ValueError('Binary exports require --output PATH')
        output(dispatch(args), args)
        return 0
    except ConfirmationRequired as exc:
        print(str(exc), file=sys.stderr); return 5
    except APIError as exc:
        print('API ' + str(exc.status) + ': ' + str(exc.detail), file=sys.stderr); return 4
    except (ValueError, KeyError, TypeError) as exc:
        print('Invalid input: ' + str(exc), file=sys.stderr); return 2
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print('Connection/service error: ' + str(exc), file=sys.stderr); return 3


if __name__ == '__main__':
    raise SystemExit(main())
