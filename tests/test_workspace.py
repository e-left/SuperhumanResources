from html.parser import HTMLParser

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


def test_applicants_page_has_mock_profiles_and_workspace_navigation():
    class ApplicantTableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows = []
            self.in_body = False
            self.in_cell = False

        def handle_starttag(self, tag, attrs):
            if tag == "tbody":
                self.in_body = True
            elif tag == "tr" and self.in_body:
                self.rows.append([])
            elif tag == "td" and self.in_body:
                self.in_cell = True

        def handle_endtag(self, tag):
            if tag == "tbody":
                self.in_body = False
            elif tag == "td":
                self.in_cell = False

        def handle_data(self, data):
            if self.in_cell:
                self.rows[-1].append(data)

    with TestClient(app) as client:
        workspace = client.get("/").text
        # Workspace nav order: Context Studio, Applicant's list, Candidates.
        assert workspace.index(">Context Studio</a") < workspace.index('href="/applicants"') < workspace.index('href="/candidates"')
        response = client.get("/applicants")
        assert response.status_code == 200
        assert 'href="/applicants" aria-current="page"' in response.text
        assert 'href="https://github.com/siskos-k"' in response.text
        assert 'href="https://www.linkedin.com/in/siskos-k/"' in response.text
        assert 'href="mailto:konstantinos.siscos@gmail.com"' in response.text
        assert "/static/context.js" not in response.text
        # The Interview column is added at runtime, so the table above stays as written.
        assert "/static/applicants.js" in response.text
        assert client.get("/static/applicants.js").status_code == 200
        table = ApplicantTableParser()
        table.feed(response.text)
        assert len(table.rows) == 12
        assert table.rows[0] == ["Konstantinos", "Siskos", "konstantinos.siscos@gmail.com", "siskos-k ↗", "linkedin.com/in/siskos-k ↗"]
        assert table.rows[1] == ["Fotios", "Alexandridis", "fotios.alexandridis@gmail.com", "e-left ↗", "linkedin.com/in/fotios-alexandridis-b925b4147 ↗"]
        assert 'href="https://github.com/e-left"' in response.text
        assert 'href="https://www.linkedin.com/in/fotios-alexandridis-b925b4147/"' in response.text
        for first, last, email, github, linkedin in table.rows[2:]:
            assert first and last
            assert email == f"{first.lower()}.{last.lower()}@example.com"
            assert f'href="mailto:{email}"' in response.text
            assert github.startswith("shr-demo-")
            assert linkedin == f"linkedin.com/in/{github}"
