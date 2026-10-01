"""Cookie-authenticated client for the shared, local workbench service."""
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request


class APIError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(str(detail))


class Client:
    def __init__(self, url, timeout=180):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'}
                or parsed.path not in {'', '/'} or parsed.query or parsed.fragment or parsed.username):
            raise ValueError('The service URL must be http://127.0.0.1:PORT or http://localhost:PORT')
        self.url, self.timeout = url.rstrip('/'), timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.connected = False
        self.last_headers = {}

    def connect(self):
        with self.opener.open(self.url + '/', timeout=15) as response:
            response.read()
        self.connected = True

    def request(self, method, path, body=None):
        if not path.startswith('/api/') or urllib.parse.urlsplit(path).netloc or '#' in path:
            raise ValueError('Use an absolute /api/ path')
        if not self.connected:
            self.connect()
        if body is None and method not in {'GET', 'HEAD'}:
            body = {}
        data = json.dumps(body, allow_nan=False).encode() if body is not None else None
        for attempt in range(2):
            request = urllib.request.Request(self.url + path, data=data, method=method,
                headers={'Origin': self.url, 'Content-Type': 'application/json'})
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    self.last_headers = response.headers
                    raw = response.read()
                    if not raw:
                        return None
                    content_type = response.headers.get('Content-Type', '')
                    if 'application/json' in content_type:
                        return json.loads(raw)
                    if content_type.startswith('text/'):
                        return raw.decode('utf-8')
                    return raw
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode('utf-8', errors='replace')
                try:
                    detail = json.loads(raw).get('detail', raw)
                except (ValueError, AttributeError):
                    detail = raw
                if attempt == 0 and exc.code == 403 and detail == '请从应用首页打开工作台':
                    self.connect()
                    continue
                raise APIError(exc.code, detail) from exc

    def get(self, path):
        return self.request('GET', path)

    def post(self, path, body=None):
        return self.request('POST', path, body)
