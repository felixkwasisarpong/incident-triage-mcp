from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from incident_triage_mcp.adapters.jira_cloud import JiraCloudProvider
from incident_triage_mcp.adapters.jira_mock import JiraMockProvider
from incident_triage_mcp.adapters.servicenow import ServiceNowProvider


class TestJiraCloudTransition(unittest.TestCase):
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

    def test_transition_fetches_then_posts(self) -> None:
        provider = self._provider()
        get_response = MagicMock()
        get_response.json.return_value = {
            "transitions": [
                {"id": "11", "name": "To Do"},
                {"id": "21", "name": "In Progress"},
                {"id": "31", "name": "Done"},
            ]
        }
        post_response = MagicMock()
        post_response.json.return_value = {}

        with (
            patch("requests.get", return_value=get_response),
            patch("requests.post", return_value=post_response) as mock_post,
        ):
            result = provider.transition_issue("INC-42", "In Progress")

        mock_post.assert_called_once()
        body_arg = mock_post.call_args[1]["json"]
        assert body_arg["transition"]["id"] == "21"
        assert result["transitioned"] is True
        assert result["issue_key"] == "INC-42"
        assert result["transition"] == "In Progress"

    def test_transition_case_insensitive(self) -> None:
        provider = self._provider()
        get_response = MagicMock()
        get_response.json.return_value = {"transitions": [{"id": "31", "name": "Done"}]}
        post_response = MagicMock()

        with (
            patch("requests.get", return_value=get_response),
            patch("requests.post", return_value=post_response),
        ):
            result = provider.transition_issue("INC-42", "done")

        assert result["transitioned"] is True

    def test_transition_unknown_name_raises(self) -> None:
        provider = self._provider()
        get_response = MagicMock()
        get_response.json.return_value = {"transitions": [{"id": "11", "name": "To Do"}]}

        with patch("requests.get", return_value=get_response):
            with self.assertRaises(RuntimeError) as ctx:
                provider.transition_issue("INC-42", "Nonexistent")

        assert "not found" in str(ctx.exception)


class TestJiraMockTransition(unittest.TestCase):
    def test_transition_returns_correct_shape(self) -> None:
        provider = JiraMockProvider()
        result = provider.transition_issue("INC-99", "Resolved")
        assert result["transitioned"] is True
        assert result["issue_key"] == "INC-99"
        assert result["transition"] == "Resolved"


class TestServiceNowTransition(unittest.TestCase):
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

    def test_transition_maps_resolved_to_state_6(self) -> None:
        provider = self._provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {}

        with patch("requests.patch", return_value=mock_response) as mock_patch:
            result = provider.transition_issue("sys123", "Resolved")

        body_arg = mock_patch.call_args[1]["json"]
        assert body_arg["state"] == "6"
        assert result["transitioned"] is True

    def test_transition_maps_in_progress_to_state_2(self) -> None:
        provider = self._provider()
        mock_response = MagicMock()

        with patch("requests.patch", return_value=mock_response) as mock_patch:
            provider.transition_issue("sys123", "In Progress")

        body_arg = mock_patch.call_args[1]["json"]
        assert body_arg["state"] == "2"

    def test_transition_unknown_name_raises(self) -> None:
        provider = self._provider()
        with self.assertRaises(RuntimeError) as ctx:
            provider.transition_issue("sys123", "Unknown State")
        assert "Unknown transition" in str(ctx.exception)
