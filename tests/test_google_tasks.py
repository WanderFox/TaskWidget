import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("google_tasks", ROOT / "contents/scripts/google_tasks.py")
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


def configuration():
    return {
        "client_id": "test-client", "client_secret": "test-secret",
        "refresh_token": "test-refresh", "list_id": "list/with+characters",
        "list_title": "Test list", "access_key": "test-access-key-with-at-least-32-characters",
        "port": 18743,
    }


def api():
    return bridge.GoogleTasksAPI(configuration(), tokens={"access_token": "test-access", "expires_in": 3600})


class GoogleAPITests(unittest.TestCase):
    def test_snapshot_loads_every_page_and_mobile_completed_tasks(self):
        client = api()
        client.request = Mock(side_effect=[
            {"id": "list-id", "title": "Renamed list"},
            {"items": [{"id": "a", "title": "A", "status": "needsAction", "etag": '"a"'}], "nextPageToken": "page two"},
            {"items": [
                {"id": "b", "title": "B", "status": "completed", "hidden": True, "etag": '"b"'},
                {"id": "deleted", "deleted": True},
            ]},
        ])
        snapshot = client.snapshot()
        self.assertEqual(snapshot["listTitle"], "Renamed list")
        self.assertEqual([task["id"] for task in snapshot["tasks"]], ["a", "b"])
        self.assertTrue(snapshot["tasks"][1]["completed"])
        first_path = client.request.call_args_list[1].args[1]
        self.assertIn("/lists/list%2Fwith%2Bcharacters/tasks?", first_path)
        query = parse_qs(urlsplit(first_path).query)
        self.assertEqual(query["showHidden"], ["true"])
        self.assertEqual(query["showCompleted"], ["true"])
        self.assertEqual(query["showDeleted"], ["false"])
        self.assertEqual(query["maxResults"], ["100"])
        next_query = parse_qs(urlsplit(client.request.call_args.args[1]).query)
        self.assertEqual(next_query["pageToken"], ["page two"])

    def test_empty_list_does_not_synthesize_tasks(self):
        client = api()
        client.request = Mock(side_effect=[{"id": "list-id", "title": "Empty"}, {}])
        self.assertEqual(client.snapshot()["tasks"], [])

    def test_repeated_page_token_fails_instead_of_looping(self):
        client = api()
        client.request = Mock(return_value={"nextPageToken": "same"})
        with self.assertRaises(bridge.BridgeError):
            client.all_pages("/users/@me/lists")
        self.assertEqual(client.request.call_count, 2)

    def test_update_only_patches_requested_fields_and_uses_etag(self):
        client = api()
        client.request = Mock(return_value={"id": "a/+?", "title": "New title", "etag": '"new"'})
        task = client.update("a/+?", {"description": " New title "}, '"old"')
        self.assertEqual(task["description"], "New title")
        method, path, data, etag = client.request.call_args.args
        self.assertEqual(method, "PATCH")
        self.assertTrue(path.endswith("/a%2F%2B%3F"))
        self.assertEqual(data, {"title": "New title"})
        self.assertEqual(etag, '"old"')
        client.update("a", {"completed": False})
        self.assertEqual(client.request.call_args.args[2], {"status": "needsAction", "completed": None})

    def test_validation_rejects_unmanaged_or_invalid_fields_before_writing(self):
        client = api()
        client.request = Mock()
        for data in ({}, {"description": " "}, {"description": "x" * 1025},
                     {"completed": "true"}, {"notes": "overwrite"}, None, []):
            with self.subTest(data=data), self.assertRaises(bridge.BridgeError):
                client.update("a", data)
        client.request.assert_not_called()

    def test_create_accepts_unicode_and_completion(self):
        client = api()
        client.request = Mock(return_value={"id": "new", "title": "買い物 🥕", "status": "completed", "etag": '"1"'})
        result = client.create({"description": "買い物 🥕", "completed": True})
        self.assertTrue(result["completed"])
        self.assertEqual(client.request.call_args.args[2], {"title": "買い物 🥕", "status": "completed"})

    def test_delete_is_idempotent_but_preserves_conflicts(self):
        client = api()
        client.request = Mock(side_effect=bridge.BridgeError("not_found", "Gone", 404))
        client.delete("a", '"etag"')
        client.request.side_effect = bridge.BridgeError("conflict", "Changed", 409)
        with self.assertRaises(bridge.BridgeError):
            client.delete("a", '"etag"')

    @patch.object(bridge, "request_json")
    def test_refreshes_expired_token_then_retries_a_rejected_token_once(self, transport):
        client = api()
        client.expires_at = 0
        transport.side_effect = [
            {"access_token": "refreshed", "expires_in": 3600},
            bridge.GoogleError(401, "UNAUTHENTICATED"),
            {"access_token": "fresh-again", "expires_in": 3600},
            {"id": "created"},
        ]
        self.assertEqual(client.request("POST", "/example", {"title": "A"}), {"id": "created"})
        self.assertEqual(transport.call_count, 4)
        self.assertEqual(transport.call_args.kwargs["headers"]["Authorization"], "Bearer fresh-again")
        self.assertEqual(transport.call_args_list[0].kwargs["form"]["refresh_token"], "test-refresh")

    def test_ambiguous_writes_are_never_automatically_retried(self):
        for failure in (bridge.GoogleError(503, "UNAVAILABLE"), bridge.BridgeError("offline", "Offline")):
            with self.subTest(failure=failure), patch.object(bridge, "request_json", side_effect=failure) as transport:
                with self.assertRaises(bridge.BridgeError):
                    api().request("POST", "/example", {"title": "A"})
                self.assertEqual(transport.call_count, 1)

    @patch.object(bridge, "request_json", side_effect=bridge.GoogleError(400, "invalid_grant"))
    def test_revoked_refresh_token_requests_sign_in(self, transport):
        client = api()
        client.expires_at = 0
        with self.assertRaises(bridge.BridgeError) as caught:
            client.request("GET", "/example")
        self.assertEqual(caught.exception.code, "sign_in_required")
        self.assertEqual(transport.call_count, 1)

    @patch.object(bridge, "urlopen")
    def test_transport_keeps_credentials_in_headers_and_forms(self, opener):
        opener.return_value = io.BytesIO(b'{"id":"a"}')
        bridge.request_json(bridge.API_URL + "/example", "PATCH", {"title": "Title"},
                            {"Authorization": "Bearer private-token", "If-Match": '"version"'})
        request = opener.call_args.args[0]
        self.assertNotIn("private-token", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer private-token")
        self.assertEqual(request.get_header("If-match"), '"version"')
        self.assertEqual(json.loads(request.data), {"title": "Title"})
        self.assertEqual(opener.call_args.kwargs["timeout"], bridge.NETWORK_TIMEOUT)


class AuthorizationTests(unittest.TestCase):
    def test_loopback_oauth_checks_state_and_exchanges_with_pkce(self):
        captured = {}
        failures = []
        threads = []

        def browser(url):
            captured.update(parse_qs(urlsplit(url).query))

            def visit():
                callback = captured["redirect_uri"][0]
                try:
                    with self.assertRaises(HTTPError) as rejected:
                        urlopen(callback + "?" + urlencode({"state": "wrong 🥕", "code": "bad"}), timeout=2)
                    self.assertEqual(rejected.exception.code, 400)
                    rejected.exception.close()
                except Exception as error:
                    failures.append(error)
                finally:
                    try:
                        query = urlencode({"state": captured["state"][0], "code": "authorization-code"})
                        with urlopen(callback + "?" + query, timeout=2) as response:
                            self.assertEqual(response.status, 200)
                    except Exception as error:
                        failures.append(error)

            thread = threading.Thread(target=visit)
            threads.append(thread)
            thread.start()
            return True

        tokens = {"access_token": "access", "refresh_token": "refresh", "scope": bridge.SCOPE}
        with patch.object(bridge.webbrowser, "open", side_effect=browser), \
                patch.object(bridge, "request_json", return_value=tokens) as transport, \
                contextlib.redirect_stdout(io.StringIO()):
            result = bridge.authorize({"client_id": "id", "client_secret": "secret"}, timeout=5)
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(failures, [])
        self.assertEqual(result, tokens)
        self.assertEqual(captured["scope"], [bridge.SCOPE])
        self.assertEqual(captured["access_type"], ["offline"])
        self.assertEqual(captured["code_challenge_method"], ["S256"])
        form = transport.call_args.kwargs["form"]
        verifier = form["code_verifier"]
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        self.assertEqual(captured["code_challenge"], [expected])
        self.assertEqual(form["code"], "authorization-code")
        self.assertEqual(form["redirect_uri"], captured["redirect_uri"][0])

    def test_credentials_are_private_and_rotated_refresh_tokens_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private/settings.json"
            config = configuration()
            bridge.save_config(path, config)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            client = bridge.GoogleTasksAPI(config, path=path)
            with patch.object(bridge, "request_json", return_value={"access_token": "new", "refresh_token": "rotated"}):
                client.refresh_token()
            self.assertEqual(bridge.load_config(path)["refresh_token"], "rotated")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn("access_token", path.read_text())

    def test_service_is_per_user_and_does_not_embed_credentials(self):
        with tempfile.TemporaryDirectory(prefix="taskwidget space %$") as directory:
            unit = Path(directory) / "systemd/user" / bridge.SERVICE
            script = Path(directory) / "data/google_tasks.py"
            config = Path(directory) / "private/google-tasks.json"
            with patch.object(bridge, "service_paths", return_value=(unit, script)), \
                    patch.object(bridge.shutil, "which", return_value="/usr/bin/systemctl"), \
                    patch.object(bridge.subprocess, "run") as run:
                bridge.install_service(config)
            contents = unit.read_text()
            self.assertIn("%%$$", contents)
            self.assertIn("--config", contents)
            self.assertIn("UMask=0077", contents)
            self.assertNotIn("test-refresh", contents)
            self.assertTrue(script.is_file())
            self.assertEqual(run.call_args.args[0], ["systemctl", "--user", "restart", bridge.SERVICE])
            self.assertTrue(all("--user" in call.args[0] for call in run.call_args_list))

    def test_feature_is_off_by_default(self):
        schema = ET.parse(ROOT / "contents/config/main.xml")
        namespace = {"k": "http://www.kde.org/standards/kcfg/1.0"}
        default = schema.find(".//k:entry[@name='enableGoogleTasks']/k:default", namespace)
        self.assertEqual(default.text, "false")

    def test_disconnect_removes_local_files_when_token_is_already_revoked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "google-tasks.json"
            unit = Path(directory) / bridge.SERVICE
            script = Path(directory) / "google_tasks.py"
            bridge.save_config(path, configuration())
            unit.touch()
            script.touch()
            with patch.object(bridge, "service_paths", return_value=(unit, script)), \
                    patch.object(bridge.subprocess, "run") as run, \
                    patch.object(bridge, "request_json", side_effect=bridge.GoogleError(400, "invalid_token")), \
                    contextlib.redirect_stdout(io.StringIO()):
                bridge.disconnect(SimpleNamespace(config=path))
            self.assertFalse(path.exists())
            self.assertFalse(unit.exists())
            self.assertFalse(script.exists())
            self.assertEqual(run.call_args_list[0].args[0], ["systemctl", "--user", "disable", "--now", bridge.SERVICE])

    def test_disconnect_retains_credentials_if_remote_revocation_cannot_be_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "google-tasks.json"
            unit = Path(directory) / bridge.SERVICE
            script = Path(directory) / "google_tasks.py"
            bridge.save_config(path, configuration())
            with patch.object(bridge, "service_paths", return_value=(unit, script)), \
                    patch.object(bridge, "request_json", side_effect=bridge.BridgeError("offline", "Offline")):
                with self.assertRaises(bridge.BridgeError):
                    bridge.disconnect(SimpleNamespace(config=path))
            self.assertEqual(bridge.load_config(path)["refresh_token"], configuration()["refresh_token"])


class BridgeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.api = api()
        self.api.request = Mock()
        self.server = bridge.BridgeServer(0, configuration()["access_key"], self.api)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%s" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path="/v1/tasks", method="GET", data=None, authenticated=True, headers=None):
        headers = dict(headers or {})
        if authenticated:
            headers["Authorization"] = "Bearer " + configuration()["access_key"]
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, method=method, headers=headers,
                          data=json.dumps(data).encode() if data is not None else None)
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    def test_server_binds_only_to_loopback_and_authenticates_before_google_calls(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, body = self.request(authenticated=False)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "invalid_key")
        self.api.request.assert_not_called()

    def test_browser_origins_and_foreign_hosts_are_rejected(self):
        for headers in ({"Origin": "https://example.com"}, {"Host": "example.com"}):
            with self.subTest(headers=headers):
                status, _ = self.request(headers=headers)
                self.assertEqual(status, 403)
        self.api.request.assert_not_called()

    def test_http_create_edit_and_delete_use_the_selected_google_list(self):
        self.api.request.return_value = {"id": "task/+", "title": "Buy milk", "etag": '"new"'}
        status, body = self.request(method="POST", data={"description": "Buy milk"})
        self.assertEqual(status, 200)
        self.assertEqual(body["task"]["description"], "Buy milk")
        self.assertIn("/lists/list%2Fwith%2Bcharacters/tasks", self.api.request.call_args.args[1])
        self.request("/v1/tasks/task%2F%2B", "PATCH", {"completed": True}, headers={"If-Match": '"old"'})
        self.assertEqual(self.api.request.call_args.args[2], {"status": "completed"})
        self.assertEqual(self.api.request.call_args.args[3], '"old"')
        self.assertTrue(self.api.request.call_args.args[1].endswith("/task%2F%2B"))
        self.assertEqual(self.request("/v1/tasks/task%2F%2B", "DELETE")[0], 200)
        self.assertEqual(self.api.request.call_args.args[0], "DELETE")

    def test_invalid_changes_do_not_reach_google(self):
        status, _ = self.request(method="POST", data={"description": ""})
        self.assertEqual(status, 400)
        self.api.request.assert_not_called()

    def test_google_failures_have_actionable_json_errors(self):
        self.api.request.side_effect = bridge.BridgeError("sign_in_required", "Run setup again.", 401)
        status, body = self.request()
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "sign_in_required")
        self.assertNotIn(configuration()["refresh_token"], json.dumps(body))

    def test_unknown_routes_cannot_proxy_arbitrary_google_endpoints(self):
        self.assertEqual(self.request("/v1/users/@me/lists")[0], 404)
        self.api.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
