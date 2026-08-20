"""
Canvas API client for AIML04 learner support system.
Owned by: Gentille Uwera
"""
import time
import requests
from app.config import settings

BASE_URL = settings.canvas_api_url.rstrip("/")
COURSE_ID = 829
TEST_STUDENT_ID = 27815
PER_PAGE = 100
MAX_RETRIES = 5

DEADLINE_MAP = {
    3320: "2026-06-28T23:59:00Z",
    3317: "2026-07-05T23:59:00Z",
    3313: "2026-07-05T23:59:00Z",
    3311: "2026-07-05T23:59:00Z",
    3309: "2026-07-12T23:59:00Z",
    3323: "2026-07-15T23:59:00Z",
    3314: "2026-07-19T23:59:00Z",
    3312: "2026-07-26T23:59:00Z",
    3321: "2026-08-02T23:59:00Z",
    3324: "2026-08-02T23:59:00Z",
    3310: "2026-08-09T23:59:00Z",
    3315: "2026-08-09T23:59:00Z",
    3319: "2026-08-09T23:59:00Z",
    3325: "2026-08-09T23:59:00Z",
    3308: "2026-08-16T23:59:00Z",
    3316: "2026-08-16T23:59:00Z",
    3318: "2026-08-16T23:59:00Z",
    3322: "2026-08-16T23:59:00Z",
    3326: "2026-08-16T23:59:00Z",
}


def get_roadmap_deadline(assignment_id: int) -> str | None:
    return DEADLINE_MAP.get(assignment_id)


class CanvasClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {settings.canvas_api_token}"
        })

    def get_paginated(self, path: str, params: dict | None = None):
        url = f"{BASE_URL}{path}"
        params = dict(params or {})
        params.setdefault("per_page", PER_PAGE)
        while url:
            response = self._get_with_retry(url, params)
            data = response.json()
            if isinstance(data, list):
                yield from data
            else:
                yield data
            url = response.links.get("next", {}).get("url")
            params = None

    def get(self, path: str, params: dict | None = None):
        return self._get_with_retry(f"{BASE_URL}{path}", params).json()

    def _get_with_retry(self, url: str, params: dict | None):
        for attempt in range(1, MAX_RETRIES + 1):
            r = self.session.get(url, params=params, timeout=30)
            if r.status_code == 403 and "rate limit" in r.text.lower():
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        raise RuntimeError(f"Exceeded retries fetching {url}")
