#!/usr/bin/env python3
"""Call the local workbench API with its cookie and same-origin protection."""
import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def call(base, method, path, document=None):
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1'} or parsed.path not in {'', '/'} or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Use a local http://127.0.0.1:PORT address')
    if not path.startswith('/api/') or '?' in path or '#' in path or '..' in path:
        raise ValueError('Use an absolute /api/ path without a query or fragment')
    origin = base.rstrip('/')
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with client.open(origin + '/', timeout=15) as response:
        response.read()
    headers = {'Origin': origin, 'Content-Type': 'application/json'}
    data = None if document is None else json.dumps(document, allow_nan=False).encode()
    request = urllib.request.Request(origin + path, data=data, headers=headers, method=method)
    with client.open(request, timeout=180) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8765')
    parser.add_argument('--method', choices=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], default='GET')
    parser.add_argument('--path', required=True)
    parser.add_argument('--json-file', help='UTF-8 request document; use - for stdin')
    args = parser.parse_args()
    document = None
    if args.json_file:
        with open(args.json_file, encoding='utf-8') if args.json_file != '-' else sys.stdin as stream:
            document = json.load(stream)
    try:
        result = call(args.base, args.method, args.path, document)
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(errors='replace'), file=sys.stderr)
        raise SystemExit(exc.code) from exc
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
