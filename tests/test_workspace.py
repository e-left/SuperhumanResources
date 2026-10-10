from fastapi.testclient import TestClient

from src.api.app import app


def test_workspace_and_voice_interview_have_separate_entry_points():
    with TestClient(app) as client:
        workspace = client.get("/")
        assert workspace.status_code == 200
        assert "Context Studio" in workspace.text
        assert 'id="context-form"' in workspace.text
        interview = client.get("/?session=demo")
        assert interview.status_code == 200
        assert "Technical interview" in interview.text
        assert "SyncedAudioPlayer" in interview.text
        for path in ["/static/context.css", "/static/context.js", "/static/js/synced-audio-player.js"]:
            assert client.get(path).status_code == 200
        # The report is internal: served to recruiters, never from the candidate's static folder.
        assert client.get("/internal/report?session=demo").status_code == 200
        assert client.get("/static/report.html").status_code == 404
