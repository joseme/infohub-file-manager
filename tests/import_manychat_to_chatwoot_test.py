"""Tests for scripts/import_manychat_to_chatwoot.py"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_manychat_to_chatwoot import (  # noqa: E402
    ChatwootAPIError,
    ChatwootClient,
    dedupe_contacts,
    extract_label_titles,
    infer_attribute_type,
    normalize_contact,
    normalize_phone,
    parse_args,
    prepare_contacts,
    run_import,
    sanitize_attribute_key,
    slugify_label,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class FakeSession:
    """Session fake: devuelve respuestas encoladas (la última se repite)."""

    def __init__(self, responses=None):
        self.responses = list(responses or [FakeResponse()])
        self.calls = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


def make_client(responses=None, rate=1000):
    waits = []
    session = FakeSession(responses)
    client = ChatwootClient("https://chat.test", 1, "token-abc", rate_per_sec=rate,
                            session=session, sleep_fn=waits.append)
    return client, session, waits


class TestSlugAndKeys:
    def test_slugify_label_basic(self):
        assert slugify_label("Cliente VIP!") == "cliente-vip"
        assert slugify_label("  Mayorista  ") == "mayorista"

    def test_slugify_label_empty_returns_none(self):
        assert slugify_label("!!!") is None
        assert slugify_label("") is None

    def test_sanitize_attribute_key(self):
        assert sanitize_attribute_key("Plan Anual") == "plan_anual"
        assert sanitize_attribute_key("  Ciudad ") == "ciudad"

    def test_sanitize_attribute_key_invalid_falls_back(self):
        assert sanitize_attribute_key("!!!") == "campo"


class TestNormalizePhone:
    def test_keeps_plus_and_strips_separators(self):
        assert normalize_phone("+54 9 11 2233-44") == "+54911223344"

    def test_digits_only_without_plus(self):
        assert normalize_phone("54911223344") == "54911223344"

    def test_too_short_is_invalid(self):
        assert normalize_phone("123") is None
        assert normalize_phone("") is None
        assert normalize_phone(None) is None


class TestNormalizeContact:
    def test_full_contact(self):
        raw = {
            "id": 42,
            "first_name": "Ana",
            "last_name": "Pérez",
            "phone": "+54911223344",
            "email": "ana@ejemplo.com",
            "tags": ["VIP", "Mayorista"],
            "custom_fields": {"Plan Anual": "Premium"},
        }
        contact = normalize_contact(raw)
        assert contact["name"] == "Ana Pérez"
        assert contact["identifier"] == "42"
        assert contact["phone"] == "+54911223344"
        assert contact["email"] == "ana@ejemplo.com"
        assert contact["labels"] == ["mayorista", "vip"]
        assert contact["custom_attributes"] == {"plan_anual": "Premium"}

    def test_string_tags_split_on_semicolon(self):
        contact = normalize_contact({"name": "B", "tags": "vip; mayorista,nuevo"})
        assert contact["labels"] == ["mayorista", "nuevo", "vip"]

    def test_alternate_field_names(self):
        contact = normalize_contact({
            "name": "C", "phone_number": "+54911000000",
            "custom_attributes": {"Edad": 30},
        })
        assert contact["phone"] == "+54911000000"
        assert contact["custom_attributes"] == {"edad": 30}

    def test_no_identifiers_returns_none(self):
        assert normalize_contact({}) is None
        assert normalize_contact({"tags": ["vip"]}) is None
        assert normalize_contact("no-dict") is None

    def test_name_only_is_kept(self):
        contact = normalize_contact({"first_name": "Solo"})
        assert contact["name"] == "Solo"
        assert contact["phone"] is None


class TestDedupe:
    def test_merges_by_phone_union_labels_and_attrs(self):
        a = normalize_contact({"name": "Ana", "phone": "+5491111", "tags": ["vip"]})
        b = normalize_contact({"name": "", "phone": "5491111", "tags": ["nuevo"],
                               "custom_fields": {"ciudad": "Lima"}})
        merged = dedupe_contacts([a, b])
        assert len(merged) == 1
        assert merged[0]["labels"] == ["nuevo", "vip"]
        assert merged[0]["custom_attributes"] == {"ciudad": "Lima"}

    def test_later_contact_fills_missing_fields(self):
        a = normalize_contact({"name": "Ana"})
        b = normalize_contact({"name": "Ana", "phone": "+5491111", "email": "a@x.com"})
        merged = dedupe_contacts([a, b])
        assert len(merged) == 1
        assert merged[0]["phone"] == "+5491111"
        assert merged[0]["email"] == "a@x.com"

    def test_similar_names_do_not_merge(self):
        """Nombres parecidos pero no iguales NO se fusionan (evita falsos positivos)."""
        a = normalize_contact({"name": "Ana"})
        b = normalize_contact({"name": "Ana 2", "phone": "+5491111"})
        merged = dedupe_contacts([a, b])
        assert len(merged) == 2

    def test_prepare_contacts_counts(self):
        rows = [
            {"name": "Ana", "phone": "+5491111"},
            {"name": "Ana", "phone": "+54 91111"},   # duplicado del anterior
            {"no_identifiers": True},                # inválido
        ]
        contacts, invalid, duplicates = prepare_contacts(rows)
        assert len(contacts) == 1
        assert invalid == 1
        assert duplicates == 1


class TestInferAndExtract:
    def test_infer_attribute_type(self):
        assert infer_attribute_type([True, False]) == "checkbox"
        assert infer_attribute_type([1, 2.5]) == "number"
        assert infer_attribute_type(["a", 1]) == "text"
        assert infer_attribute_type([]) == "text"
        assert infer_attribute_type([True, 1]) == "text"  # mixto → text

    def test_extract_label_titles(self):
        assert extract_label_titles([{"title": "VIP"}, {"name": "Nuevo"}]) == ["VIP", "Nuevo"]
        assert extract_label_titles(["plano"]) == ["plano"]
        assert extract_label_titles({"labels": [{"title": "X"}]}) == ["X"]
        assert extract_label_titles(None) == []


class TestClientRequest:
    def test_success_returns_json(self):
        client, session, _ = make_client([FakeResponse(200, {"ok": True})])
        assert client.request("GET", "/labels") == {"ok": True}
        call = session.calls[0]
        assert call["url"] == "https://chat.test/api/v1/accounts/1/labels"
        assert call["headers"] == {"api_access_token": "token-abc"}

    def test_retries_on_500_then_succeeds(self):
        client, session, waits = make_client(
            [FakeResponse(500, text="boom"), FakeResponse(200, {"payload": []})]
        )
        assert client.request("GET", "/labels") == {"payload": []}
        assert len(session.calls) == 2
        assert waits  # hubo backoff entre intentos

    def test_raises_after_exhausting_attempts(self):
        client, session, _ = make_client([FakeResponse(503, text="down")])
        with pytest.raises(ChatwootAPIError):
            client.request("GET", "/labels", attempts=3)
        assert len(session.calls) == 3

    def test_non_retryable_raises_immediately(self):
        client, session, _ = make_client([FakeResponse(401, text="unauthorized")])
        with pytest.raises(ChatwootAPIError, match="401"):
            client.request("GET", "/labels")
        assert len(session.calls) == 1

    def test_rate_limiting_sleeps_between_calls(self):
        client, _, waits = make_client(rate=5)  # min intervalo 0.2 s
        client.request("GET", "/labels")
        client.request("GET", "/labels")
        assert any(w > 0.1 for w in waits)


class TestContactEndpoints:
    def test_search_contact_by_phone_matches_exact(self):
        responses = [FakeResponse(200, {"payload": [
            {"id": 1, "phone_number": "+5999"},
            {"id": 2, "phone_number": "+5491111"},
        ]})]
        client, _, _ = make_client(responses)
        found = client.search_contact_by_phone("+5491111")
        assert found["id"] == 2

    def test_search_no_match_returns_none(self):
        client, _, _ = make_client([FakeResponse(200, {"payload": []})])
        assert client.search_contact_by_phone("+5491111") is None

    def test_create_contact_sends_expected_body(self):
        client, session, _ = make_client(
            [FakeResponse(200, {"payload": {"contact": {"id": 5}}})]
        )
        created = client.create_contact({
            "name": "Ana", "phone": "+5491111", "email": "a@x.com",
            "custom_attributes": {"plan": "gold"}, "identifier": "42",
        })
        assert created["id"] == 5
        body = session.calls[0]["json"]
        assert body["name"] == "Ana"
        assert body["phone_number"] == "+5491111"
        assert body["identifier"] == "42"
        assert body["custom_attributes"] == {"plan": "gold"}

    def test_set_contact_labels_skips_empty(self):
        client, session, _ = make_client()
        before = len(session.calls)
        client.set_contact_labels(5, [])
        assert len(session.calls) == before

    def test_ensure_labels_creates_only_missing(self):
        client, session, _ = make_client(
            [FakeResponse(200, {"payload": [{"title": "VIP"}]}),
             FakeResponse(200, {})]
        )
        created = client.ensure_labels(["vip", "nuevo"])
        assert created == ["nuevo"]
        posts = [c for c in session.calls if c["method"] == "POST"]
        assert len(posts) == 1
        assert posts[0]["json"] == {"title": "nuevo"}

    def test_ensure_labels_dry_run_writes_nothing(self):
        client, session, _ = make_client(
            [FakeResponse(200, {"payload": []})]
        )
        created = client.ensure_labels(["nuevo"], dry_run=True)
        assert created == ["nuevo"]
        assert all(c["method"] == "GET" for c in session.calls)

    def test_ensure_custom_attributes_creates_only_missing(self):
        client, session, _ = make_client(
            [FakeResponse(200, {"payload": [{"attribute_key": "plan"}]}),
             FakeResponse(200, {})]
        )
        created = client.ensure_custom_attributes({"plan": "text", "ciudad": "text"})
        assert created == ["ciudad"]
        body = [c for c in session.calls if c["method"] == "POST"][0]["json"]
        assert body["attribute_key"] == "ciudad"
        assert body["attribute_display_type"] == "text"
        assert body["attribute_model"] == 1


class TestRunImport:
    def _responses_new_contact(self):
        return [
            FakeResponse(200, {"payload": []}),                     # GET /labels
            FakeResponse(200, {"payload": []}),                     # GET attribute defs
            FakeResponse(200, {}),                                  # POST /labels
            FakeResponse(200, {}),                                  # POST attribute def
            FakeResponse(200, {"payload": []}),                     # GET search (sin match)
            FakeResponse(200, {"payload": {"contact": {"id": 9}}}), # POST /contacts
            FakeResponse(200, {}),                                  # POST labels
        ]

    def test_creates_new_contact_with_labels(self):
        client, session, _ = make_client(self._responses_new_contact())
        contacts, _, _ = prepare_contacts(
            [{"name": "Ana", "phone": "+5491111", "tags": ["vip"],
              "custom_fields": {"Plan": "gold"}}]
        )
        summary = run_import(client, contacts)
        assert summary["created"] == 1
        assert summary["failed"] == 0
        methods = [(c["method"], c["url"].split("/accounts/1")[-1]) for c in session.calls]
        assert ("POST", "/contacts") in methods
        assert ("POST", "/contacts/9/labels") in methods

    def test_skips_existing_by_default(self):
        responses = [
            FakeResponse(200, {"payload": []}),   # GET /labels
            FakeResponse(200, {"payload": []}),   # GET attribute defs
            FakeResponse(200, {"payload": [       # GET search → existe
                {"id": 7, "phone_number": "+5491111", "name": "Vieja",
                 "email": "", "labels": [], "custom_attributes": {}}],
            }),
        ]
        client, session, _ = make_client(responses)
        contacts, _, _ = prepare_contacts([{"name": "Ana", "phone": "+5491111"}])
        summary = run_import(client, contacts)
        assert summary["skipped"] == 1
        assert summary["created"] == 0
        assert all(c["method"] == "GET" for c in session.calls)

    def test_update_existing_merges_labels_and_attrs(self):
        responses = [
            FakeResponse(200, {"payload": []}),   # GET /labels (ensure_labels)
            FakeResponse(200, {}),                # POST /labels "vip"
            FakeResponse(200, {"payload": []}),   # GET custom_attribute_definitions
            FakeResponse(200, {}),                # POST custom_attribute_definitions
            FakeResponse(200, {"payload": [       # GET search → existe
                {"id": 7, "phone_number": "+5491111", "name": "Vieja",
                 "email": "", "labels": [{"title": "vieja"}],
                 "custom_attributes": {"plan": "viejo"}}],
            }),
            FakeResponse(200, {}),                # PUT /contacts/7
            FakeResponse(200, {}),                # POST /contacts/7/labels
        ]
        client, session, _ = make_client(responses)
        contacts, _, _ = prepare_contacts(
            [{"name": "Ana", "phone": "+5491111", "tags": ["vip"],
              "custom_fields": {"plan": "oro"}}]
        )
        summary = run_import(client, contacts, update_existing=True)
        assert summary["updated"] == 1
        put = [c for c in session.calls if c["method"] == "PUT"][0]
        assert put["url"].endswith("/contacts/7")
        assert put["json"]["custom_attributes"] == {"plan": "oro"}
        labels_post = [c for c in session.calls if c["method"] == "POST" and c["url"].endswith("/contacts/7/labels")][0]
        assert sorted(labels_post["json"]["labels"]) == ["vieja", "vip"]

    def test_dry_run_never_writes(self):
        client, session, _ = make_client(self._responses_new_contact())
        contacts, _, _ = prepare_contacts([{"name": "Ana", "phone": "+5491111"}])
        summary = run_import(client, contacts, dry_run=True)
        assert summary["created"] == 1
        assert all(c["method"] == "GET" for c in session.calls)

    def test_failure_is_recorded_and_does_not_raise(self):
        responses = [
            FakeResponse(200, {"payload": []}),   # GET /labels (sin labels que crear)
            FakeResponse(200, {"payload": []}),   # GET attribute definitions (nada que crear)
            FakeResponse(200, {"payload": []}),   # GET search → sin match
            FakeResponse(500, text="boom"),       # POST /contacts falla siempre
        ]
        client, _, _ = make_client(responses)
        contacts, _, _ = prepare_contacts([{"name": "Ana", "phone": "+5491111"}])
        summary = run_import(client, contacts)
        assert summary["created"] == 0
        assert summary["failed"] == 1
        assert "500" in summary["errors"][0]["error"]


class TestParseArgs:
    def test_requires_input(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_flags_and_values(self):
        args = parse_args([
            "--input", "c.json", "--chatwoot-url", "https://chat.test",
            "--account-id", "3", "--api-token", "tk", "--rate", "2",
            "--dry-run", "--update-existing", "--report", "r.json",
        ])
        assert args.input == "c.json"
        assert args.account_id == 3
        assert args.rate == 2
        assert args.dry_run is True
        assert args.update_existing is True
        assert args.report == "r.json"


class TestReportFile:
    def test_main_writes_report(self, tmp_path):
        """main() de punta a punta con API fake: reporte JSON escrito."""
        input_path = tmp_path / "contacts.json"
        input_path.write_text(json.dumps([
            {"name": "Ana", "phone": "+5491111", "tags": ["vip"]},
        ]), encoding="utf-8")
        report_path = tmp_path / "report.json"

        responses = [
            FakeResponse(200, {"payload": []}),
            FakeResponse(200, {"payload": []}),
            FakeResponse(200, {}),
            FakeResponse(200, {"payload": []}),
            FakeResponse(200, {"payload": {"contact": {"id": 9}}}),
            FakeResponse(200, {}),
        ]
        session = FakeSession(responses)
        waits = []

        from import_manychat_to_chatwoot import main
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("import_manychat_to_chatwoot.ChatwootClient",
                       lambda *a, **kw: ChatwootClient(
                           kw.get("base_url", a[0] if a else "https://chat.test"),
                           1, "tk", rate_per_sec=1000,
                           session=session, sleep_fn=waits.append))
            # ChatwootClient se construye con (url, account, token, rate_per_sec=...)
            exit_code = main([
                "--input", str(input_path),
                "--chatwoot-url", "https://chat.test",
                "--account-id", "1",
                "--api-token", "tk",
                "--report", str(report_path),
            ])

        assert exit_code == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["created"] == 1
        assert report["failed"] == 0
