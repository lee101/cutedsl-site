from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _unit_values(text: str, key: str) -> set[str]:
    values: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(f"{key}="):
            values.update(line.split("=", 1)[1].split())
    return values


def test_cold_zimage_worker_starts_and_orders_native_fallback():
    override = (ROOT / "systemd" / "cutedsl-zimage-override.conf").read_text(
        encoding="utf-8"
    )

    assert "omniserve-native.service" in _unit_values(override, "Wants")
    assert "omniserve-native.service" in _unit_values(override, "After")
    assert "ZIMAGE_NATIVE_FALLBACK_URL=http://127.0.0.1:8791" in override
    assert "ZIMAGE_NATIVE_RESTART_GRACE_SECONDS=60" in override


def test_native_recovery_grace_leaves_room_inside_public_edge_timeout():
    override = (ROOT / "systemd" / "cutedsl-zimage-override.conf").read_text()
    environment = dict(value.split("=", 1) for value in _unit_values(override, "Environment"))
    for name in (
        "ZIMAGE_NATIVE_HEADROOM_GRACE_SECONDS",
        "ZIMAGE_NATIVE_GENERATION_FAILURE_GRACE_SECONDS",
        "ZIMAGE_NATIVE_RESTART_GRACE_SECONDS",
    ):
        # Cloudflare returns 524 at 120 seconds, even though the Go proxy allows 180.
        assert 0 < float(environment[name]) <= 60


def test_secondary_qwen_gateway_does_not_eagerly_reserve_shared_gpu():
    dropin = (ROOT / "systemd" / "omniserve-native-qwen-cutedsl.conf").read_text(
        encoding="utf-8"
    )

    assert "OMNISERVE_NATIVE_SD_EAGER_LOAD=0" in dropin


def test_unhealthy_image_overflow_uses_local_admission_only():
    dropin = (ROOT / "systemd" / "zz-oncall-image-overflow.conf").read_text()
    assert _unit_values(dropin, "Environment") == {
        "OMNISERVE_NATIVE_IMAGE_OVERFLOW_UPSTREAM="
    }
