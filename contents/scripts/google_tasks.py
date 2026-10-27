#!/usr/bin/env python3
"""Optional Google Tasks bridge for Task Widget (Python 3.9+, standard library only)."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen
import webbrowser


SCOPE = "https://www.googleapis.com/auth/tasks"
API_URL = "https://tasks.googleapis.com/tasks/v1"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
DEFAULT_PORT = 18743
SERVICE = "taskwidget-google-tasks.service"
NETWORK_TIMEOUT = 15


class BridgeError(Exception):
    def __init__(self, code, message, status=502):
        super().__init__(message)
        self.code = code
        self.status = status


class GoogleError(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def config_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "taskwidget/google-tasks.json"


def private_write(path, contents):
    """Replace a private file atomically, including when refreshing credentials."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".taskwidget-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_config(path, config):
    private_write(path, json.dumps(config, indent=2) + "\n")


def load_config(path):
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        for field in ("client_id", "refresh_token", "list_id", "access_key"):
            if not isinstance(config[field], str) or not config[field]:
                raise ValueError(field)
        if len(config["access_key"]) < 32 or not 1024 <= int(config["port"]) <= 65535:
            raise ValueError("Invalid bridge settings")
        return config
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise BridgeError("setup_required", "Run the Google Tasks setup command first.", 503) from error


def request_json(url, method="GET", data=None, headers=None, form=None):
    headers = dict(headers or {})
    body = None
    if form is not None:
        body = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=NETWORK_TIMEOUT) as response:
            raw = response.read()
        result = json.loads(raw) if raw else {}
        if not isinstance(result, dict):
            raise ValueError("Expected an object")
        return result
    except HTTPError as error:
        try:
            with error:
                reason = json.loads(error.read()).get("error", "")
            if isinstance(reason, dict):
                reason = reason.get("status", "")
        except (ValueError, AttributeError):
            reason = ""
        raise GoogleError(error.code, str(reason)) from error
    except (URLError, OSError, HTTPException) as error:
        raise BridgeError("offline", "Could not reach Google. Check your connection and try again.") from error
    except (ValueError, UnicodeError) as error:
        raise BridgeError("invalid_response", "Google returned an unreadable response. Try syncing again.") from error


def google_error(error):
    if error.status == 401 or error.reason in ("invalid_grant", "invalid_client"):
        return BridgeError("sign_in_required", "Google sign-in expired or was revoked. Run setup again.", 401)
    if error.status == 403:
        return BridgeError("permission_denied", "Google denied access. Check the Tasks API, account permissions, and API quota.", 403)
    if error.status in (404, 410):
        return BridgeError("not_found", "This Google task or list no longer exists. Refresh the list.", 404)
    if error.status == 412:
        return BridgeError("conflict", "This task changed on Google. Finish or cancel editing, then refresh before trying again.", 409)
    if error.status == 429:
        return BridgeError("rate_limited", "Google's request limit was reached. Wait a minute and sync again.", 429)
    if error.status == 400:
        return BridgeError("invalid_task", "Google could not save this task. Check its title and try again.", 400)
    return BridgeError("google_unavailable", "Google Tasks is temporarily unavailable. Try syncing again.")


