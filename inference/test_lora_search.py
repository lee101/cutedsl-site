from lora_fixtures import get_all_zimage_loras, get_lora_by_id
from lora_search import LoRASearchEngine


def test_catalog_contains_netwrck_zimage_adapters_only():
    loras = get_all_zimage_loras()

    assert len(loras) >= 51
    assert len({lora.id for lora in loras}) == len(loras)
    assert get_lora_by_id("retro_scifi_90s") is not None
    assert get_lora_by_id("vintage_travel_poster") is not None
    assert get_lora_by_id("zit_v6") is not None
    assert all("netwrckstatic.netwrck.com/static/loras/" in lora.url for lora in loras)


def test_keyword_selector_picks_specific_zimage_loras():
    engine = LoRASearchEngine()

    results = engine._search_keywords("90s retro cyberpunk city with neon signs", top_k=3)
    assert results[0].lora.id == "retro_scifi_90s"

    results = engine._search_keywords("a vintage travel poster of a cute moon cafe", top_k=3)
    assert results[0].lora.id == "vintage_travel_poster"

    results = engine._search_keywords("clean linework anime girl portrait", top_k=3)
    assert results[0].lora.id == "z_clean_linework_anime_girl"


def test_adult_loras_require_explicit_adult_prompt():
    engine = LoRASearchEngine()

    results = engine._search_keywords("realistic influencer fashion portrait", top_k=10)
    assert all(not result.lora.is_adult for result in results)

    results = engine._search_keywords("nsfw realistic adult portrait", top_k=3)
    assert any(result.lora.is_adult for result in results)
