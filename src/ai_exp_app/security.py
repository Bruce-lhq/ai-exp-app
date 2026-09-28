import secrets
from urllib.parse import urlsplit
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class LocalSessionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str, native_token: str):
        super().__init__(app)
        self.token = token
        self.native_token = native_token

    async def dispatch(self, request, call_next):
        host = request.url.hostname
        if host not in {"localhost", "127.0.0.1", "testserver"}:
            return JSONResponse({"detail": "不允许的主机地址"}, status_code=403)
        path = request.url.path
        native = secrets.compare_digest(request.headers.get("X-Desktop-Token", ""), self.native_token)
        if path.startswith("/api/") and path != "/api/health":
            valid = secrets.compare_digest(request.cookies.get("ai_exp_session", ""), self.token)
            if not valid and not native:
                return JSONResponse({"detail": "请从应用首页打开工作台"}, status_code=403)
            if request.method not in {"GET", "HEAD", "OPTIONS"} and not native:
                origin = request.headers.get("origin", "")
                parsed = urlsplit(origin)
                if parsed.netloc != request.url.netloc or parsed.scheme != request.url.scheme:
                    return JSONResponse({"detail": "仅允许同源操作"}, status_code=403)
                if "application/json" not in request.headers.get("content-type", ""):
                    return JSONResponse({"detail": "请求必须为 JSON"}, status_code=415)
        response = await call_next(request)
        if not path.startswith("/api/") and request.method == "GET" and "text/html" in response.headers.get("content-type", ""):
            response.set_cookie("ai_exp_session", self.token, httponly=True, samesite="strict")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response