def authorize(client, timeout=300):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    result = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        timeout = 5

        def log_message(self, *_args):
            pass  # The callback URL contains an authorization code.

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            returned_state = query.get("state", [""])[0]
            if parsed.path != "/" or not secrets.compare_digest(returned_state.encode("utf-8"), state.encode("ascii")):
                self.send_error(400, "Invalid authorization callback")
                return
            if not query.get("code") and not query.get("error"):
                self.send_error(400, "Missing authorization code")
                return
            result.update(query)
            message = b"Authorization received. You can close this tab and return to the terminal."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    with HTTPServer(("127.0.0.1", 0), CallbackHandler) as server:
        server.timeout = 1
        redirect_uri = "http://127.0.0.1:%s/" % server.server_port
        url = AUTH_URL + "?" + urlencode({
            "client_id": client["client_id"], "redirect_uri": redirect_uri,
            "response_type": "code", "scope": SCOPE, "access_type": "offline",
            "prompt": "consent", "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        print("Open this URL in your browser to authorize Google Tasks:\n\n" + url + "\n")
        try:
            webbrowser.open(url)
        except webbrowser.Error:
            pass
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result or "error" in result:
        raise BridgeError("authorization_failed", "Authorization was cancelled or timed out. Run setup again.", 400)
    tokens = request_json(TOKEN_URL, "POST", form={
        "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
        "code": result["code"][0], "code_verifier": verifier,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    })
    if not tokens.get("refresh_token") or not tokens.get("access_token"):
        raise BridgeError("authorization_failed", "Google did not grant offline access. Run setup and grant Tasks access.", 400)
    if SCOPE not in tokens.get("scope", SCOPE).split():
        raise BridgeError("authorization_failed", "Google Tasks permission was not granted. Run setup again.", 400)
    return tokens


def task_record(task):
    return {
        "id": task["id"], "description": task.get("title", ""),
        "completed": task.get("status") == "completed", "etag": task.get("etag", ""),
    }


def task_fields(data, creating=False):
    if not isinstance(data, dict) or set(data) - {"description", "completed"}:
        raise BridgeError("invalid_task", "Only the task title and completion status can be changed.", 400)
    fields = {}
    if "description" in data or creating:
        title = data.get("description")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 1024:
            raise BridgeError("invalid_task", "Use a task title between 1 and 1,024 characters.", 400)
        fields["title"] = title.strip()
    if "completed" in data:
        if not isinstance(data["completed"], bool):
            raise BridgeError("invalid_task", "Completion status must be true or false.", 400)
        fields["status"] = "completed" if data["completed"] else "needsAction"
        if not data["completed"]:
            fields["completed"] = None
    if not fields:
        raise BridgeError("invalid_task", "No task changes were supplied.", 400)
    return fields


class GoogleTasksAPI:
    def __init__(self, config, path=None, tokens=None):
        self.config = config
        self.path = path
        self.access_token = (tokens or {}).get("access_token", "")
        self.expires_at = time.time() + (tokens or {}).get("expires_in", 0)

    def refresh_token(self):
        try:
            tokens = request_json(TOKEN_URL, "POST", form={
                "client_id": self.config["client_id"],
                "client_secret": self.config.get("client_secret", ""),
                "refresh_token": self.config["refresh_token"], "grant_type": "refresh_token",
            })
        except GoogleError as error:
            raise google_error(error) from error
        if not tokens.get("access_token"):
            raise BridgeError("sign_in_required", "Google could not refresh your sign-in. Run setup again.", 401)
        if tokens.get("refresh_token") and tokens["refresh_token"] != self.config["refresh_token"]:
            self.config["refresh_token"] = tokens["refresh_token"]
            if self.path:
                save_config(self.path, self.config)
        self.access_token = tokens["access_token"]
        self.expires_at = time.time() + tokens.get("expires_in", 3600)

    def request(self, method, path, data=None, etag=None):
        if not self.access_token or self.expires_at <= time.time() + 60:
            self.refresh_token()
        for attempt in range(2):
            headers = {"Authorization": "Bearer " + self.access_token}
            if etag:
                headers["If-Match"] = etag
            try:
                return request_json(API_URL + path, method, data=data, headers=headers)
            except GoogleError as error:
                # A rejected token is safe to retry. Never retry an ambiguous write.
                if error.status == 401 and attempt == 0:
                    self.refresh_token()
                else:
                    raise google_error(error) from error

    def all_pages(self, path, parameters=None):
        parameters = dict(parameters or {})
        parameters["maxResults"] = 100
        items = []
        seen = set()
        while True:
            page = self.request("GET", path + "?" + urlencode(parameters))
            items.extend(page.get("items", []))
            token = page.get("nextPageToken")
            if not token:
                return items
            if token in seen:
                raise BridgeError("invalid_response", "Google returned a repeated page. Try syncing again.")
            seen.add(token)
            parameters["pageToken"] = token

    def tasks_path(self):
        return "/lists/" + quote(self.config["list_id"], safe="") + "/tasks"

    def snapshot(self):
        task_list = self.request("GET", "/users/@me/lists/" + quote(self.config["list_id"], safe=""))
        tasks = self.all_pages(self.tasks_path(), {
            "showCompleted": "true", "showHidden": "true", "showDeleted": "false",
        })
        return {
            "listId": task_list["id"], "listTitle": task_list.get("title", "Google Tasks"),
            "tasks": [task_record(task) for task in tasks if not task.get("deleted")],
        }

    def create(self, data):
        return task_record(self.request("POST", self.tasks_path(), task_fields(data, creating=True)))

    def update(self, task_id, data, etag=None):
        return task_record(self.request("PATCH", self.tasks_path() + "/" + quote(task_id, safe=""), task_fields(data), etag))

    def delete(self, task_id, etag=None):
        try:
            self.request("DELETE", self.tasks_path() + "/" + quote(task_id, safe=""), etag=etag)
        except BridgeError as error:
            if error.code != "not_found":
                raise


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, access_key, api):
        super().__init__(("127.0.0.1", port), BridgeHandler)
        self.access_key = access_key
        self.api = api
        self.operation_lock = threading.Lock()


class BridgeHandler(BaseHTTPRequestHandler):
    timeout = 10

    def log_message(self, *_args):
        pass  # Do not put task contents, headers, or credentials in the journal.

    def reply(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 16384:
                raise ValueError("Body too large")
            if length and self.headers.get_content_type() != "application/json":
                raise ValueError("Expected JSON")
            return json.loads(self.rfile.read(length)) if length else {}
        except (ValueError, UnicodeError) as error:
            raise BridgeError("invalid_request", "The helper received an invalid request.", 400) from error

    def dispatch(self):
        expected_host = "127.0.0.1:%s" % self.server.server_port
        if self.headers.get("Host") != expected_host or self.headers.get("Origin"):
            raise BridgeError("forbidden", "Only local widget requests are accepted.", 403)
        authorization = self.headers.get("Authorization", "")
        expected = "Bearer " + self.server.access_key
        if not secrets.compare_digest(authorization.encode("utf-8"), expected.encode("utf-8")):
            raise BridgeError("invalid_key", "The helper access key does not match. Copy it from the setup script into widget settings.", 401)
        path = urlsplit(self.path).path
        # Decode the task ID once; the API client will safely encode it again.
        task_id = unquote(path[len("/v1/tasks/"):]) if path.startswith("/v1/tasks/") else ""
        with self.server.operation_lock:
            if path == "/v1/tasks" and self.command == "GET":
                return self.server.api.snapshot()
            if path == "/v1/tasks" and self.command == "POST":
                return {"task": self.server.api.create(self.read_body())}
            if task_id and self.command == "PATCH":
                return {"task": self.server.api.update(task_id, self.read_body(), self.headers.get("If-Match"))}
            if task_id and self.command == "DELETE":
                self.server.api.delete(task_id, self.headers.get("If-Match"))
                return {}
        raise BridgeError("not_found", "Unknown helper endpoint.", 404)

    def handle_request(self):
        try:
            try:
                self.reply(200, self.dispatch())
            except BridgeError as error:
                self.reply(error.status, {"error": {"code": error.code, "message": str(error)}})
            except (OSError, ValueError, KeyError, TypeError):
                self.reply(500, {"error": {"code": "helper_error", "message": "The Google Tasks helper failed. Check its configuration and restart it."}})
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = handle_request
    do_POST = handle_request
    do_PATCH = handle_request
    do_DELETE = handle_request
    do_OPTIONS = handle_request


def service_paths():
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return config_home / "systemd/user" / SERVICE, data_home / "taskwidget/google_tasks.py"


def systemd_quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$").replace("\n", "\\n") + '"'


def install_service(path):
    if not shutil.which("systemctl"):
        raise BridgeError("service_unavailable", "systemd was not found. Run this script with the 'serve' command instead.", 503)
    unit, installed_script = service_paths()
    private_write(installed_script, Path(__file__).read_text(encoding="utf-8"))
    command = " ".join(systemd_quote(part) for part in (sys.executable, installed_script.resolve(), "--config", path.resolve(), "serve"))
    private_write(unit, "\n".join([
        "[Unit]", "Description=Task Widget Google Tasks helper", "", "[Service]",
        "Type=simple", "ExecStart=" + command, "Restart=on-failure", "RestartSec=5",
        "UMask=0077", "NoNewPrivileges=true", "", "[Install]", "WantedBy=default.target", "",
    ]))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", SERVICE], check=True)
    subprocess.run(["systemctl", "--user", "restart", SERVICE], check=True)


def show_connection(config):
    print("Google Tasks list:", config.get("list_title", config["list_id"]))
    print("Helper port:", config["port"])
    print("Helper access key:", config["access_key"])
    print("\nIn Configure Widget > Google Tasks, paste these settings and enable Google Tasks.")


def setup(args):
    try:
        client = json.loads(args.client_secrets.expanduser().read_text(encoding="utf-8"))["installed"]
        if not isinstance(client.get("client_id"), str) or not client["client_id"]:
            raise ValueError("Missing client ID")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise BridgeError("invalid_credentials", "Choose the downloaded OAuth client JSON for a Desktop app.", 400) from error
    tokens = authorize(client)
    config = {
        "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
        "refresh_token": tokens["refresh_token"], "port": args.port,
        "access_key": secrets.token_urlsafe(32),
    }
    api = GoogleTasksAPI(config, tokens=tokens)
    lists = api.all_pages("/users/@me/lists")
    print("Choose the list to show in the widget:")
    print("  0. Create a new list named Task Widget")
    for index, task_list in enumerate(lists, 1):
        print("  %s. %s" % (index, task_list.get("title", "Untitled list")))
    while True:
        try:
            selection = int(input("List [0]: ").strip() or "0")
            if 0 <= selection <= len(lists):
                break
        except ValueError:
            pass
        print("Enter a number from 0 to %s." % len(lists))
    selected = lists[selection - 1] if selection else api.request("POST", "/users/@me/lists", {"title": "Task Widget"})
    config.update(list_id=selected["id"], list_title=selected.get("title", "Google Tasks"))
    save_config(args.config, config)
    show_connection(config)
    if args.no_service:
        print("\nStart the helper with: python3 %s --config %s serve" % (shlex.quote(__file__), shlex.quote(str(args.config))))
    else:
        install_service(args.config)
        print("\nThe helper is running and will start automatically when you log in.")


def disconnect(args):
    config = load_config(args.config)
    unit, installed_script = service_paths()
    if unit.exists():
        subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE], check=True)
    try:
        request_json("https://oauth2.googleapis.com/revoke", "POST", form={"token": config["refresh_token"]})
    except GoogleError as error:
        if error.status != 400 or error.reason != "invalid_token":
            raise
    args.config.unlink()
    if unit.exists():
        unit.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    installed_script.unlink(missing_ok=True)
    print("Google access revoked and the helper removed. Turn off Google Tasks in widget settings.")


