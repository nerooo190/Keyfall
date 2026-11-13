"""Deploy Keyfall to a PythonAnywhere account (works on the free Beginner plan).

    python3 -I deploy/pythonanywhere.py <username>

The API token is read from $PYTHONANYWHERE_TOKEN or ~/.config/keyfall/pythonanywhere_token
(Account -> API token on pythonanywhere.com). The site ends up at https://<username>.pythonanywhere.com

How it works: everything is packed into one zip and uploaded to ~/keyfall-bundle.zip. The WSGI
file installed on PythonAnywhere unpacks it into ~/keyfall the next time the app starts.
Code files are replaced on every deploy; files under data/ (database, uploads, covers) are only
written if they don't exist yet, so redeploying never touches accounts, reviews or uploads.
"""
import argparse
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.expanduser("~/.config/keyfall/pythonanywhere_token")
HOSTS = ["www.pythonanywhere.com", "eu.pythonanywhere.com"]
PYTHON_VERSIONS = ["python313", "python312", "python311", "python310"]

WSGI_TEMPLATE = '''# Keyfall — installed by deploy/pythonanywhere.py. Unpacks new bundles, then serves the app.
import os
import shutil
import sys
import zipfile

APP_DIR = {app_dir!r}
BUNDLE = {bundle!r}
MARKER = os.path.join(APP_DIR, ".bundle-version")


def _install_bundle():
    if not os.path.exists(BUNDLE):
        return
    stamp = "%s:%s" % (os.path.getmtime(BUNDLE), os.path.getsize(BUNDLE))
    try:
        with open(MARKER) as f:
            if f.read() == stamp:
                return
    except OSError:
        pass
    root = os.path.realpath(APP_DIR)
    with zipfile.ZipFile(BUNDLE) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = os.path.realpath(os.path.join(APP_DIR, info.filename))
            if not target.startswith(root + os.sep):
                continue  # never write outside the app directory
            if info.filename.startswith("data/") and os.path.exists(target):
                continue  # live data (database, uploads) is never overwritten
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target + ".part", "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(target + ".part", target)
    with open(MARKER, "w") as f:
        f.write(stamp)


_install_bundle()
os.environ.setdefault("KEYFALL_TRUST_PROXY", "1")
os.environ.setdefault("KEYFALL_SQLITE_JOURNAL", "DELETE")
sys.path.insert(0, os.path.join(APP_DIR, "app"))
from wsgi import application  # noqa: E402,F401
'''


def build_bundle():
    """Zip code + library + a consistent snapshot of the database."""
    buf = io.BytesIO()
    skip_dirs = {"__pycache__", ".git"}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for top in ("app", "Songs"):
            for dirpath, dirs, files in os.walk(os.path.join(ROOT, top)):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for f in files:
                    if not f.endswith(".pyc"):
                        p = os.path.join(dirpath, f)
                        z.write(p, os.path.relpath(p, ROOT))
        for f in ("README.md", "start.sh"):
            z.write(os.path.join(ROOT, f), f)
        data = os.path.join(ROOT, "data")
        for sub in ("covers", "notes", "midi"):
            for dirpath, _, files in os.walk(os.path.join(data, sub)):
                for f in files:
                    p = os.path.join(dirpath, f)
                    z.write(p, os.path.relpath(p, ROOT))
        # Database snapshot via the backup API (safe while the local server runs),
        # converted to rollback-journal mode for the host's network filesystem.
        with tempfile.TemporaryDirectory() as tmp:
            snap = os.path.join(tmp, "keyfall.db")
            src = sqlite3.connect(os.path.join(data, "keyfall.db"))
            dst = sqlite3.connect(snap)
            src.backup(dst)
            src.close()
            dst.execute("DELETE FROM sessions")  # local logins shouldn't carry over
            dst.commit()
            dst.execute("PRAGMA journal_mode = DELETE")
            dst.close()
            z.write(snap, "data/keyfall.db")
    return buf.getvalue()


