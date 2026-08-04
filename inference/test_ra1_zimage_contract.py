import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


def test_explicit_lora_keeps_ra1_final_prompt(monkeypatch):
    monkeypatch.setattr(server, "lora_engine", object())
    monkeypatch.setattr(server, "ENABLE_NVFP4", False)
    prompt = "90s retro sci-fi, a chrome robot in Tokyo"
    req = server.ZImageRequest(
        prompt=prompt,
        lora_id="retro_scifi_90s",
        auto_lora=False,
        prompt_is_final=True,
    )

    lora, final_prompt = server._resolve_lora(req)

    assert lora is not None
    assert lora.id == "retro_scifi_90s"
    assert final_prompt == prompt