def port_number(value):
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("Choose a port between 1024 and 65535.")
    return port


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=config_path(), help="Private helper configuration file")
    commands = parser.add_subparsers(dest="command", required=True)
    setup_parser = commands.add_parser("setup", help="Sign in, select a list, and install the user service")
    setup_parser.add_argument("--client-secrets", type=Path, required=True, help="Google Desktop app OAuth client JSON")
    setup_parser.add_argument("--port", type=port_number, default=DEFAULT_PORT)
    setup_parser.add_argument("--no-service", action="store_true", help="Configure only; start the helper manually")
    commands.add_parser("serve", help="Run the local helper in the foreground")
    commands.add_parser("info", help="Show the settings to paste into the widget")
    commands.add_parser("disconnect", help="Revoke Google access and remove the helper")
    args = parser.parse_args()
    args.config = args.config.expanduser().resolve()
    try:
        if args.command == "setup":
            setup(args)
        elif args.command == "info":
            show_connection(load_config(args.config))
        elif args.command == "disconnect":
            disconnect(args)
        else:
            config = load_config(args.config)
            with BridgeServer(int(config["port"]), config["access_key"], GoogleTasksAPI(config, args.config)) as server:
                print("Google Tasks helper listening on 127.0.0.1:%s" % server.server_port, flush=True)
                server.serve_forever()
    except GoogleError as error:
        print(str(google_error(error)), file=sys.stderr)
        return 1
    except (BridgeError, OSError, subprocess.CalledProcessError, EOFError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