class PA:
    def __init__(self, username, token):
        self.user = username
        self.token = token
        self.host = None

    def call(self, method, path, data=None, files=None, ok=(200, 201, 204)):
        url = f"https://{self.host}/api/v0/user/{self.user}/{path}"
        headers = {"Authorization": f"Token {self.token}", "User-Agent": "keyfall-deploy/1.0"}
        body = None
        if files:
            boundary = uuid.uuid4().hex
            parts = []
            for name, (filename, content) in files.items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                             f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
                parts.append(content + b"\r\n")
            parts.append(f"--{boundary}--\r\n".encode())
            body = b"".join(parts)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif data is not None:  # the PythonAnywhere API takes form-encoded fields
            body = urllib.parse.urlencode({k: (str(v) if not isinstance(v, bool) else ("True" if v else "False"))
                                           for k, v in data.items()}).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        if status not in ok:
            raise RuntimeError(f"{method} {path} -> HTTP {status}: {raw[:300].decode(errors='replace')}")
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return raw

    def detect_host(self):
        for host in HOSTS:
            self.host = host
            try:
                self.call("GET", "cpu/")
                return host
            except RuntimeError as e:
                if "HTTP 401" not in str(e) and "HTTP 403" not in str(e):
                    raise
        raise SystemExit("The API token was rejected. Check the username and create a fresh token "
                         "under Account -> API token.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username")
    args = ap.parse_args()
    token = os.environ.get("PYTHONANYWHERE_TOKEN")
    if not token and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
    if not token:
        raise SystemExit(f"No API token: set PYTHONANYWHERE_TOKEN or save it to {TOKEN_FILE}")

    pa = PA(args.username, token)
    host = pa.detect_host()
    domain = f"{args.username}.pythonanywhere.com" if host.startswith("www") else f"{args.username}.eu.pythonanywhere.com"
    home = f"/home/{args.username}"
    print(f"✓ token accepted ({host})")

    bundle = build_bundle()
    print(f"✓ bundle built: {len(bundle) / 1e6:.1f} MB")
    pa.call("POST", f"files/path{home}/keyfall-bundle.zip", files={"content": ("keyfall-bundle.zip", bundle)})
    print("✓ bundle uploaded")

    apps = {a["domain_name"]: a for a in pa.call("GET", "webapps/")}
    if domain not in apps:
        last = None
        for version in PYTHON_VERSIONS:
            try:
                pa.call("POST", "webapps/", data={"domain_name": domain, "python_version": version})
                print(f"✓ web app created ({version})")
                break
            except RuntimeError as e:
                last = e
        else:
            raise SystemExit(f"Couldn't create the web app: {last}")
    else:
        print("✓ web app exists")

    wsgi_path = f"/var/www/{domain.replace('.', '_')}_wsgi.py"
    wsgi = WSGI_TEMPLATE.format(app_dir=f"{home}/keyfall", bundle=f"{home}/keyfall-bundle.zip")
    pa.call("POST", f"files/path{wsgi_path}", files={"content": ("wsgi.py", wsgi.encode())})
    print("✓ WSGI entry point installed")
    try:
        pa.call("PATCH", f"webapps/{domain}/", data={"source_directory": f"{home}/keyfall", "force_https": True})
    except RuntimeError as e:
        print(f"  (couldn't set source dir / force HTTPS: {e})")
    pa.call("POST", f"webapps/{domain}/reload/")
    print("✓ reloaded")

    url = f"https://{domain}"
    for attempt in range(12):  # first request unpacks the bundle
        try:
            with urllib.request.urlopen(urllib.request.Request(url + "/api/meta", headers={"User-Agent": "keyfall-deploy"}),
                                        timeout=120) as r:
                meta = json.load(r)
            print(f"✓ live: {url}  ({meta['total']} songs)")
            return
        except Exception as e:
            last = e
            time.sleep(5)
    print(f"! The app didn't answer yet ({last}). Check the error log on the Web tab: "
          f"https://{host}/user/{args.username}/webapps/")
    sys.exit(1)


if __name__ == "__main__":
    main()
