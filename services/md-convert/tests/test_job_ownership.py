import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.main import _enqueue_conversion_job, _fetch_owned_job_or_404


class FakeQueue:
    def __init__(self):
        self.call = None

    def enqueue(self, *args, **kwargs):
        self.call = (args, kwargs)
        return object()


class FakeJob:
    def __init__(self, owner_hash=None):
        self.meta = {}
        if owner_hash is not None:
            self.meta["owner_session_hash"] = owner_hash


class JobOwnershipTests(unittest.TestCase):
    def test_enqueue_stores_owner_hash_in_job_metadata(self):
        queue = FakeQueue()

        result = _enqueue_conversion_job(
            queue,
            job_id="job-1",
            job_dir="/data/jobs/job-1",
            options={"output_format": "docx"},
            owner_hash="owner-a",
        )

        self.assertIsNotNone(result)
        _, kwargs = queue.call
        self.assertEqual(kwargs["meta"], {"owner_session_hash": "owner-a"})
        self.assertEqual(kwargs["job_id"], "job-1")

    @patch("app.main.Job.fetch")
    def test_fetch_allows_matching_owner(self, fetch):
        job = FakeJob("owner-a")
        fetch.return_value = job

        result = _fetch_owned_job_or_404("job-1", "owner-a")

        self.assertIs(result, job)

    @patch("app.main.Job.fetch")
    def test_fetch_hides_foreign_and_legacy_jobs(self, fetch):
        for job in (FakeJob("owner-b"), FakeJob()):
            with self.subTest(meta=job.meta):
                fetch.return_value = job
                with self.assertRaises(HTTPException) as error:
                    _fetch_owned_job_or_404("job-1", "owner-a")
                self.assertEqual(error.exception.status_code, 404)
                self.assertEqual(error.exception.detail, "Job not found")


if __name__ == "__main__":
    unittest.main()
