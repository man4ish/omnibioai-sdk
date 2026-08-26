"""Additional contract tests for SDK boundaries and edge-case request shapes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import responses

from omnibioai import OmniBioAI
from omnibioai._base import BaseServiceClient, _extract_message, _safe_json
from omnibioai.auth.session import AuthenticatedSession
from omnibioai.auth.tokens import TokenPair
from omnibioai.exceptions import ValidationError
from omnibioai.tes.client import TESClient

GATEWAY = "https://gateway.example.com"
AUTH = "https://auth.example.com"


def _client() -> OmniBioAI:
    return OmniBioAI(access_token="access-1", refresh_token="refresh-1", base_url=GATEWAY)


def _response(status_code: int, body=None, reason: str = "Reason") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.reason = reason
    if body is None:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = body
    return response


class TestBaseBoundaryCases:
    def test_request_normalizes_url_and_forwards_kwargs(self):
        session = MagicMock()
        session.last_trace_id = "trace-1"
        session.request.return_value = _response(200, {"ok": True})
        service = BaseServiceClient("https://api.example.com/", session)

        result = service._request("POST", "/v1/items", json={"name": "x"}, timeout=3)

        assert result == {"ok": True}
        session.request.assert_called_once_with(
            "POST", "https://api.example.com/v1/items", json={"name": "x"}, timeout=3
        )

    @pytest.mark.parametrize("status", [204, 302])
    def test_non_error_statuses_return_empty_body(self, status):
        session = MagicMock()
        session.last_trace_id = None
        assert BaseServiceClient("https://api.example.com", session)._parse(_response(status)) is None

    def test_malformed_json_falls_back_to_reason_for_client_error(self):
        session = MagicMock()
        session.last_trace_id = "trace-2"

        with pytest.raises(ValidationError) as exc:
            BaseServiceClient("https://api.example.com", session)._parse(
                _response(400, reason="Bad Request")
            )

        assert str(exc.value) == "Bad Request"
        assert exc.value.trace_id == "trace-2"

    def test_safe_json_returns_none_when_response_is_not_json(self):
        assert _safe_json(_response(200)) is None

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ({"error": "bad"}, "bad"),
            ({"error": "bad", "reason": "because"}, "bad: because"),
            ({"detail": {"reason": "nested reason"}}, "nested reason"),
            ({"detail": ""}, ""),
            ({"error": ""}, None),
        ],
    )
    def test_extract_message_normalizes_known_shapes(self, body, expected):
        assert _extract_message(body) == expected


class TestAuthRequestBoundaryCases:
    @responses.activate
    def test_custom_headers_survive_and_authorization_is_sdk_owned(self):
        session = AuthenticatedSession(TokenPair("access-1", "refresh-1"), AUTH, timeout=7)
        responses.add(responses.GET, f"{GATEWAY}/health", json={"ok": True}, status=200)

        session.request(
            "GET", f"{GATEWAY}/health",
            headers={"X-Client": "demo", "Authorization": "Bearer caller-token"},
        )

        sent = responses.calls[0].request
        assert sent.headers["X-Client"] == "demo"
        assert sent.headers["Authorization"] == "Bearer access-1"
        assert sent.headers["X-Trace-Id"]

    @responses.activate
    def test_retry_flag_prevents_a_second_refresh(self):
        session = AuthenticatedSession(TokenPair("access-1", "refresh-1"), AUTH)
        responses.add(responses.GET, f"{GATEWAY}/health", json={"detail": "expired"}, status=401)

        result = session.request("GET", f"{GATEWAY}/health", _is_retry=True)

        assert result.status_code == 401
        assert len(responses.calls) == 1

    @responses.activate
    def test_refresh_preserves_trace_id_across_original_and_retry(self):
        session = AuthenticatedSession(TokenPair("access-1", "refresh-1"), AUTH)
        responses.add(responses.GET, f"{GATEWAY}/health", json={}, status=401)
        responses.add(responses.POST, f"{AUTH}/auth/refresh", json={"access_token": "access-2"}, status=200)
        responses.add(responses.GET, f"{GATEWAY}/health", json={"ok": True}, status=200)

        session.request("GET", f"{GATEWAY}/health", trace_id="fixed-trace")

        assert responses.calls[0].request.headers["X-Trace-Id"] == "fixed-trace"
        assert responses.calls[2].request.headers["X-Trace-Id"] == "fixed-trace"
        assert session.last_trace_id == "fixed-trace"


class TestServiceParameterEdges:
    @responses.activate
    def test_rag_query_keeps_zero_top_k_and_encodes_query(self):
        c = _client()
        responses.add(responses.POST, f"{GATEWAY}/rag/v1/query", json={"results": []}, status=200)

        c.rag.query("BRCA1 & TP53", top_k=0, mode="structured", hybrid_search=True)

        body = responses.calls[0].request.body.decode()
        assert '"top_k": 0' in body
        assert '"hybrid_search": true' in body
        assert "BRCA1 & TP53" in body

    @responses.activate
    def test_rag_entity_includes_explicit_empty_type(self):
        c = _client()
        responses.add(responses.GET, f"{GATEWAY}/rag/v1/kg/entity", json={"name": "X"}, status=200)

        c.rag.kg_entity("X", type="")

        assert "type=" in responses.calls[0].request.url

    @responses.activate
    def test_models_list_sends_only_the_metric_filter_when_requested(self):
        c = _client()
        responses.add(responses.GET, f"{GATEWAY}/model-registry/v1/models", json={"models": []}, status=200)

        c.models.list(metric_gte="accuracy:0.95")

        url = responses.calls[0].request.url
        assert "metric_gte=accuracy%3A0.95" in url
        assert "task=" not in url
        assert "model_name=" not in url

    @responses.activate
    def test_models_resolve_can_disable_verification(self):
        c = _client()
        responses.add(responses.GET, f"{GATEWAY}/model-registry/v1/resolve", json={"path": "/x"}, status=200)

        c.models.resolve("task", "latest", verify=False)

        assert "verify=False" in responses.calls[0].request.url

    def test_tes_run_request_normalizes_none_inputs(self):
        assert TESClient._run_request("tool", None, None, None) == {
            "tool_id": "tool", "inputs": {}, "resources": {}, "constraints": {}
        }

    @responses.activate
    def test_tes_omits_empty_server_id_query_parameter(self):
        c = _client()
        responses.add(responses.POST, f"{GATEWAY}/tes/api/runs/validate", json={"ok": True}, status=200)

        c.tes.validate("tool", server_id="")

        assert responses.calls[0].request.url == f"{GATEWAY}/tes/api/runs/validate"

    @responses.activate
    def test_workflow_run_preserves_explicit_empty_inputs_and_engine(self):
        c = _client()
        responses.add(
            responses.GET, f"{GATEWAY}/workflow-bundles/v1/workflows/wf",
            json=[{"id": 4, "version": "1.0"}], status=200,
        )
        responses.add(
            responses.POST, f"{GATEWAY}/workflow-bundles/v1/workflows/4/run",
            json={"run_id": "r1"}, status=201,
        )

        c.workflows.run("wf", inputs={}, engine="")

        assert responses.calls[1].request.body.decode() == '{"inputs": {}, "engine": ""}'
