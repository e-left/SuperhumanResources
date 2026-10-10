"""Read a candidate's public GitHub profile through the GitHub API. No code is read."""

import collections
import os
import re

import httpx

API = "https://api.github.com"
_USER = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/?$")
_BARE = re.compile(r"^@?([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))$")
MAX_REPOS = 12


class GithubError(Exception):
    pass


def username(value: str) -> str:
    """'https://github.com/octocat', 'github.com/octocat', '@octocat' or 'octocat' -> 'octocat'."""
    value = value.strip()
    match = _USER.match(value) or _BARE.match(value)
    if not match:
        raise GithubError("use a GitHub profile link such as https://github.com/username")
    return match.group(1)


def profile_url(value: str) -> str:
    return f"https://github.com/{username(value)}"


def fetch_profile(value: str) -> dict:
    """Public facts about the account and its own repositories."""
    user = username(value)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "SuperhumanResources"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(base_url=API, headers=headers, timeout=10.0) as client:
            account = client.get(f"/users/{user}")
            if account.status_code == 404:
                raise GithubError(f"GitHub has no user called {user}")
            if account.status_code in (403, 429):
                raise GithubError("GitHub's rate limit was reached; try again later or set GITHUB_TOKEN")
            account.raise_for_status()
            repos = client.get(
                f"/users/{user}/repos", params={"sort": "pushed", "per_page": 30, "type": "owner"}
            )
            repos.raise_for_status()
    except httpx.HTTPError as exc:
        raise GithubError(f"could not read the GitHub profile ({type(exc).__name__})") from exc

    data = account.json()
    own = [r for r in repos.json() if not r.get("fork")]
    languages = collections.Counter(r["language"] for r in own if r.get("language"))
    return {
        "username": user,
        "name": data.get("name"),
        "bio": data.get("bio"),
        "company": data.get("company"),
        "location": data.get("location"),
        "member_since": (data.get("created_at") or "")[:4] or None,
        "public_repos": data.get("public_repos"),
        "followers": data.get("followers"),
        "languages": [name for name, _ in languages.most_common(6)],
        "repositories": [
            {
                "name": r.get("name"),
                "description": r.get("description"),
                "language": r.get("language"),
                "stars": r.get("stargazers_count"),
                "last_push": (r.get("pushed_at") or "")[:10] or None,
            }
            for r in own[:MAX_REPOS]
        ],
    }
