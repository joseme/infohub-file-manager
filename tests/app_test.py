"""Tests for InfoHubFileManager"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from app import InfoHubFileManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager():
    """Return an InfoHubFileManager with a minimal config dict.
    By default all workspaces are considered accessible (legacy tests).
    """
    # Isolate from real env vars so config values win (os.getenv takes precedence)
    with patch.dict(os.environ, {
        "ANYTHINGLLM_API_KEY": "",
        "ANYTHINGLLM_BASE_URL": "",
        "OLLAMA_BASE_URL": "",
        "OLLAMA_MODEL": "",
        "IMAGE_DESCRIPTION_ACTIVATE": "",
        "WATCHED_FOLDERS_ROOT": "",
    }):
        # Block real HTTP calls by default. Tests that need specific responses
        # patch requests.get/post themselves.
        with patch("requests.get", return_value=MagicMock(spec=requests.Response)) as mock_get:
            mock_get.return_value.status_code = 500
            mgr = InfoHubFileManager(config={
                "anythingllm_api_key": "test-api-key",
                "anythingllm_base_url": "https://test.infohub.example.com",
                "ollama_base_url": "http://localhost:11434",
                "ollama_model": "llava:latest",
                "image_description_active": True,
                "watched_folders_root": "/test/watched",
            })
            # Default for existing tests: treat all workspaces as accessible
            # so scan/sort/full-upload tests keep working without access-control noise.
            with patch.object(mgr, "is_workspace_accessible", return_value=True):
                yield mgr


@pytest.fixture
def real_access_manager():
    """Return an InfoHubFileManager where is_workspace_accessible is real (not patched).
    Use this for tests that specifically verify access-control behavior.
    """
    with patch.dict(os.environ, {
        "ANYTHINGLLM_API_KEY": "",
        "ANYTHINGLLM_BASE_URL": "",
        "OLLAMA_BASE_URL": "",
        "OLLAMA_MODEL": "",
        "IMAGE_DESCRIPTION_ACTIVATE": "",
        "WATCHED_FOLDERS_ROOT": "",
    }):
        with patch("requests.get", return_value=MagicMock(spec=requests.Response)):
            yield InfoHubFileManager(config={
                "anythingllm_api_key": "test-api-key",
                "anythingllm_base_url": "https://test.infohub.example.com",
                "ollama_base_url": "http://localhost:11434",
                "ollama_model": "llava:latest",
                "image_description_active": True,
                "watched_folders_root": "/test/watched",
            })


@pytest.fixture
def manager_without_config():
    """Return an InfoHubFileManager without config (reads env vars)."""
    with patch.dict(os.environ, {
        "ANYTHINGLLM_API_KEY": "env-api-key",
        "ANYTHINGLLM_BASE_URL": "https://env.example.com",
        "OLLAMA_BASE_URL": "http://env-ollama:11434",
        "OLLAMA_MODEL": "llama3",
        "IMAGE_DESCRIPTION_ACTIVATE": "true",
        "WATCHED_FOLDERS_ROOT": "/env/watched",
    }, clear=True):
        return InfoHubFileManager()


@pytest.fixture
def watched_dir(tmp_path: Path):
    """Create a temporary watched directory with sample folder structure.

    Structure:
        tmp_path/Infohub_Tech/
            WorkspaceA/
                doc1.pdf
                doc2.txt
                image1.jpg
            WorkspaceB/
                report.docx
        tmp_path/AnythingLLM_Team/
            TeamSpace/
                notes.md
    """
    # Create Infohub_Tech workspace folders
    (tmp_path / "Infohub_Tech" / "WorkspaceA").mkdir(parents=True)
    (tmp_path / "Infohub_Tech" / "WorkspaceB").mkdir(parents=True)
    (tmp_path / "AnythingLLM_Team" / "TeamSpace").mkdir(parents=True)

    # Create sample files
    for fname in ["doc1.pdf", "doc2.txt", "image1.jpg"]:
        (tmp_path / "Infohub_Tech" / "WorkspaceA" / fname).write_text("content")
    (tmp_path / "Infohub_Tech" / "WorkspaceB" / "report.docx").write_text("content")
    (tmp_path / "AnythingLLM_Team" / "TeamSpace" / "notes.md").write_text("content")
    return tmp_path


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_init_with_config(self, manager):
        assert manager.api_key == "test-api-key"
        assert manager.base_url == "https://test.infohub.example.com"
        assert manager.watched_root == "/test/watched"
        assert manager.image_description_active is True
        assert manager.ollama_model == "llava:latest"

    def test_init_without_config_uses_env(self, manager_without_config):
        assert manager_without_config.api_key == "env-api-key"
        assert manager_without_config.base_url == "https://env.example.com"
        assert manager_without_config.watched_root == "/env/watched"
        assert manager_without_config.image_description_active is True
        assert manager_without_config.ollama_model == "llama3"

    @patch.dict(os.environ, {}, clear=True)
    def test_init_without_config_no_env_uses_defaults(self):
        """With no env vars and no config, should use hardcoded defaults."""
        m = InfoHubFileManager()
        assert m.api_key == ""
        assert m.base_url == "http://localhost:3000"
        assert m.watched_root == ""
        assert m.image_description_active is True  # from "true" default
        assert m.ollama_model == "llava:latest"


# ---------------------------------------------------------------------------
# get_workspace_slug
# ---------------------------------------------------------------------------


class TestGetWorkspaceSlug:
    def test_converts_to_lowercase_dash(self, manager):
        assert manager.get_workspace_slug("My Workspace") == "my-workspace"

    def test_handles_underscores(self, manager):
        assert manager.get_workspace_slug("My_Workspace_Name") == "my-workspace-name"

    def test_handles_mixed(self, manager):
        assert manager.get_workspace_slug("Hello  World_Test") == "hello--world-test"

    def test_already_slug(self, manager):
        assert manager.get_workspace_slug("already-slug") == "already-slug"


# ---------------------------------------------------------------------------
# scan_files
# ---------------------------------------------------------------------------


class TestScanFiles:
    def test_no_root_configured(self, manager):
        manager.watched_root = ""
        result = manager.scan_files()
        assert result["status"] == "error"
        assert "not configured" in result["message"]

    def test_root_does_not_exist(self, manager, tmp_path):
        manager.watched_root = str(tmp_path / "nonexistent")
        result = manager.scan_files()
        assert result["status"] == "error"
        assert "does not exist" in result["message"]

    def test_scan_with_files(self, manager, watched_dir):
        manager.watched_root = str(watched_dir)
        result = manager.scan_files()

        assert result["status"] == "success"
        assert result["total_workspaces"] == 3
        assert result["total_files"] == 5

        workspaces = result["workspaces"]
        assert "WorkspaceA" in workspaces
        assert "WorkspaceB" in workspaces
        assert "TeamSpace" in workspaces

        ws_a_files = workspaces["WorkspaceA"]["files"]
        assert "doc1.pdf" in ws_a_files
        assert "doc2.txt" in ws_a_files
        # image1.jpg has no .image_description.txt suffix, so it should be included
        assert "image1.jpg" in ws_a_files

    def test_scan_image_description_files_excluded(self, manager, watched_dir):
        """Files ending with .image_description or .image_description.txt should be excluded."""
        ws_a = watched_dir / "Infohub_Tech" / "WorkspaceA"
        (ws_a / "photo.jpg.image_description.txt").write_text("a description")
        (ws_a / "photo.jpg.image_description").write_text("another")

        manager.watched_root = str(watched_dir)
        result = manager.scan_files()

        ws_a_files = result["workspaces"]["WorkspaceA"]["files"]
        assert "photo.jpg.image_description.txt" not in ws_a_files
        assert "photo.jpg.image_description" not in ws_a_files

    def test_scan_empty_workspace(self, manager, watched_dir):
        """A workspace folder with no files should appear with file_count=0."""
        (watched_dir / "Infohub_Tech" / "EmptyWS").mkdir()
        manager.watched_root = str(watched_dir)
        result = manager.scan_files()

        assert "EmptyWS" in result["workspaces"]
        assert result["workspaces"]["EmptyWS"]["file_count"] == 0

    def test_scan_non_prefixed_folders_ignored(self, manager, watched_dir):
        """Folders not starting with Infohub or AnythingLLM should be ignored."""
        (watched_dir / "OtherFolder" / "SomeWS").mkdir(parents=True)
        (watched_dir / "OtherFolder" / "SomeWS" / "file.txt").write_text("data")
        manager.watched_root = str(watched_dir)
        result = manager.scan_files()

        assert "SomeWS" not in result["workspaces"]

    def test_scan_deduplicates_across_parent_dirs(self, manager, watched_dir):
        """Same workspace name under two matching parents should appear once."""
        # watched_dir already has Infohub_Tech/WorkspaceA with 3 files
        # Create a second matching parent with same workspace name
        (watched_dir / "Infohub_Backup" / "WorkspaceA").mkdir(parents=True)
        (watched_dir / "Infohub_Backup" / "WorkspaceA" / "extra.txt").write_text("x")

        manager.watched_root = str(watched_dir)
        result = manager.scan_files()

        # WorkspaceA appears under Infohub_Tech and Infohub_Backup
        assert "WorkspaceA" in result["workspaces"]
        # Should appear only ONCE (deduplication)
        # total_files must NOT double-count WorkspaceA
        total_from_dict = sum(ws["file_count"] for ws in result["workspaces"].values())
        assert result["total_files"] == total_from_dict


# ---------------------------------------------------------------------------
# get_workspace_documents
# ---------------------------------------------------------------------------


class TestGetWorkspaceDocuments:
    def test_successful_response(self, manager):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "workspace": [{
                "documents": [
                    {"id": "1", "docpath": "doc1.uuid.json"},
                    {"id": "2", "docpath": "subdir/doc2.uuid.json"},
                    {"id": "3", "docpath": "report.final.json"},
                ]
            }]
        }

        with patch("requests.get", return_value=mock_response) as mock_get:
            result = manager.get_workspace_documents("My Workspace")

        # Verify the API call
        mock_get.assert_called_once_with(
            "https://test.infohub.example.com/api/v1/workspace/my-workspace",
            headers={
                "Authorization": "Bearer test-api-key",
                "accept": "application/json",
            },
            timeout=10,
        )

        # Verify parsed results
        assert "base_names" in result
        assert "doc_names" in result
        assert "raw_docs" in result
        assert "exists" in result
        assert result["exists"] is True
        assert result["base_names"] == {"doc1.uuid", "doc2.uuid", "report.final"}
        assert result["doc_names"]["doc1.uuid"] == "doc1.uuid.json"

    def test_list_response_format(self, manager):
        """Handle the case where the API returns a list instead of dict."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [{
            "documents": [
                {"id": "1", "docpath": "mydoc.abc.json"},
            ]
        }]

        with patch("requests.get", return_value=mock_response):
            result = manager.get_workspace_documents("Test")

        assert "mydoc.abc" in result["base_names"]
        assert result["exists"] is True

    def test_empty_documents(self, manager):
        """A workspace with no documents should return empty sets."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"workspace": [{"documents": []}]}

        with patch("requests.get", return_value=mock_response):
            result = manager.get_workspace_documents("Empty")

        assert result["base_names"] == set()
        assert result["doc_names"] == {}
        assert result["raw_docs"] == []
        assert result["exists"] is True

    def test_api_error_status(self, manager):
        """Non-200 status should return empty sets and log a warning."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500

        with patch("requests.get", return_value=mock_response):
            with patch("app.logger.warning") as mock_warn:
                result = manager.get_workspace_documents("FailWS")

        assert result["base_names"] == set()
        assert result["exists"] is False
        mock_warn.assert_called_once()

    def test_network_error(self, manager):
        """A network exception should return empty sets without crashing."""
        with patch("requests.get", side_effect=requests.ConnectionError("No network")):
            with patch("app.logger.error") as mock_err:
                result = manager.get_workspace_documents("FailWS")

        assert result["base_names"] == set()
        assert result["exists"] is False
        mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# create_workspace
