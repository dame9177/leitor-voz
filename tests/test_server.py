import http.client
import json

import pytest

from leitor.server import ApiServer, parse_segments


class FakeController:
    def __init__(self):
        self.reads, self.actions, self.settings = [], [], []

    def read(self, segments):
        self.reads.append(segments)
        return "r1"

    def control(self, action):
        self.actions.append(action)

    def update_settings(self, data):
        if data.get("voice") == "robocop":
            raise ValueError("voz desconhecida")
        self.settings.append(data)
        return {"voice": data.get("voice", "marin")}

    def status(self):
        return {"state": "idle"}


@pytest.fixture
def api():
    ctrl = FakeController()
    server = ApiServer(ctrl, port=0)  # random free port
    server.start()
    yield ctrl, server.port
    server.close()


def request(port, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    hdrs = {"Host": host or f"127.0.0.1:{port}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    payload = resp.read()
    return resp.status, json.loads(payload) if payload else None, resp


def test_status(api):
    _, port = api
    assert request(port, "GET", "/status")[:2] == (200, {"state": "idle"})


def test_read_text_from_extension(api):
    ctrl, port = api
    status, body, resp = request(
        port, "POST", "/read", {"text": "Olá"},
        headers={"Origin": "moz-extension://abc"},
    )
    assert (status, body) == (200, {"reading_id": "r1"})
    assert ctrl.reads == [[{"id": "0", "text": "Olá"}]]
    assert resp.getheader("Access-Control-Allow-Origin") == "moz-extension://abc"


def test_web_page_origin_is_rejected(api):
    ctrl, port = api
    status, _, _ = request(port, "POST", "/read", {"text": "x"}, headers={"Origin": "https://evil.com"})
    assert status == 403
    status, _, _ = request(port, "GET", "/status", headers={"Origin": "https://evil.com"})
    assert status == 403
    assert ctrl.reads == []


def test_dns_rebinding_host_is_rejected(api):
    _, port = api
    status, _, _ = request(port, "GET", "/status", host=f"evil.com:{port}")
    assert status == 403


def test_non_json_post_is_rejected(api):
    ctrl, port = api
    status, _, _ = request(
        port, "POST", "/read", headers={"Content-Type": "text/plain", "Content-Length": "0"}
    )
    assert status == 400
    assert ctrl.reads == []


def test_control_validates_action(api):
    ctrl, port = api
    assert request(port, "POST", "/control", {"action": "pause"})[0] == 200
    assert request(port, "POST", "/control", {"action": "explode"})[0] == 400
    assert ctrl.actions == ["pause"]


def test_settings_errors_become_400(api):
    _, port = api
    assert request(port, "POST", "/settings", {"voice": "cedar"})[:2] == (200, {"voice": "cedar"})
    assert request(port, "POST", "/settings", {"voice": "robocop"})[0] == 400


def test_parse_segments():
    assert parse_segments({"segments": [{"id": "a", "text": "x"}, {"id": "b", "text": "  "}]}) == [
        {"id": "a", "text": "x"}
    ]
    with pytest.raises(ValueError):
        parse_segments({"text": "   "})
    with pytest.raises(ValueError):
        parse_segments({"segments": []})
    with pytest.raises(ValueError):
        parse_segments({})
