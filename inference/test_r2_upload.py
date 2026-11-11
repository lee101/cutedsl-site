import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import r2_upload  # noqa: E402


def test_project_storage_setting_overrides_unrelated_host_default(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "another-sites-bucket")
    monkeypatch.setenv("CUTEDSL_R2_BUCKET", "appstatic")

    assert r2_upload._project_env("CUTEDSL_R2_BUCKET", "R2_BUCKET", "fallback") == "appstatic"


def test_project_storage_setting_falls_back_to_generic_for_compatibility(monkeypatch):
    monkeypatch.delenv("CUTEDSL_R2_BUCKET", raising=False)
    monkeypatch.setenv("R2_BUCKET", "legacy-bucket")

    assert r2_upload._project_env("CUTEDSL_R2_BUCKET", "R2_BUCKET", "fallback") == "legacy-bucket"