# ---------------------------------------------------------------------------


class TestCreateWorkspace:
    def test_create_success(self, manager):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = manager.create_workspace("NewWS")

        assert result is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://test.infohub.example.com/api/v1/workspace/new"
        assert kwargs["json"] == {"name": "NewWS"}
        assert kwargs["timeout"] == 10

    def test_create_201(self, manager):
        """201 status should also be treated as success."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 201

        with patch("requests.post", return_value=mock_response):
            result = manager.create_workspace("NewWS")

        assert result is True

    def test_create_already_exists(self, manager):
        """400 status means workspace already exists."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 400

        with patch("requests.post", return_value=mock_response):
            result = manager.create_workspace("ExistingWS")

        assert result is False

    def test_create_api_error(self, manager):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("requests.post", return_value=mock_response):
            with patch("app.logger.warning") as mock_warn:
                result = manager.create_workspace("FailWS")

        assert result is False
        mock_warn.assert_called_once()

    def test_create_network_error(self, manager):
        with patch("requests.post", side_effect=requests.ConnectionError("No network")):
            with patch("app.logger.error") as mock_err:
                result = manager.create_workspace("FailWS")

        assert result is False
        mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# _update_embeddings
# ---------------------------------------------------------------------------


class TestUpdateEmbeddings:
    def test_update_skips_already_embedded_docs(self, manager):
        """Docs already registered in workspace must NOT be re-sent as adds
        (re-adding creates duplicate rows in workspace_documents)."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200

        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": {"doc1"},
            "doc_names": {"doc1": "doc1.json"},
            "raw_docs": [{"docpath": "custom-documents/doc1.json"}],
        }):
            with patch("requests.post", return_value=mock_response) as mock_post:
                result = manager._update_embeddings("MyWorkspace")

        assert result is True
        mock_post.assert_not_called()

    def test_update_sends_only_new_documents(self, manager):
        """Only unregistered documents-area docpaths go into adds."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200

        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": {"doc1"},
            "doc_names": {"doc1": "doc1.json"},
            "raw_docs": [{"docpath": "custom-documents/doc1.json"}],
        }):
            with patch.object(
                manager,
                "_get_documents_area_docpaths",
                return_value=["custom-documents/doc1.json", "custom-documents/doc2.json"],
            ):
                with patch("requests.post", return_value=mock_response) as mock_post:
                    result = manager._update_embeddings("MyWorkspace")

        assert result is True
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["adds"] == ["custom-documents/doc2.json"]

    def test_update_no_docs(self, manager):
        """Workspace with no documents should return True (nothing to embed)."""
        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": set(),
            "doc_names": {},
            "raw_docs": [],
        }):
            result = manager._update_embeddings("EmptyWS")
        assert result is True

    def test_update_workspace_not_found(self, manager):
        """Non-existent workspace should return False."""
        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": False,
            "base_names": set(),
            "doc_names": {},
            "raw_docs": [],
        }):
            result = manager._update_embeddings("NoExist")
        assert result is False

    def test_update_api_error(self, manager):
        """API error should return False."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500
        mock_response.text = "Server error"

        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": {"doc1"},
            "doc_names": {"doc1": "doc1.json"},
            "raw_docs": [{"docpath": "custom-documents/doc1.json"}],
        }):
            with patch.object(
                manager,
                "_get_documents_area_docpaths",
                return_value=["custom-documents/doc2.json"],
            ):
                with patch("requests.post", return_value=mock_response):
                    result = manager._update_embeddings("MyWorkspace")
        assert result is False

    def test_update_network_error(self, manager):
        """Network error should return False after retries are exhausted."""
        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": {"doc1"},
            "doc_names": {"doc1": "doc1.json"},
            "raw_docs": [{"docpath": "custom-documents/doc1.json"}],
        }):
            with patch.object(
                manager,
                "_get_documents_area_docpaths",
                return_value=["custom-documents/doc2.json"],
            ):
                with patch("requests.post", side_effect=requests.ConnectionError("Timeout")):
                    with patch("time.sleep"):
                        result = manager._update_embeddings("MyWorkspace")
        assert result is False

    def test_update_retries_on_504_then_success(self, manager):
        """504 on first attempt, 200 on retry → True, two POST calls."""
        mock_504 = MagicMock(spec=requests.Response)
        mock_504.status_code = 504
        mock_504.text = "Gateway Time-out"
        mock_200 = MagicMock(spec=requests.Response)
        mock_200.status_code = 200

        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": {"doc1"},
            "doc_names": {"doc1": "doc1.json"},
            "raw_docs": [{"docpath": "custom-documents/doc1.json"}],
        }):
            with patch.object(
                manager,
                "_get_documents_area_docpaths",
                return_value=["custom-documents/doc2.json"],
            ):
                with patch("requests.post", side_effect=[mock_504, mock_200]) as mock_post:
                    with patch("time.sleep") as mock_sleep:
                        result = manager._update_embeddings("MyWorkspace")

        assert result is True
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once()

    def test_update_retries_exhausted_on_504(self, manager):
        """Persistent 504 → False after max retries."""
        mock_504 = MagicMock(spec=requests.Response)
        mock_504.status_code = 504
        mock_504.text = "Gateway Time-out"

        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": {"doc1"},
            "doc_names": {"doc1": "doc1.json"},
            "raw_docs": [{"docpath": "custom-documents/doc1.json"}],
        }):
            with patch.object(
                manager,
                "_get_documents_area_docpaths",
                return_value=["custom-documents/doc2.json"],
            ):
                with patch("requests.post", return_value=mock_504) as mock_post:
                    with patch("time.sleep"):
                        result = manager._update_embeddings("MyWorkspace")

        assert result is False
        assert mock_post.call_count == 3

    def test_update_retries_on_network_error(self, manager):
        """Network error on first attempt, 200 on retry → True."""
        mock_200 = MagicMock(spec=requests.Response)
        mock_200.status_code = 200

        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": {"doc1"},
            "doc_names": {"doc1": "doc1.json"},
            "raw_docs": [{"docpath": "custom-documents/doc1.json"}],
        }):
            with patch.object(
                manager,
                "_get_documents_area_docpaths",
                return_value=["custom-documents/doc2.json"],
            ):
                with patch("requests.post", side_effect=[requests.ConnectionError("Timeout"), mock_200]) as mock_post:
                    with patch("time.sleep"):
                        result = manager._update_embeddings("MyWorkspace")

        assert result is True
        assert mock_post.call_count == 2

    def test_update_falls_back_to_documents_area_when_listing_empty(self, manager):
        """InfoHub behavior: uploads land in documents/{slug}/ but are NOT registered
        in the workspace listing until processed. _update_embeddings must find the
        docpaths in the documents area and embed them anyway."""
        mock_docs_response = MagicMock(spec=requests.Response)
        mock_docs_response.status_code = 200
        mock_docs_response.json.return_value = {
            "localFiles": {
                "name": "documents",
                "type": "folder",
                "items": [
                    {"name": "custom-documents", "type": "folder", "items": []},
                    {"name": "blawd", "type": "folder", "items": [
                        {"name": "Blawd-Profile-2026-(2).pdf-402c5c3a-68ec-4a88-a81d-b268285c722b.json", "type": "file"},
                        {"name": "Menu.png-d3c13eca-021c-4af4-8ec0-06ccb7552abb.json", "type": "file"},
                    ]},
                ],
            }
        }

        mock_embed_response = MagicMock(spec=requests.Response)
        mock_embed_response.status_code = 200

        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": set(),
            "doc_names": {},
            "raw_docs": [],
        }):
            with patch("requests.get", return_value=mock_docs_response) as mock_get:
                with patch("requests.post", return_value=mock_embed_response) as mock_post:
                    result = manager._update_embeddings("blawd")

        assert result is True
        # Documents area queried for the workspace slug
        mock_get.assert_called_once_with(
            "https://test.infohub.example.com/api/v1/documents",
            headers={
                "Authorization": "Bearer test-api-key",
                "accept": "application/json",
            },
            timeout=10,
        )
        # Embeddings triggered with the documents-area docpaths
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["adds"] == [
            "blawd/Blawd-Profile-2026-(2).pdf-402c5c3a-68ec-4a88-a81d-b268285c722b.json",
            "blawd/Menu.png-d3c13eca-021c-4af4-8ec0-06ccb7552abb.json",
        ]

    def test_update_no_docs_anywhere_returns_true(self, manager):
        """Workspace listing empty AND documents area has no matching folder:
        nothing to embed, return True."""
        mock_docs_response = MagicMock(spec=requests.Response)
        mock_docs_response.status_code = 200
        mock_docs_response.json.return_value = {
            "localFiles": {"name": "documents", "type": "folder", "items": []}
        }

        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": set(),
            "doc_names": {},
            "raw_docs": [],
        }):
            with patch("requests.get", return_value=mock_docs_response):
                with patch("requests.post") as mock_post:
                    result = manager._update_embeddings("EmptyWS")

        assert result is True
        mock_post.assert_not_called()

    def test_update_merges_partial_listing_with_documents_area(self, manager):
        """Partial workspace listing: doc1 registered, doc2 only in the
        documents area. Only the unregistered one goes into adds."""
        mock_docs_response = MagicMock(spec=requests.Response)
        mock_docs_response.status_code = 200
        mock_docs_response.json.return_value = {
            "localFiles": {
                "name": "documents",
                "type": "folder",
                "items": [
                    {"name": "blawd", "type": "folder", "items": [
                        {"name": "doc1.json", "type": "file"},
                        {"name": "doc2.json", "type": "file"},
                    ]},
                ],
            }
        }

        mock_embed_response = MagicMock(spec=requests.Response)
        mock_embed_response.status_code = 200

        with patch.object(manager, "get_workspace_documents", return_value={
            "exists": True,
            "base_names": {"doc1"},
            "doc_names": {"doc1": "doc1.json"},
            "raw_docs": [{"docpath": "blawd/doc1.json"}],
        }):
            with patch("requests.get", return_value=mock_docs_response):
                with patch("requests.post", return_value=mock_embed_response) as mock_post:
                    result = manager._update_embeddings("blawd")

        assert result is True
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["adds"] == ["blawd/doc2.json"]


# ---------------------------------------------------------------------------
# file_exists_in_workspace
# ---------------------------------------------------------------------------


class TestFileExistsInWorkspace:
    def test_file_exists(self, manager):
        """Should return True when the file's stem is in base_names."""
        with patch.object(manager, "get_workspace_documents", return_value={
            "base_names": {"doc1", "doc2"},
            "doc_names": {"doc1": "doc1.json", "doc2": "doc2.json"},
            "raw_docs": [],
        }):
            assert manager.file_exists_in_workspace(Path("/some/path/doc1.pdf"), "WS") is True

    def test_file_does_not_exist(self, manager):
        """Should return False when the file's stem is not in base_names."""
        with patch.object(manager, "get_workspace_documents", return_value={
            "base_names": {"doc1", "doc2"},
            "doc_names": {"doc1": "doc1.json", "doc2": "doc2.json"},
            "raw_docs": [],
        }):
            assert manager.file_exists_in_workspace(Path("/some/path/doc3.pdf"), "WS") is False

    def test_file_exists_with_uuid_suffix(self, manager):
        """Real-world case: docpath has UUID like 'doc1.abc123.json'."""
        with patch.object(manager, "get_workspace_documents", return_value={
            "base_names": {"doc1.abc123", "doc2.def456"},
            "doc_names": {"doc1.abc123": "doc1.abc123.json", "doc2.def456": "doc2.def456.json"},
            "raw_docs": [],
        }):
            assert manager.file_exists_in_workspace(Path("/some/path/doc1.pdf"), "WS") is True
            assert manager.file_exists_in_workspace(Path("/some/path/doc2.txt"), "WS") is True
            assert manager.file_exists_in_workspace(Path("/some/path/doc3.pdf"), "WS") is False

    def test_file_exists_in_documents_area_only(self, manager):
        """Empty listing but docpath exists in documents area (slug/stem-uuid.json)."""
        with patch.object(manager, "get_workspace_documents", return_value={
            "base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True,
        }):
            with patch.object(
                manager,
                "_get_documents_area_docpaths",
                return_value=["ws/doc1-abc123.json", "ws/doc2-xyz789.json"],
            ):
                assert manager.file_exists_in_workspace(Path("/some/path/doc1.pdf"), "WS") is True
                assert manager.file_exists_in_workspace(Path("/some/path/nope.pdf"), "WS") is False

    def test_file_exists_with_hyphen_separator(self, manager):
        """Listing base_names with hyphen separator (report-uuid)."""
        with patch.object(manager, "get_workspace_documents", return_value={
            "base_names": {"report-402c5c3a"},
            "doc_names": {"report-402c5c3a": "report-402c5c3a.json"},
            "raw_docs": [],
        }):
            assert manager.file_exists_in_workspace(Path("/some/path/report.pdf"), "WS") is True

    def test_file_exists_slugified_name_with_spaces(self, manager):
        """Real server format: 'Daniel Reis ... Essentials.pdf' is stored as
        'Daniel-Reis-...-Essentials.pdf-<uuid>.json' (spaces → dashes).
        Prefix match must survive the slugification."""
        base = "Daniel-Reis-Odoo-Development-Essentials.pdf-d61da6b2-09ff-43dd-9c8c-6acb4bc58b6c"
        with patch.object(manager, "get_workspace_documents", return_value={
            "base_names": {base},
            "doc_names": {base: f"{base}.json"},
            "raw_docs": [],
        }):
            assert manager.file_exists_in_workspace(
                Path("/docs/Daniel Reis Odoo Development Essentials.pdf"), "odoo"
            ) is True

    def test_file_exists_slugified_name_with_commas_and_underscores(self, manager):
        base = "Odoo-11-Development-Cookbook_-Over-120-unique-recipes-bc196923-7918-4854-9368-1f389c2bf9c6"
        with patch.object(manager, "get_workspace_documents", return_value={
            "base_names": {base},
            "doc_names": {base: f"{base}.json"},
            "raw_docs": [],
        }):
            assert manager.file_exists_in_workspace(
                Path("/docs/Odoo 11 Development Cookbook_ Over 120 unique recipes.epub"), "odoo"
            ) is True

    def test_file_exists_slugified_name_with_accents(self, manager):
        base = "informe-ano-2024.pdf-d61da6b2-09ff-43dd-9c8c-6acb4bc58b6c"
        with patch.object(manager, "get_workspace_documents", return_value={
            "base_names": {base},
            "doc_names": {base: f"{base}.json"},
            "raw_docs": [],
        }):
            assert manager.file_exists_in_workspace(Path("/docs/informe año 2024.pdf"), "ws") is True

    def test_different_file_not_matched_as_slugified_duplicate(self, manager):
        base = "Daniel-Reis-Odoo-Development-Essentials.pdf-d61da6b2-09ff-43dd-9c8c-6acb4bc58b6c"
        with patch.object(manager, "get_workspace_documents", return_value={
            "base_names": {base},
            "doc_names": {base: f"{base}.json"},
            "raw_docs": [],
        }):
            assert manager.file_exists_in_workspace(
                Path("/docs/Greg Moss Working with Odoo.pdf"), "odoo"
            ) is False


