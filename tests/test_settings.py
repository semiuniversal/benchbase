"""Settings YAML round-trip for Speed-index baseline."""

from __future__ import annotations

from benchbase.api.routes.settings import SettingsUpdate, settings_to_out
from benchbase.config import Settings


def test_work_clock_reference_defaults_unset():
    s = Settings()
    assert s.work_clock_reference_model is None
    out = settings_to_out(s)
    assert out.work_clock_reference_model is None


def test_work_clock_reference_round_trip():
    s = Settings(work_clock_reference_model="holo-3.1-35b-nothink")
    out = settings_to_out(s)
    assert out.work_clock_reference_model == "holo-3.1-35b-nothink"
    update = SettingsUpdate(work_clock_reference_model="")
    dumped = update.model_dump(exclude_unset=True)
    assert dumped["work_clock_reference_model"] == ""


def test_work_clock_reference_blank_means_none_in_out():
    s = Settings(work_clock_reference_model="")
    assert settings_to_out(s).work_clock_reference_model is None
