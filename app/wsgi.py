"""WSGI entry point for hosting Keyfall behind a WSGI server (PythonAnywhere, gunicorn, ...).

It reuses server.Handler unchanged: each WSGI request becomes one dispatch() call whose
buffered response is handed back to the WSGI server instead of written to a socket.
"""
import mimetypes
import os
import sys
from email.message import Message
from http import HTTPStatus
from urllib.parse import quote

os.environ.setdefault("KEYFALL_TRUST_PROXY", "1")        # hosted behind the provider's proxy
os.environ.setdefault("KEYFALL_SQLITE_JOURNAL", "DELETE")  # safest on network filesystems
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402
import store  # noqa: E402

mimetypes.add_type("application/javascript", ".js")
store.init().close()


class WSGIHandler(server.Handler):
    def __init__(self, environ):  # deliberately not calling the socket-based base __init__
        self.environ = environ
        self.command = environ["REQUEST_METHOD"].upper()
        raw_path = environ.get("PATH_INFO", "/").encode("latin-1")  # WSGI's str-of-bytes convention
        query = environ.get("QUERY_STRING", "")
        self.path = quote(raw_path, safe="/%:@!$&'()*+,;=-._~") + (f"?{query}" if query else "")
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                self.headers[key[5:].replace("_", "-").title()] = value
        if environ.get("CONTENT_TYPE"):
            self.headers["Content-Type"] = environ["CONTENT_TYPE"]
        if environ.get("CONTENT_LENGTH"):
            self.headers["Content-Length"] = environ["CONTENT_LENGTH"]
        self.rfile = environ["wsgi.input"]
        self.client_address = (environ.get("REMOTE_ADDR", ""), 0)
        self.close_connection = True
        self._result = None

    def is_https(self):
        return self.environ.get("wsgi.url_scheme") == "https" or super().is_https()

    def flush(self):
        self._result = self.response_headers()

    def log_message(self, fmt, *args):
        pass  # the hosting provider keeps its own access log


def application(environ, start_response):
    handler = WSGIHandler(environ)
    method = handler.command
    handler.dispatch("GET" if method == "HEAD" else method)
    status, headers = handler._result
    start_response(f"{status} {HTTPStatus(status).phrase}", headers)
    body = handler._pending_body or b""
    return [] if method == "HEAD" else [body]