# ---------------------------------------------------------------------------
# delete_documents
# ---------------------------------------------------------------------------


class TestDeleteDocuments:
    def test_delete_success(self, manager):
        """Successful deletion should return (True, count, [])."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200

        with patch("requests.delete", return_value=mock_response) as mock_delete:
            success, count, errors = manager.delete_documents(["doc1.uuid.json", "doc2.abc.json"])

        assert success is True
        assert count == 2
        assert errors == []

        mock_delete.assert_called_once_with(
            "https://test.infohub.example.com/api/v1/system/remove-documents",
            headers={
                "Authorization": "Bearer test-api-key",
                "Content-Type": "application/json",
                "accept": "application/json",
            },
            json={"names": ["doc1.uuid.json", "doc2.abc.json"]},
            timeout=30,
        )

    def test_delete_empty_list(self, manager):
        """Empty doc list should succeed immediately without API call."""
        success, count, errors = manager.delete_documents([])
        assert success is True
        assert count == 0
        assert errors == []

    def test_delete_api_error(self, manager):
        """API error should return failure details."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 400
        mock_response.text = "Invalid request"

        with patch("requests.delete", return_value=mock_response):
            with patch("app.logger.warning") as mock_warn:
                success, count, errors = manager.delete_documents(["doc1.json"])

        assert success is False
        assert count == 0
        assert len(errors) > 0
        mock_warn.assert_called_once()

    def test_delete_network_error(self, manager):
        """Network error during deletion should be caught."""
        with patch("requests.delete", side_effect=requests.ConnectionError("Timeout")):
            with patch("app.logger.error") as mock_err:
                success, count, errors = manager.delete_documents(["doc1.json"])

        assert success is False
        assert count == 0
        assert len(errors) > 0
        mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# upload_file_to_workspace
