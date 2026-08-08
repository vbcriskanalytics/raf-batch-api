"""RAF Batch API client (VERIFIED contract, 2026-06-01).

The batch API is a 3-step job, NOT a single JSON POST:

  1. submit() : POST /raf-batch-api/<scoreType>  (multipart: risk_model,
     risk_factor, file=CSV)                              -> raf_batch_id
  2. check_status(id) : GET /raf-batch-api/check-status/<id>
     poll until status == "Completed"                    -> download_url
  3. get_download_url(id) : GET /raf-batch-api/download/<id>
     -> a short-lived (~120s) signed AWS S3 URL to a .zip of .xlsx results

Auth on every batch host call: header ``ApiKey: <key>`` plus an empty
``X-CSRF-TOKEN:`` header. (NOT Authorization: Bearer.)

Verified live against https://www.vbcriskanalytics.com/raf-batch-api with a
real key. Use synthetic data only — no PHI.
"""

import os
import time

import requests

# --- API contract (VERIFIED) --------------------------------------------------
BATCH_BASE_URL = "https://www.vbcriskanalytics.com/raf-batch-api"

# Submit endpoints by score type, with the matching sample CSV the docs link to.
SCORE_TYPES = {
    "pre-prospect":  "getPreProspectScore",   # Flag: Last_Year | Current_Year
    "post-prospect": "getPostProspectScore",  # Flag: New | Billed | Missed
    "post-concurrent": "getPostCncntScore",   # Flag: No_Changes | Deletion | Addition
}
SAMPLE_CSV_URLS = {
    "pre-prospect":  "https://www.vbcriskanalytics.com/input_pre_prospective.csv",
    "post-prospect": "https://www.vbcriskanalytics.com/input_post_prospective.csv",
    "post-concurrent": "https://www.vbcriskanalytics.com/input_post_concurrent.csv",
}

SIGNUP_URL = "https://www.rafscorecalculator.com/raf-score-batch"
API_KEY_ENV_VAR = "RAF_BATCH_API_KEY"


class RafBatchClientError(Exception):
    """Raised when a Batch API call fails or the key is missing."""


class RafBatchClient:
    """Thin client for the 3-step RAF Batch API."""

    def __init__(self, api_key=None, base_url=BATCH_BASE_URL, timeout=120):
        self.api_key = api_key or os.environ.get(API_KEY_ENV_VAR)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise RafBatchClientError(
                f"Missing Batch API key. Set {API_KEY_ENV_VAR}.\n"
                f"Get a Batch API key here: {SIGNUP_URL}"
            )

    def _headers(self):
        # VERIFIED: custom ApiKey header + empty X-CSRF-TOKEN.
        return {"ApiKey": self.api_key, "X-CSRF-TOKEN": "", "accept": "*/*"}

    def submit(self, csv_path, risk_model, risk_factor, score_type="pre-prospect"):
        """Step 1 — upload a CSV for bulk scoring. Returns the parsed JSON
        (contains ``raf_batch_id`` and ``status: Queued``)."""
        endpoint = SCORE_TYPES.get(score_type)
        if not endpoint:
            raise RafBatchClientError(
                f"Unknown score_type {score_type!r}; use one of {list(SCORE_TYPES)}"
            )
        url = f"{self.base_url}/{endpoint}"
        with open(csv_path, "rb") as fh:
            files = {"file": (os.path.basename(csv_path), fh, "text/csv")}
            data = {"risk_model": risk_model, "risk_factor": risk_factor}
            try:
                resp = requests.post(
                    url, headers=self._headers(), data=data, files=files,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise RafBatchClientError(f"Submit failed: {exc}") from exc
        return self._json(resp)

    def check_status(self, raf_batch_id):
        """Step 2 — poll once. Returns parsed JSON with ``status`` in
        {Queued, Running, Completed} and (when done) a ``download_url``."""
        url = f"{self.base_url}/check-status/{raf_batch_id}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise RafBatchClientError(f"check-status failed: {exc}") from exc
        return self._json(resp)

    def wait_until_complete(self, raf_batch_id, interval=4, max_polls=30):
        """Poll check-status until status == 'Completed' (or give up)."""
        last = None
        for _ in range(max_polls):
            last = self.check_status(raf_batch_id)
            if str(last.get("status", "")).lower() == "completed":
                return last
            time.sleep(interval)
        raise RafBatchClientError(f"Job {raf_batch_id} did not complete; last={last}")

    def get_download_url(self, raf_batch_id):
        """Step 3 — get the pre-signed S3 URL (expires ~120s)."""
        url = f"{self.base_url}/download/{raf_batch_id}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise RafBatchClientError(f"download failed: {exc}") from exc
        return self._json(resp)

    @staticmethod
    def fetch_result(signed_url, out_path):
        """Step 4 — download the .zip from the signed S3 URL (NO ApiKey header)."""
        try:
            resp = requests.get(signed_url, timeout=120)
        except requests.RequestException as exc:
            raise RafBatchClientError(f"S3 fetch failed: {exc}") from exc
        if not resp.ok:
            raise RafBatchClientError(f"S3 returned HTTP {resp.status_code}")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(resp.content)
        return out_path

    @staticmethod
    def _json(resp):
        if resp.status_code == 401:
            raise RafBatchClientError(f"Invalid API Key (401): {resp.text}")
        if not resp.ok:
            raise RafBatchClientError(f"HTTP {resp.status_code}: {resp.text}")
        try:
            return resp.json()
        except ValueError as exc:
            raise RafBatchClientError(f"Non-JSON response: {resp.text}") from exc
