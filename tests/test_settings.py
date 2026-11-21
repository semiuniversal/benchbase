"""Settings YAML round-trip for Speed-index baseline."""

from __future__ import annotations

from benchbase.api.routes.settings import SettingsUpdate, merge_settings_update, settings_to_out
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


def test_batch_model_concurrency_defaults_to_three():
    s = Settings()
    assert s.batch_model_concurrency == 3
    assert settings_to_out(s).batch_model_concurrency == 3


def test_batch_model_concurrency_update_field():
    update = SettingsUpdate(batch_model_concurrency=4)
    assert update.model_dump(exclude_unset=True)["batch_model_concurrency"] == 4


def test_litellm_api_key_set_false_when_empty():
    assert settings_to_out(Settings(litellm_api_key="")).litellm_api_key_set is False


def test_merge_settings_blank_key_keeps_existing():
    current = Settings(litellm_api_key="secret")
    merged = merge_settings_update(current, SettingsUpdate(litellm_base_url="http://proxy"))
    assert merged.litellm_api_key == "secret"


def test_merge_settings_clear_api_key():
    current = Settings(litellm_api_key="secret")
    merged = merge_settings_update(current, SettingsUpdate(clear_litellm_api_key=True))
    assert merged.litellm_api_key == ""