# ---------------------------------------------------------------------------


class TestUploadFileToWorkspace:
    MOCK_DOCS_EXISTS = {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True}

    def test_upload_success(self, manager, tmp_path):
        """Successful upload should return (True, False, 'uploaded')."""
        file_path = tmp_path / "test.pdf"
        file_path.write_text("pdf content")

        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 201

        with patch.object(manager, "get_workspace_documents", return_value=self.MOCK_DOCS_EXISTS):
            with patch("requests.post", return_value=mock_response) as mock_post:
                success, skipped, msg = manager.upload_file_to_workspace(file_path, "MyWorkspace")

        assert success is True
        assert skipped is False
        assert msg == "uploaded"

        # Verify the API call - url is first positional arg
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://test.infohub.example.com/api/v1/document/upload/myworkspace"
        assert "file" in call_args.kwargs["files"]
        assert call_args.kwargs["timeout"] == 300

    def test_upload_skipped_when_exists(self, manager, tmp_path):
        """When file already exists, should skip without API call."""
        file_path = tmp_path / "existing.pdf"
        file_path.write_text("content")

        mock_docs = {"base_names": {"existing"}, "doc_names": {"existing": "existing.json"}, "raw_docs": [], "exists": True}

        with patch.object(manager, "get_workspace_documents", return_value=mock_docs):
            with patch("requests.post") as mock_post:
                success, skipped, msg = manager.upload_file_to_workspace(file_path, "WS")

        assert success is False
        assert skipped is True
        assert msg == "already exists"
        mock_post.assert_not_called()

    def test_upload_skipped_when_exists_with_uuid(self, manager, tmp_path):
        """When file exists with UUID-style docpath, should skip."""
        file_path = tmp_path / "existing.pdf"
        file_path.write_text("content")

        # base_names contain UUID: "existing.abc123" instead of plain "existing"
        mock_docs = {
            "base_names": {"existing.abc123", "other.doc"},
            "doc_names": {"existing.abc123": "existing.abc123.json", "other.doc": "other.doc.json"},
            "raw_docs": [],
            "exists": True,
        }

        with patch.object(manager, "get_workspace_documents", return_value=mock_docs):
            with patch("requests.post") as mock_post:
                success, skipped, msg = manager.upload_file_to_workspace(file_path, "WS")

        assert success is False
        assert skipped is True
        assert msg == "already exists"
        mock_post.assert_not_called()

    def test_upload_skipped_when_in_documents_area_only(self, manager, tmp_path):
        """Empty listing but file already in documents area → skip, no upload call."""
        file_path = tmp_path / "Blawd-Profile-2026-(2).pdf"
        file_path.write_text("content")

        mock_docs = {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True}

        with patch.object(manager, "get_workspace_documents", return_value=mock_docs):
            with patch.object(
                manager,
                "_get_documents_area_docpaths",
                return_value=["blawd/Blawd-Profile-2026-(2).pdf-402c5c3a-9f1c.json"],
            ):
                with patch("requests.post") as mock_post:
                    success, skipped, msg = manager.upload_file_to_workspace(file_path, "blawd")

        assert success is False
        assert skipped is True
        assert msg == "already exists"
        mock_post.assert_not_called()

    def test_upload_skipped_with_hyphen_separator(self, manager, tmp_path):
        """base_names with hyphen separator (existing-abc123) → skip."""
        file_path = tmp_path / "existing.pdf"
        file_path.write_text("content")

        mock_docs = {
            "base_names": {"existing-abc123"},
            "doc_names": {"existing-abc123": "existing-abc123.json"},
            "raw_docs": [],
            "exists": True,
        }

        with patch.object(manager, "get_workspace_documents", return_value=mock_docs):
            with patch("requests.post") as mock_post:
                success, skipped, msg = manager.upload_file_to_workspace(file_path, "WS")

        assert success is False
        assert skipped is True
        assert msg == "already exists"
        mock_post.assert_not_called()

    def test_upload_api_error(self, manager, tmp_path):
        """API error should return failure."""
        file_path = tmp_path / "failing.pdf"
        file_path.write_text("content")

        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500
        mock_response.text = "Server Error"

        with patch.object(manager, "get_workspace_documents", return_value=self.MOCK_DOCS_EXISTS):
            with patch("requests.post", return_value=mock_response):
                success, skipped, msg = manager.upload_file_to_workspace(file_path, "WS")

        assert success is False
        assert skipped is False
        assert "failed" in msg

    def test_upload_file_not_found(self, manager):
        """Missing file should be handled gracefully."""
        file_path = Path("/nonexistent/file.pdf")

        with patch.object(manager, "get_workspace_documents", return_value=self.MOCK_DOCS_EXISTS):
            success, skipped, msg = manager.upload_file_to_workspace(file_path, "WS")

        assert success is False
        assert skipped is False

    def test_upload_creates_workspace_if_missing(self, manager, tmp_path):
        """Should create workspace before upload when workspace doesn't exist."""
        file_path = tmp_path / "new.pdf"
        file_path.write_text("content")

        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 201

        docs_not_found = {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": False}
        docs_found = {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True}

        with patch.object(manager, "get_workspace_documents", side_effect=[docs_not_found, docs_found]) as mock_get:
            with patch.object(manager, "create_workspace", return_value=True) as mock_create:
                with patch("requests.post", return_value=mock_response):
                    success, skipped, msg = manager.upload_file_to_workspace(file_path, "NewWorkspace")

        mock_create.assert_called_once_with("NewWorkspace")
        assert mock_get.call_count == 2  # before and after creation
        assert success is True
        assert msg == "uploaded"


# ---------------------------------------------------------------------------
# sort_files
# ---------------------------------------------------------------------------


class TestSortFiles:
    def test_no_root_configured(self, manager):
        manager.watched_root = ""
        result = manager.sort_files()
        assert result["status"] == "error"
        assert "not configured" in result["message"]

    def test_sort_uploads_and_describes(self, manager, watched_dir):
        """sort_files should upload files and generate image descriptions."""
        manager.watched_root = str(watched_dir)

        # Count how many times upload is called
        upload_call_count = [0]

        def mock_upload(file_path, workspace_name, skip_if_exists=True):
            upload_call_count[0] += 1
            return (True, False, "uploaded")

        with patch.object(manager, "upload_file_to_workspace", side_effect=mock_upload):
            with patch.object(manager, "_generate_image_description", return_value="desc"):
                with patch.object(manager, "_update_embeddings", return_value=True):
                    with patch.object(manager, "image_description_active", True):
                        with patch.object(manager, "get_workspace_documents", return_value={
                            "base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True
                        }):
                            result = manager.sort_files()

        assert result["status"] == "success"
        assert result["uploaded"] == 5
        assert result["images_processed"] == 1  # image1.jpg only
        # 5 non-excluded files across 3 workspaces
        assert upload_call_count[0] == 5

    def test_sort_generates_image_description(self, manager, watched_dir):
        """sort_files should create .image_description.txt files for images."""
        manager.watched_root = str(watched_dir)

        desc_text = "A photo of mountains"

        with patch.object(manager, "upload_file_to_workspace", return_value=(True, False, "uploaded")):
            with patch.object(manager, "_generate_image_description", return_value=desc_text):
                with patch.object(manager, "_update_embeddings", return_value=True):
                    with patch.object(manager, "image_description_active", True):
                        with patch.object(manager, "get_workspace_documents", return_value={
                            "base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True
                        }):
                            result = manager.sort_files()

        ws_a = watched_dir / "Infohub_Tech" / "WorkspaceA"
        desc_file = ws_a / "image1.jpg.image_description.txt"
        assert desc_file.exists()
        assert desc_file.read_text() == desc_text

    def test_sort_skips_existing_description(self, manager, watched_dir):
        """If .image_description.txt exists, skip description generation."""
        ws_a = watched_dir / "Infohub_Tech" / "WorkspaceA"
        existing_desc = ws_a / "image1.jpg.image_description.txt"
        existing_desc.write_text("existing desc")

        with patch.object(manager, "upload_file_to_workspace", return_value=(True, False, "uploaded")):
            with patch.object(manager, "_generate_image_description") as mock_gen:
                with patch.object(manager, "_update_embeddings", return_value=True):
                    with patch.object(manager, "image_description_active", True):
                        with patch.object(manager, "get_workspace_documents", return_value={
                            "base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True
                        }):
                            result = manager.sort_files()

        mock_gen.assert_not_called()

    def test_sort_error_handling(self, manager):
        """An exception during sort_files should return error status."""
        manager.watched_root = "/nonexistent"
        result = manager.sort_files()
        assert result["status"] == "error"

    def test_sort_creates_workspace_for_empty_folder(self, manager, watched_dir):
        """An empty local workspace folder should still create the remote workspace."""
        (watched_dir / "Infohub_Tech" / "EmptyWS").mkdir()
        manager.watched_root = str(watched_dir)

        def mock_get_docs(ws_name):
            if ws_name == "EmptyWS":
                return {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": False}
            return {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True}

        with patch.object(manager, "get_workspace_documents", side_effect=mock_get_docs):
            with patch.object(manager, "create_workspace", return_value=True) as mock_create:
                with patch.object(manager, "upload_file_to_workspace", return_value=(True, False, "uploaded")):
                    with patch.object(manager, "_update_embeddings", return_value=True):
                        with patch.object(manager, "image_description_active", False):
                            result = manager.sort_files()

        assert result["status"] == "success"
        mock_create.assert_called_once_with("EmptyWS")

    def test_sort_does_not_recreate_existing_workspace(self, manager, watched_dir):
        """Workspaces that already exist remotely should not be recreated."""
        manager.watched_root = str(watched_dir)

        with patch.object(manager, "get_workspace_documents", return_value={
            "base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True
        }):
            with patch.object(manager, "create_workspace") as mock_create:
                with patch.object(manager, "upload_file_to_workspace", return_value=(True, False, "uploaded")):
                    with patch.object(manager, "_update_embeddings", return_value=True):
                        with patch.object(manager, "image_description_active", False):
                            result = manager.sort_files()

        assert result["status"] == "success"
        mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# full_upload_and_clean
# ---------------------------------------------------------------------------


class TestFullUploadAndClean:
    def test_no_root_configured(self, manager):
        manager.watched_root = ""
        result = manager.full_upload_and_clean()
        assert result["status"] == "error"
        assert "not configured" in result["message"]

    def test_upload_and_delete_orphans(self, manager, watched_dir):
        """full_upload_and_clean should upload local files and delete orphaned docs."""
        manager.watched_root = str(watched_dir)

        # Simulate: WorkspaceA has doc1.pdf locally, but remote has doc1.pdf, doc_orphan.json
        # So doc_orphan should be deleted
        def mock_get_docs(ws_name):
            if ws_name == "WorkspaceA":
                return {
                    "base_names": {"doc1", "doc_orphan"},
                    "doc_names": {"doc1": "doc1.uuid.json", "doc_orphan": "doc_orphan.abc.json"},
                    "raw_docs": [],
                    "exists": True,
                }
            return {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True}

        delete_results = {}

        def mock_delete(doc_names):
            delete_results["called_with"] = doc_names
            return (True, len(doc_names), [])

        def mock_upload(fp, ws, skip=True):
            return (True, False, "uploaded")

        with patch.object(manager, "get_workspace_documents", side_effect=mock_get_docs):
            with patch.object(manager, "delete_documents", side_effect=mock_delete):
                with patch.object(manager, "upload_file_to_workspace", side_effect=mock_upload):
                    with patch.object(manager, "_update_embeddings", return_value=True):
                        result = manager.full_upload_and_clean()

        assert result["status"] == "success"
        assert result["deleted"] == 1
        assert "doc_orphan.abc.json" in delete_results.get("called_with", [])

    def test_no_orphans(self, manager, watched_dir):
        """When local and remote are in sync, nothing should be deleted."""
        manager.watched_root = str(watched_dir)

        def mock_get_docs(ws_name):
            if ws_name == "WorkspaceA":
                return {
                    "base_names": {"doc1", "doc2"},
                    "doc_names": {"doc1": "doc1.uuid.json", "doc2": "doc2.uuid.json"},
                    "raw_docs": [],
                    "exists": True,
                }
            return {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True}

        with patch.object(manager, "get_workspace_documents", side_effect=mock_get_docs):
            with patch.object(manager, "delete_documents") as mock_delete:
                with patch.object(manager, "upload_file_to_workspace", return_value=(True, False, "uploaded")):
                    with patch.object(manager, "_update_embeddings", return_value=True):
                        result = manager.full_upload_and_clean()

        # doc1 and doc2 exist locally, so no orphans - delete_documents not called at all
        mock_delete.assert_not_called()
        assert result["deleted"] == 0

    def test_full_upload_creates_workspace_for_empty_folder(self, manager, watched_dir):
        """An empty local workspace folder should still create the remote workspace."""
        (watched_dir / "Infohub_Tech" / "EmptyWS").mkdir()
        manager.watched_root = str(watched_dir)

        def mock_get_docs(ws_name):
            if ws_name == "EmptyWS":
                return {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": False}
            return {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": True}

        with patch.object(manager, "get_workspace_documents", side_effect=mock_get_docs):
            with patch.object(manager, "create_workspace", return_value=True) as mock_create:
                with patch.object(manager, "upload_file_to_workspace", return_value=(True, False, "uploaded")):
                    with patch.object(manager, "_update_embeddings", return_value=True):
                        result = manager.full_upload_and_clean()

        assert result["status"] == "success"
        mock_create.assert_called_once_with("EmptyWS")


# ---------------------------------------------------------------------------
# create_image_descriptions
# ---------------------------------------------------------------------------


class TestCreateImageDescriptions:
    def test_disabled_returns_warning(self, manager):
        manager.image_description_active = False
        result = manager.create_image_descriptions()
        assert result["status"] == "warning"
        assert "disabled" in result["message"]

    def test_no_root_configured(self, manager):
        manager.image_description_active = True
        manager.watched_root = ""
        result = manager.create_image_descriptions()
        assert result["status"] == "error"
        assert "not configured" in result["message"]

    def test_processes_new_images(self, manager, watched_dir):
        """Should generate descriptions for images without .image_description.txt."""
        manager.watched_root = str(watched_dir)

        ws_a = watched_dir / "Infohub_Tech" / "WorkspaceA"
        # Add another image that needs description
        (ws_a / "photo2.png").write_text("png data")

        desc_text = "Generated description"

        with patch.object(manager, "_generate_image_description", return_value=desc_text):
            result = manager.create_image_descriptions()

        assert result["status"] == "success"
        assert result["processed"] == 2  # image1.jpg + photo2.png
        assert result["skipped"] == 0

        # Verify description files were created
        assert (ws_a / "image1.jpg.image_description.txt").exists()
        assert (ws_a / "photo2.png.image_description.txt").exists()
        assert (ws_a / "image1.jpg.image_description.txt").read_text() == desc_text

    def test_skips_images_with_existing_descriptions(self, manager, watched_dir):
        """Images that already have .image_description.txt should be skipped."""
        manager.watched_root = str(watched_dir)

        ws_a = watched_dir / "Infohub_Tech" / "WorkspaceA"
        existing = ws_a / "image1.jpg.image_description.txt"
        existing.write_text("existing desc")

        with patch.object(manager, "_generate_image_description") as mock_gen:
            result = manager.create_image_descriptions()

        assert result["status"] == "success"
        assert result["processed"] == 0
        assert result["skipped"] == 1
        mock_gen.assert_not_called()

    def test_partial_errors_tracked(self, manager, watched_dir):
        """When some images fail, errors should be reported."""
        manager.watched_root = str(watched_dir)

        ws_a = watched_dir / "Infohub_Tech" / "WorkspaceA"

        def mock_generate(img_path):
            if "image1" in img_path.name:
                raise RuntimeError("Ollama error")
            return "successful desc"

        with patch.object(manager, "_generate_image_description", side_effect=mock_generate):
            result = manager.create_image_descriptions()

        assert result["status"] == "error"
        assert result["processed"] == 0  # image1 failed
        assert len(result.get("errors", [])) > 0


# ---------------------------------------------------------------------------
# _generate_image_description
# ---------------------------------------------------------------------------


class TestGenerateImageDescription:
    def test_successful_generation(self, manager, tmp_path):
        """Should send image as base64 to Ollama and return description."""
        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"fake image bytes")

        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "A beautiful mountain landscape with snow"}
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            description = manager._generate_image_description(img_path)

        assert description == "A beautiful mountain landscape with snow"

        # Verify the API call - url is first positional arg
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:11434/api/chat"
        assert call_args.kwargs["json"]["model"] == "llava:latest"
        assert call_args.kwargs["json"]["stream"] is False
        assert "images" in call_args.kwargs["json"]["messages"][0]
        assert call_args.kwargs["timeout"] == 120

    def test_empty_description_raises_error(self, manager, tmp_path):
        """Empty description from Ollama should raise RuntimeError."""
        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"fake image bytes")

        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": ""}}

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="empty description"):
                manager._generate_image_description(img_path)

    def test_network_error(self, manager, tmp_path):
        """Network error should propagate."""
        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"fake image bytes")

        with patch("requests.post", side_effect=requests.ConnectionError("Timeout")):
            with pytest.raises(requests.ConnectionError):
                manager._generate_image_description(img_path)


