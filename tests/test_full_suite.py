"""Full suite queue plan (Smoke → Standard chaining)."""

from __future__ import annotations

from benchbase.batch_scheduler import BatchJob


def test_batch_job_accepts_follow_up_field():
    job = BatchJob(
        batch_id="abc",
        model_id=1,
        model_name="m",
        run_ids=[1, 2],
        run_group_id="tier-abc",
        tier="smoke",
        follow_up_tier="standard",
    )
    assert job.follow_up_tier == "standard"