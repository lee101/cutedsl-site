"""Z-Image LoRA fixtures — style metadata for auto-selection."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class LoRAMetadata:
    id: str
    name: str
    template: str
    url: str
    trigger_word: str = ""
    keywords: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)


def apply_lora_template(lora: LoRAMetadata, prompt: str) -> str:
    if not lora.template:
        return prompt
    return lora.template.replace("{prompt}", prompt)


def get_all_zimage_loras() -> list[LoRAMetadata]:
    return [
        LoRAMetadata(
            id="mecha_klein",
            name="Mecha Klein",
            trigger_word="mecha",
            template="mecha, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/new_mecha_klein4b.safetensors",
            keywords=["mecha", "fun", "anime realistic", "detailed cartoon high def"],
            negative_keywords=["organic", "natural", "human only", "realistic photo", "landscape", "painting", "fuzzy"],
        ),
        LoRAMetadata(
            id="anime_serenity",
            name="Anime Serenity Real Life",
            trigger_word="SERENITY style",
            template="SERENITY style, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/anime_blend_real_life%20SERENITY%20style.safetensors",
            keywords=["anime real life", "serenity style", "anime blend", "realistic anime", "semi-realistic", "anime portrait", "beautiful anime", "soft anime", "anime character", "anime girl", "anime boy", "serene anime"],
            negative_keywords=["cartoon", "chibi", "simple", "abstract", "pixel art"],
        ),
        LoRAMetadata(
            id="colorful_pop_art",
            name="Colorful Pop Art",
            trigger_word="colorful pop art",
            template="colorful pop art, intense colorful illustration, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/colorful_pop_art_intense_colorful_illustrations_turbo-lora-MSch_Psych_01.safetensors",
            keywords=["pop art", "colorful", "vibrant", "intense colors", "illustration", "bold colors", "graphic art", "warhol style", "comic pop", "retro pop", "bright illustration", "psychedelic", "vivid colors"],
            negative_keywords=["muted", "monochrome", "grayscale", "realistic", "photograph"],
        ),
        LoRAMetadata(
            id="cosplay_realistic",
            name="Cosplay Realistic",
            trigger_word="cosplay",
            template="cosplay, realistic, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/coser-V3-cosplay-realistic.safetensors",
            keywords=["cosplay", "costume", "cosplayer", "realistic cosplay", "anime cosplay", "costume design", "character costume", "professional cosplay", "detailed costume", "convention", "fantasy cosplay", "game cosplay"],
            negative_keywords=["cartoon", "drawing", "2d art", "illustration", "sketch"],
        ),
        LoRAMetadata(
            id="inkwash",
            name="Ink Wash Painting",
            trigger_word="ink wash",
            template="ink wash painting, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/inkwash_ink_painting_paints_lora.safetensors",
            keywords=["ink wash", "ink painting", "sumi-e", "chinese ink", "japanese ink", "brush stroke", "traditional ink", "watercolor ink", "asian art", "calligraphy style", "monochrome ink", "brush painting"],
            negative_keywords=["digital", "3d render", "photograph", "colorful", "neon"],
        ),
        LoRAMetadata(
            id="knight_stylism",
            name="Knight Stylism HD",
            trigger_word="knight stylism",
            template="knight stylism, intense detail, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/intense_detail_knight_stylism_highfi_cartoon_animesish.safetensors",
            keywords=["knight", "medieval", "armor", "fantasy knight", "warrior", "sword", "shield", "castle", "dragon slayer", "paladin", "intense detail", "epic fantasy", "battle armor", "crusader", "illustration"],
            negative_keywords=["modern", "sci-fi", "futuristic", "casual", "simple"],
        ),
        LoRAMetadata(
            id="water_cartoon",
            name="Water Cartoon Vintage",
            trigger_word="water cartoon",
            template="water cartoon, old charming hand drawn, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/myloraEX2_watercartoon_anime_old_charming_handrawn.safetensors",
            keywords=["vintage cartoon", "hand drawn", "classic animation", "old style", "watercolor cartoon", "charming", "nostalgic", "retro anime", "classic disney", "traditional animation", "storybook"],
            negative_keywords=["modern", "3d", "digital", "realistic", "photograph"],
        ),
        LoRAMetadata(
            id="needle_felting",
            name="Needle Felting Knit",
            trigger_word="needle felting",
            template="needle felting style, knitting style, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/needle_felting%20style_loonalone_knitting_style%20.safetensors",
            keywords=["needle felting", "felted", "wool", "knitted", "yarn", "crafted", "handmade", "plush", "soft toy", "cozy", "textile art", "fiber art", "cute felt"],
            negative_keywords=["digital", "realistic", "photograph", "hard edges", "metallic"],
        ),
        LoRAMetadata(
            id="neon_paint",
            name="Neon Paint Style",
            trigger_word="neon paint",
            template="neon paint style, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/NeonPaintStyle_Z-Image_512.safetensors",
            keywords=["neon", "glow", "fluorescent", "bright colors", "neon lights", "cyberpunk", "synthwave", "retrowave", "glowing", "vibrant", "electric colors", "blacklight", "uv reactive"],
            negative_keywords=["muted", "pastel", "grayscale", "natural", "realistic"],
        ),
        LoRAMetadata(
            id="mecha_zimage",
            name="Mecha Anime Detailed",
            trigger_word="mecha anime",
            template="mecha anime, detailed, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/new_mecha_zit_V2_anime_detailed_realistic_cartoon.safetensors",
            keywords=["mecha", "fun", "anime realistic", "detailed cartoon high def", "sci-fi anime", "power suit", "anime detailed realistic cartoon", "anime mech"],
            negative_keywords=["organic", "natural", "realistic photo", "simple", "minimalist"],
        ),
        LoRAMetadata(
            id="nsfw_master",
            name="NSFW Master",
            trigger_word="nsfw",
            template="nsfw, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/NSFW_master_ZIT_000008766.safetensors",
            keywords=["nsfw", "adult", "explicit", "mature content", "erotic", "sensual", "nude", "adult art"],
            negative_keywords=["sfw", "family friendly", "cute", "cartoon", "child"],
        ),
        LoRAMetadata(
            id="orcs",
            name="Orcs Fantasy",
            trigger_word="orc",
            template="orc, fantasy, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/orcs_zimage__orc_lora.safetensors",
            keywords=["orc", "ork", "green skin", "fantasy creature", "warcraft", "goblin", "troll", "barbaric", "tribal", "warrior orc", "fantasy beast", "monster", "brute"],
            negative_keywords=["human", "elf", "realistic", "modern", "cute"],
        ),
        LoRAMetadata(
            id="smartphone_realistic",
            name="Smartphone Realistic",
            trigger_word="smartphone photo",
            template="smartphone photo, realistic, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/smartphone_realistic_real_life_real_pic.safetensors",
            keywords=["smartphone", "mobile photo", "iphone", "android photo", "selfie", "casual photo", "candid", "real life", "authentic", "snapshot", "phone camera", "social media", "instagram style"],
            negative_keywords=["professional", "studio", "dslr", "artistic", "painting"],
        ),
        LoRAMetadata(
            id="pixel_art",
            name="Tartarus Pixel Art",
            trigger_word="pixel art",
            template="pixel art, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/TartarusPixel_pixelart_pixels.safetensors",
            keywords=["pixel art", "8bit", "16bit", "retro game", "sprite", "pixelated", "game asset", "indie game", "retro style", "classic game", "pixel graphics", "chiptune aesthetic"],
            negative_keywords=["smooth", "high resolution", "realistic", "photograph", "3d"],
        ),
        LoRAMetadata(
            id="tshirt_comic",
            name="T-Shirt Comic Design",
            trigger_word="tshirt design",
            template="tshirt design, comic style, centered, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/tshirt_comic_pixelart_centered_lora_v1.safetensors",
            keywords=["tshirt", "t-shirt design", "shirt graphic", "apparel design", "print design", "merchandise", "centered design", "logo design", "comic style", "graphic tee", "fashion graphic", "pixel comic art"],
            negative_keywords=["landscape", "background heavy", "realistic photo", "complex scene"],
        ),
        LoRAMetadata(
            id="flat_anime",
            name="Flat Anime Style",
            trigger_word="flat anime",
            template="flat anime style, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/UU_flat_anime_style_000000960.safetensors",
            keywords=["flat anime", "cel shaded", "clean lines", "simple anime", "vector style", "solid colors", "minimalist anime", "modern anime", "crisp anime", "flat color", "anime illustration"],
            negative_keywords=["realistic", "detailed shading", "3d", "photograph", "complex"],
        ),
        LoRAMetadata(
            id="watercolor_art",
            name="Watercolor Art",
            trigger_word="watercolor",
            template="watercolor art, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/watercolor-art-image-lora_v1_3000.safetensors",
            keywords=["watercolor", "aquarelle", "wet paint", "soft edges", "flowing colors", "traditional art", "painting", "artistic", "brush strokes", "delicate", "transparent colors", "paper texture"],
            negative_keywords=["digital", "sharp", "photograph", "3d render", "hard edges"],
        ),
        LoRAMetadata(
            id="z_art",
            name="Z-Art Style",
            trigger_word="z-art",
            template="z-art style, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Z-Art-3.safetensors",
            keywords=["z-art", "artistic", "creative", "stylized", "unique style", "modern art", "digital art", "contemporary", "expressive", "abstract elements", "artistic interpretation"],
            negative_keywords=["realistic", "photograph", "plain", "simple", "basic"],
        ),
        LoRAMetadata(
            id="aesthetic_base",
            name="Aesthetic Base",
            trigger_word="aesthetic",
            template="aesthetic, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Z-Image-Aesthetic-Base%20v1.safetensors",
            keywords=["aesthetic", "beautiful", "visually pleasing", "artistic", "harmonious", "balanced composition", "eye catching", "stylish", "trendy", "instagram aesthetic", "vaporwave"],
            negative_keywords=["ugly", "messy", "chaotic", "low quality", "amateur"],
        ),
        LoRAMetadata(
            id="anime_epic_nsfw",
            name="Anime Epic Stylized",
            trigger_word="epic anime",
            template="epic stylized anime, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/z-image-anime-01-epic-stylized-nsfw.safetensors",
            keywords=["epic anime", "stylized anime", "dramatic anime", "intense anime", "action anime", "dynamic anime", "powerful", "heroic anime", "anime art", "detailed anime", "impressive anime"],
            negative_keywords=["simple", "minimal", "cute", "chibi", "slice of life", "kid", "realistic"],
        ),
        LoRAMetadata(
            id="anime_artistic",
            name="Anime Artistic Interesting",
            trigger_word="artistic anime",
            template="artistic anime, interesting style, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Z-IMAGE_ANIME_ineresting_anime_artistic.safetensors",
            keywords=["artistic anime", "creative anime", "unique anime", "interesting style", "experimental anime", "avant-garde anime", "stylish anime", "anime illustration", "anime concept art"],
            negative_keywords=["basic", "generic", "simple", "standard", "boring"],
        ),
        LoRAMetadata(
            id="cosplay_nsfw",
            name="Cosplay NSFW",
            trigger_word="cosplay nsfw",
            template="cosplay, nsfw, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/zimage_cos-NSFW-lora.safetensors",
            keywords=["cosplay nsfw", "sexy cosplay", "adult cosplay", "erotic costume", "mature cosplay", "risque costume", "provocative"],
            negative_keywords=["sfw", "family friendly", "cartoon", "child", "innocent"],
        ),
        LoRAMetadata(
            id="samdoesarts",
            name="Sam Does Arts Comic",
            trigger_word="samdoesarts style",
            template="samdoesarts style, comic cartoon, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/z-samdoesarts_style_comic_cartoon.safetensors",
            keywords=["samdoesarts", "comic style", "cartoon", "stylized portrait", "digital painting", "character art", "illustration", "expressive", "bold lines", "vibrant"],
            negative_keywords=["realistic", "photograph", "plain", "simple", "abstract"],
        ),
    ]


_LORA_MAP: dict[str, LoRAMetadata] | None = None


def get_lora_map() -> dict[str, LoRAMetadata]:
    global _LORA_MAP
    if _LORA_MAP is None:
        _LORA_MAP = {lora.id: lora for lora in get_all_zimage_loras()}
    return _LORA_MAP


def get_lora_by_id(lora_id: str) -> LoRAMetadata | None:
    return get_lora_map().get(lora_id)