# ---------------------------------------------------------------------------
# is_workspace_accessible / get_accessible_workspace_names
# ---------------------------------------------------------------------------


class TestWorkspaceAccess:
    def test_accessible_when_api_returns_workspace(self, real_access_manager):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "workspace": [{"slug": "my-ws", "name": "My WS"}]
        }

        with patch("requests.get", return_value=mock_response):
            assert real_access_manager.is_workspace_accessible("My WS") is True

    def test_not_accessible_when_404(self, real_access_manager):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 404

        with patch("requests.get", return_value=mock_response):
            assert real_access_manager.is_workspace_accessible("NoAccess") is False

    def test_not_accessible_on_network_error(self, real_access_manager):
        with patch("requests.get", side_effect=requests.ConnectionError("offline")):
            assert real_access_manager.is_workspace_accessible("AnyWS") is False

    def test_get_accessible_filters_unaccessible(self, real_access_manager):
        # Only "OK" is accessible; "Nope" returns 404
        ok_response = MagicMock(spec=requests.Response)
        ok_response.status_code = 200
        ok_response.json.return_value = {"workspace": [{"slug": "ok", "name": "OK"}]}

        nope_response = MagicMock(spec=requests.Response)
        nope_response.status_code = 404

        with patch("requests.get", side_effect=[nope_response, ok_response]):
            result = real_access_manager.get_accessible_workspace_names(["Nope", "OK"])

        assert result == {"OK"}

    def test_get_accessible_empty_when_none_accessible(self, real_access_manager):
        with patch.object(real_access_manager, "is_workspace_accessible", return_value=False):
            result = real_access_manager.get_accessible_workspace_names(["A", "B", "C"])

        assert result == set()


