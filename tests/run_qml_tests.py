#!/usr/bin/env python3
"""Run QML tests against an in-memory Google API and a real loopback bridge."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("google_tasks", ROOT / "contents/scripts/google_tasks.py")
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)
ACCESS_KEY = "test-access-key-with-at-least-32-characters"


class FakeGoogleAPI(bridge.GoogleTasksAPI):
    def __init__(self):
        super().__init__({"list_id": "test-list"})
        self.reset()

    def reset(self):
        self.records = [
            {"id": "first/+", "title": "Online task 🥕", "status": "needsAction", "etag": '"1"', "notes": "Keep these notes"},
            {"id": "second", "title": "Completed online", "status": "completed", "etag": '"2"', "hidden": True},
        ]
        self.requests = []
        self.failure = ""
        self.delay = 0
        self.version = 2

    def control(self, data):
        if data.get("reset"):
            self.reset()
        if "records" in data:
            self.records = data["records"]
        if "failure" in data:
            self.failure = data["failure"]
        if "delay" in data:
            self.delay = data["delay"]
        return {"tasks": [bridge.task_record(task) for task in self.records], "requests": self.requests}

    def snapshot(self):
        delay, self.delay = self.delay, 0
        if delay:
            time.sleep(delay)
        if self.failure == "fetch":
            self.failure = ""
            raise bridge.BridgeError("offline", "Offline fixture")
        if self.failure == "malformed":
            self.failure = ""
            return {"listId": "test-list", "listTitle": "Bad response", "tasks": [{"unexpected": True}]}
        return super().snapshot()

    def request(self, method, path, data=None, etag=None):
        self.requests.append({"method": method, "path": path, "data": data})
        path = urlsplit(path).path
        if method == "GET" and path == "/users/@me/lists/test-list":
            return {"id": "test-list", "title": "My Google list"}
        if method == "GET" and path == "/lists/test-list/tasks":
            return {"items": [dict(task) for task in self.records]}
        if method == "POST" and path == "/lists/test-list/tasks":
            self.version += 1
            task = {"id": "created-%s" % self.version, "status": "needsAction", **data, "etag": '"%s"' % self.version}
            self.records.append(task)
            if self.failure == "create-after-commit":
                self.failure = ""
                raise bridge.BridgeError("offline", "Response lost after saving")
            return dict(task)
        task_id = unquote(path.rsplit("/", 1)[-1])
        task = next((task for task in self.records if task["id"] == task_id), None)
        if task is None:
            raise bridge.BridgeError("not_found", "Task was deleted", 404)
        if etag and task["etag"] != etag:
            raise bridge.BridgeError("conflict", "Task changed online. Refresh before retrying.", 409)
        if method == "PATCH":
            self.version += 1
            task.update(data, etag='"%s"' % self.version)
            return dict(task)
        if method == "DELETE":
            if self.failure == "delete-" + task_id:
                self.failure = ""
                raise bridge.BridgeError("offline", "Deletion failed")
            self.records.remove(task)
            return {}
        raise AssertionError("Unexpected fixture request: " + method + " " + path)


class FixtureHandler(bridge.BridgeHandler):
    def dispatch(self):
        if self.path == "/__test" and self.command == "POST":
            if self.headers.get("Authorization") != "Bearer " + ACCESS_KEY:
                raise bridge.BridgeError("invalid_key", "Invalid fixture key", 401)
            with self.server.operation_lock:
                return self.server.api.control(self.read_body())
        return super().dispatch()


def main():
    runner = os.environ.get("QML_TEST_RUNNER") or shutil.which("qmltestrunner")
    if not runner:
        runner = next((str(path) for path in (
            Path("/usr/lib/qt6/bin/qmltestrunner"), Path("/usr/lib64/qt6/bin/qmltestrunner"),
        ) if path.is_file()), None)
    if not runner:
        print("Install Qt 6's qmltestrunner, or set QML_TEST_RUNNER to its path.", file=sys.stderr)
        return 1
    with bridge.BridgeServer(0, ACCESS_KEY, FakeGoogleAPI()) as server:
        server.RequestHandlerClass = FixtureHandler
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="taskwidget-qml-") as directory:
                directory = Path(directory)
                template = (ROOT / "tests/qml/tst_google_tasks.qml").read_text(encoding="utf-8")
                template = template.replace('"../../contents/ui"', json.dumps((ROOT / "contents/ui").as_uri()))
                template = template.replace('"../../contents/ui/code/tasks.js"', json.dumps((ROOT / "contents/ui/code/tasks.js").as_uri()))
                template = template.replace("property int bridgePort: 0", "property int bridgePort: %s" % server.server_port)
                (directory / "tst_google_tasks.qml").write_text(template, encoding="utf-8")
                env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                           QML_DISABLE_DISK_CACHE="1", XDG_CACHE_HOME=str(directory / "cache"))
                return subprocess.run([runner, "-input", str(directory)], env=env, timeout=90).returncode
        finally:
            server.shutdown()
            thread.join(timeout=2)


if __name__ == "__main__":
    sys.exit(main())
