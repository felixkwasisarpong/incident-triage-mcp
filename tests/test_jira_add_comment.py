from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from incident_triage_mcp.adapters.jira_cloud import JiraCloudProvider
from incident_triage_mcp.adapters.jira_mock import JiraMockProvider
from incident_triage_mcp.adapters.servicenow import ServiceNowProvider


class TestJiraCloudAddComment(unittest.TestCase):
    def _provider(self) -> JiraCloudProvider:
        with patch.dict(
            "os.environ",
            {
                "JIRA_BASE_URL": "https://example.atlassian.net",
                "JIRA_EMAIL": "test@example.com",
                "JIRA_API_TOKEN": "token123",
            },
        ):
            return JiraCloudProvider()

    def test_add_comment_posts_to_correct_url(self) -> None:
        provider = self._provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "10001"}

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = provider.add_comment("INC-42", "## Update\n- Fixed the issue")

        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "INC-42/comment" in call_url

        body_arg = mock_post.call_args[1]["json"]
        assert "body" in body_arg
        assert body_arg["body"]["type"] == "doc"

    def test_add_comment_returns_correct_shape(self) -> None:
        provider = self._provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "10001"}

        with patch("requests.post", return_value=mock_response):
            result = provider.add_comment("INC-42", "some comment")

        assert result["added"] is True
        assert result["issue_key"] == "INC-42"
        assert result["comment_id"] == "10001"


class TestJiraMockAddComment(unittest.TestCase):
    def test_add_comment_returns_correct_shape(self) -> None:
        provider = JiraMockProvider()
        result = provider.add_comment("INC-99", "test body")
        assert result["added"] is True
        assert result["issue_key"] == "INC-99"
        assert result["comment_id"] is not None


class TestServiceNowAddComment(unittest.TestCase):
    def _provider(self) -> ServiceNowProvider:
        with patch.dict(
            "os.environ",
            {
                "SERVICENOW_BASE_URL": "https://example.service-now.com",
                "SERVICENOW_USERNAME": "admin",
                "SERVICENOW_PASSWORD": "pass",
            },
        ):
            return ServiceNowProvider()

    def test_add_comment_patches_work_notes(self) -> None:
        provider = self._provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {}

        with patch("requests.patch", return_value=mock_response) as mock_patch:
            result = provider.add_comment("sys123", "some update")

        mock_patch.assert_called_once()
        body_arg = mock_patch.call_args[1]["json"]
        assert "work_notes" in body_arg
        assert body_arg["work_notes"] == "some update"

    def test_add_comment_returns_correct_shape(self) -> None:
        provider = self._provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {}

        with patch("requests.patch", return_value=mock_response):
            result = provider.add_comment("sys123", "update text")

        assert result["added"] is True
        assert result["issue_key"] == "sys123"