# ---------------------------------------------------------------------------
# login / allowed workspaces por usuario
# ---------------------------------------------------------------------------


class TestUserWorkspaceFilter:
    def test_no_login_means_no_user_filter(self, manager):
        manager.allowed_workspaces = None
        result = manager.get_accessible_workspace_names(["WorkspaceA", "TeamSpace"])
        assert result == {"WorkspaceA", "TeamSpace"}

    def test_filters_by_allowed_slugs(self, manager):
        manager.allowed_workspaces = {"workspacea": "WorkspaceA"}
        result = manager.get_accessible_workspace_names(["WorkspaceA", "TeamSpace"])
        assert result == {"WorkspaceA"}

    def test_slug_mapping_applies_before_filter(self, manager):
        manager.allowed_workspaces = {"team-space": "Team Space"}
        result = manager.get_accessible_workspace_names(["Team_Space"])
        assert result == {"Team_Space"}

    def test_empty_api_key_skips_v1_check_but_keeps_user_filter(self, manager):
        """Sin API key el chequeo /v1 no puede aportar; manda el filtro de usuario."""
        manager.api_key = ""
        manager.allowed_workspaces = {"workspacea": "WorkspaceA"}
        with patch("requests.get", side_effect=AssertionError("no debe llamar /v1")):
            result = manager.get_accessible_workspace_names(["WorkspaceA", "TeamSpace"])
        assert result == {"WorkspaceA"}


