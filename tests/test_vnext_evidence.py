from benchbase.evidence.store import artifact_root, write_observation_manifest


def test_observation_manifest_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("benchbase.evidence.store.DATA_DIR", tmp_path)
    rel, digest = write_observation_manifest(1, "item-a", {"raw": "x"})
    assert digest
    assert (artifact_root() / rel).is_file()