class TestLogin:
    def _mock_response(self, status_code=200, payload=None):
        response = MagicMock(spec=requests.Response)
        response.status_code = status_code
        response.json.return_value = payload or {}
        return response

    def test_login_success_stores_token_and_workspaces(self, manager):
        post_response = self._mock_response(payload={
            "valid": True,
            "token": "jwt-token",
            "user": {"id": 1, "username": "jose", "role": "default"},
        })
        get_response = self._mock_response(payload={
            "workspaces": [{"slug": "workspacea", "name": "WorkspaceA"}],
        })

        with patch("requests.post", return_value=post_response), \
             patch("requests.get", return_value=get_response) as mock_get:
            ok, err = manager.login("jose", "secret")

        assert (ok, err) == (True, None)
        assert manager.session_token == "jwt-token"
        assert manager.allowed_workspaces == {"workspacea": "WorkspaceA"}
        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer jwt-token"

    def test_login_success_falls_back_to_slug_when_name_missing(self, manager):
        post_response = self._mock_response(payload={"valid": True, "token": "jwt"})
        get_response = self._mock_response(payload={
            "workspaces": [{"slug": "solo-slug"}, {}],
        })

        with patch("requests.post", return_value=post_response), \
             patch("requests.get", return_value=get_response):
            ok, _ = manager.login("jose", "secret")

        assert manager.allowed_workspaces == {"solo-slug": "solo-slug"}

    def test_login_invalid_credentials(self, manager):
        post_response = self._mock_response(payload={
            "valid": False,
            "message": "[001] Invalid login credentials.",
        })

        with patch("requests.post", return_value=post_response):
            ok, err = manager.login("jose", "wrong")

        assert ok is False
        assert "[001]" in err
        assert manager.session_token == ""
        assert manager.allowed_workspaces is None

    def test_login_fails_closed_when_workspaces_unavailable(self, manager):
        post_response = self._mock_response(payload={"valid": True, "token": "jwt"})
        get_response = self._mock_response(status_code=500)

        with patch("requests.post", return_value=post_response), \
             patch("requests.get", return_value=get_response):
            ok, err = manager.login("jose", "secret")

        assert ok is False
        assert "workspaces" in err
        assert manager.session_token == ""
        assert manager.allowed_workspaces is None

    def test_login_connection_error(self, manager):
        with patch("requests.post", side_effect=requests.ConnectionError("offline")):
            ok, err = manager.login("jose", "secret")

        assert ok is False
        assert err is not None
        assert manager.session_token == ""
