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
    scale: float = 1.0
    keywords: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)

    @property
    def is_adult(self) -> bool:
        metadata_terms = (
            "nsfw", "explicit", "porn", "hentai", "nude", "naked", "breast",
            "ahegao", "erotic", "slut", "bbc",
        )
        metadata = " ".join([self.id, self.name, self.trigger_word, self.url]).lower()
        if any(term in metadata for term in metadata_terms):
            return True

        explicit_keywords = {"nsfw", "porn", "hentai", "nude", "naked", "ahegao", "xxx", "explicit"}
        return any(keyword.lower().strip() in explicit_keywords for keyword in self.keywords)


def apply_lora_template(lora: LoRAMetadata, prompt: str) -> str:
    if not lora.template:
        return prompt
    return lora.template.replace("{prompt}", prompt)


def get_all_zimage_loras() -> list[LoRAMetadata]:
    loras = [
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
    loras.extend(_get_netwrck_extra_zimage_loras())
    return loras


def _get_netwrck_extra_zimage_loras() -> list[LoRAMetadata]:
    """Additional Z-Image adapters from Netwrck's RA1 fal_zimage catalog."""
    return [
        LoRAMetadata(
            id="retro_scifi_90s",
            name="Retro Sci-Fi 90s",
            trigger_word="retro_scifi_90s",
            template="retro_scifi_90s, retro_artstyle, retro, cyberpunk, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/retro_scifi-90s_anime_style_Z_image_turbo.safetensors",
            scale=0.8,
            keywords=["retro_scifi_90s", "retro_artstyle", "retro", "cyberpunk", "90s retro", "retro sci-fi", "retrofuturism", "synthwave", "neon grid", "vhs", "chrome", "arcade", "neon", "hover car", "flying car", "neon signs", "glowing signs", "night street", "cyberpunk city", "synthwave street", "retro future"],
            negative_keywords=["modern", "minimal", "plain", "realistic", "corporate", "photorealistic", "clean background"],
        ),
        LoRAMetadata(
            id="flat2",
            name="Flat Anime Style Clear",
            trigger_word="flat2",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Flat_AnimeStyle_Agino_ZImage_Clear.safetensors",
            keywords=["flat2", "flat anime", "clear style", "clean anime", "simple anime", "2d anime", "clean lines", "anime flat", "cel shading", "outline art", "anime illustration", "crisp outlines", "studio background", "anime girl portrait", "cel-shaded"],
            negative_keywords=["realistic", "3d", "photographic", "messy", "painterly", "grainy", "noisy", "blurred"],
        ),
        LoRAMetadata(
            id="ag_zib_v1",
            name="AG ZIB V1",
            trigger_word="ag_zib_v1",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/ag_zib_v1.safetensors",
            keywords=["ag_zib_v1", "mpg_zib_base_q2c_nqr32", "zib", "base", "stylized", "experimental", "bold contrast", "mixed media", "nsfw", "porn"],
            negative_keywords=["photorealistic", "minimal", "clean vector", "flat colors"],
        ),
        LoRAMetadata(
            id="dpthsdmx_zimg",
            name="Depth SDMX ZIMG",
            trigger_word="dpthsdmxZIMG",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/dpthsdmxZIMG.safetensors",
            keywords=["blowjob", "bbc", "black cock white wife", "pov porn", "sucking dick", "interracial", "bj", "nsfw"],
            negative_keywords=["flat", "single layer", "minimal", "plain", "anime"],
        ),
        LoRAMetadata(
            id="handholding_hhcplmx_zimg",
            name="Handholding HHCPLMX ZIMG",
            trigger_word="handholdinghhcplmxZIMG",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/handholdinghhcplmxZIMG.safetensors",
            keywords=["handholding", "black cock", "nsfw", "holding hands", "white wife slut porn", "bbc", "naked"],
            negative_keywords=["solo", "separate", "distant", "alone", "clothed"],
        ),
        LoRAMetadata(
            id="kissing",
            name="Kissing",
            trigger_word="kissing",
            template="kissing, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/kissing.safetensors",
            keywords=["kissing", "romance", "couple", "intimate", "passion", "romantic", "close up", "affection", "nsfw", "porn", "making out lovers"],
            negative_keywords=["platonic", "distant", "solo", "separate", "1girl", "alone"],
        ),
        LoRAMetadata(
            id="hentai_quality_studio_z_image_turbo",
            name="Quality",
            trigger_word="hentai_quality_studio_z_image_turbo",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/quality.safetensors",
            keywords=["hentai quality studio", "quality", "studio", "anime", "high detail", "sharp", "detailed", "clean", "hentai", "hardcore", "porn", "busty", "curvy anime woman", "voluptuous anime woman", "glamorous anime woman", "sexy adult anime woman", "low-cut dress", "seductive expression", "glamorous pose"],
            negative_keywords=["low quality", "blurry", "muddy", "simple", "realistic", "male", "handsome man", "tailored suit", "strong jawline", "elegant pose", "beauty portrait", "refined anime beauty", "clean anime illustration"],
        ),
        LoRAMetadata(
            id="best_breasts",
            name="Best Breasts",
            trigger_word="best breasts",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/realistic%20influencer%20girl%20woman%20large%20photo%20insta%20Breasts.safetensors",
            keywords=["best breasts", "breasts", "influencer girl", "woman", "photo", "portrait", "influencer", "fashion", "selfie", "nsfw", "hot", "porn"],
            negative_keywords=["flat", "blurry", "low detail", "group shot", "anime", "cartoon", "art", "peace", "man", "male", "handsome man", "beard", "strong jawline", "tailored suit", "luxury editorial", "fashion editorial", "elegant dress"],
        ),
        LoRAMetadata(
            id="skinnygirl",
            name="Skinny Girl",
            trigger_word="skinnygirl",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/skinnygirl.safetensors",
            keywords=["skinnygirl", "thin girl", "slim", "portrait", "petite", "fashion", "delicate", "lean", "nsfw", "porn", "slut"],
            negative_keywords=["curvy", "muscular", "heavy", "stocky", "anime"],
        ),
        LoRAMetadata(
            id="steampunkanimerealisticsyberpunk_e10",
            name="Steampunk Anime Realistic Cyberpunk E10",
            trigger_word="steampunkanimerealisticsyberpunk",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/steampunkanimerealisticsyberpunk_E10.safetensors",
            keywords=["steampunkanimerealisticsyberpunk", "steampunk", "cyberpunk", "anime", "brass", "gears", "clockwork", "industrial"],
            negative_keywords=["modern", "minimal", "plain", "sleek"],
        ),
        LoRAMetadata(
            id="ninety_s_anime_aesthetic",
            name="90s Anime Aesthetic",
            trigger_word="90s anime aesthetic",
            template="90s anime aesthetic, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/90s_anime_aesthetic_style_z_image_turbo.safetensors",
            keywords=["90s anime", "anime aesthetic", "retro anime", "vhs", "nostalgic", "retro", "cel shading"],
            negative_keywords=["modern", "photorealistic", "minimal", "3d"],
        ),
        LoRAMetadata(
            id="atomic_heart_noir_moody_war",
            name="Atomic Heart Noir Moody War",
            trigger_word="atomic heart noir",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Atomic%20Heart%20animerealistic-noir-moody-illustration-war.safetensors",
            keywords=["atomic heart", "noir", "moody", "war", "retro sci-fi", "illustration", "dramatic"],
            negative_keywords=["cute", "pastel", "clean", "minimal"],
        ),
        LoRAMetadata(
            id="childish_child_drawing",
            name="Childish Child Drawing",
            trigger_word="childish drawing",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Childishchilddrawing.safetensors",
            keywords=["child drawing", "naive art", "crayon", "kids drawing", "simple doodle", "playful"],
            negative_keywords=["realistic", "detailed", "photographic", "3d"],
        ),
        LoRAMetadata(
            id="medieval_landscape_environment",
            name="Medieval Landscape Environment",
            trigger_word="medieval landscape",
            template="medieval landscape, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Medieval02landscapeenvironment.safetensors",
            keywords=["medieval landscape", "castle", "fantasy environment", "environment art", "ancient", "ruins"],
            negative_keywords=["modern", "urban", "sci-fi", "minimal"],
        ),
        LoRAMetadata(
            id="mosaic_abstract_colorful_weird_art",
            name="Mosaic Abstract Colorful Weird Art",
            trigger_word="mosaic abstract",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Mosaicabstractcolorfulweirdart.safetensors",
            keywords=["mosaic", "abstract", "colorful", "weird art", "geometric", "patterned"],
            negative_keywords=["realistic", "plain", "photographic", "minimal"],
        ),
        LoRAMetadata(
            id="nsfw_realistic_v1",
            name="NSFW Realistic V1",
            trigger_word="nsfw realistic",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/NSFW_realistic_V1.safetensors",
            keywords=["nsfw", "realistic", "adult", "mature", "photorealistic", "explicit", "porn"],
            negative_keywords=["sfw", "cartoon", "anime", "cute"],
        ),
        LoRAMetadata(
            id="perfect_breasts_realistic_nsfw",
            name="Perfect Breasts Realistic NSFW",
            trigger_word="perfect breasts",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/PerfectBreastslargerealisticnsfw.safetensors",
            keywords=["breasts", "nsfw", "realistic", "adult", "portrait", "curvy", "insta girl hot photo dslr", "voluptuous woman", "glamorous woman", "body emphasis"],
            negative_keywords=["flat", "blurred", "cartoon", "clothed", "man", "male", "handsome man", "beard", "strong jawline", "tailored suit", "fashion editorial", "luxury editorial"],
        ),
        LoRAMetadata(
            id="saga_realm_comic_visual_novel_colorful_v2",
            name="Saga Realm Comic Visual Novel",
            trigger_word="saga realm comic",
            template="{prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/SagaRealmcomicinterestingvisualnovel%20colorfulZv2.safetensors",
            keywords=["comic", "visual novel", "colorful", "saga", "fantasy", "illustration"],
            negative_keywords=["realistic", "photo", "plain", "muted"],
        ),
        LoRAMetadata(
            id="the_look_natural_faces_expressions",
            name="The Look Natural Faces Expressions",
            trigger_word="the look",
            template="the look, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/The%20Look%20naturalfacesandexpressions.safetensors",
            keywords=["natural faces", "expressions", "portrait", "realistic face", "subtle lighting", "staring wondering girl woman", "glamorous beauty", "fashion editorial", "elegant dress", "alluring woman", "handsome man", "strong jawline", "tailored suit", "luxury editorial", "confident expression", "beauty portrait"],
            negative_keywords=["cartoon", "anime", "mask", "overstated", "exaggerated breasts", "ahegao", "tongue out"],
        ),
        LoRAMetadata(
            id="vintage_travel_poster",
            name="Vintage Travel Poster",
            trigger_word="vintage travel poster",
            template="vintage travel poster, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/VintageTravelPoster.safetensors",
            keywords=["vintage travel poster", "poster art", "retro travel", "mid century", "classic poster"],
            negative_keywords=["photo", "realistic", "modern", "3d"],
        ),
        LoRAMetadata(
            id="z_image_ahegao_face_tougeouteyescrossed_nsfw",
            name="Z Image Ahegao Face",
            trigger_word="ahegao face",
            template="ahegao face, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Z%20Image%20-%20Ahegao%20Facetougeouteyescrossednsfw.safetensors",
            keywords=["ahegao", "anime face", "nsfw", "crossed eyes", "tongue out", "expressive", "girl woman", "squat"],
            negative_keywords=["serious", "realistic", "plain", "safe", "elegant pose", "alluring face", "clean anime illustration", "beauty portrait"],
        ),
        LoRAMetadata(
            id="z_aesthetic_animedigitalartcosyartworkdogsmileinterestingcolors",
            name="Z Aesthetic Anime Digital Art",
            trigger_word="z aesthetic",
            template="z aesthetic, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Z-Aesthetic-animedigitalartcosyartworkdogsmileinterestingcolors.safetensors",
            keywords=["aesthetic", "anime digital art", "cosy", "dog smile", "interesting colors", "digital art"],
            negative_keywords=["realistic", "flat", "boring", "minimal"],
        ),
        LoRAMetadata(
            id="z_brushwork_paint_illustration_anime",
            name="Z Brushwork Paint Illustration Anime",
            trigger_word="brushwork anime",
            template="brushwork anime, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Z-Brushworkpaintillustrationanime.safetensors",
            keywords=["brushwork", "paint illustration", "anime", "painterly", "brush strokes", "girl woman"],
            negative_keywords=["photo", "realistic", "clean vector", "3d"],
        ),
        LoRAMetadata(
            id="z_clean_linework_anime_girl",
            name="Z Clean Linework Anime Girl",
            trigger_word="clean linework anime girl",
            template="clean linework anime girl, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Z-CleanLineworkanimegirl.safetensors",
            keywords=["clean linework", "anime girl", "line art", "outline", "clean sketch", "popart woman"],
            negative_keywords=["messy", "painterly", "realistic", "blurry"],
        ),
        LoRAMetadata(
            id="z_dark_aesthetic_girl_anime_realistic_cartoon",
            name="Z Dark Aesthetic Girl Anime",
            trigger_word="dark aesthetic girl",
            template="dark aesthetic girl, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Z-DarkAestheticgirlanimerealisticcartoon.safetensors",
            keywords=["dark aesthetic", "anime girl", "realistic cartoon", "moody", "shadowy"],
            negative_keywords=["bright", "pastel", "cute", "simple"],
        ),
        LoRAMetadata(
            id="z_oriental_inkbrush_anime_girl",
            name="Z Oriental Inkbrush Anime Girl",
            trigger_word="oriental inkbrush",
            template="oriental inkbrush, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Z-OrientalInkbrushanimegirl.safetensors",
            keywords=["oriental ink", "inkbrush", "anime girl", "sumi-e", "calligraphy"],
            negative_keywords=["neon", "3d", "realistic photo", "modern"],
        ),
        LoRAMetadata(
            id="z_tinted_lines_clean_sketchy_anime_girl",
            name="Z Tinted Lines Clean Sketchy Anime Girl",
            trigger_word="tinted lines",
            template="tinted lines, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/Z-TintedLinescleansketchyanimegirl.safetensors",
            keywords=["tinted lines", "clean sketch", "anime girl", "line sketch", "illustration"],
            negative_keywords=["photorealistic", "painted", "blurry", "messy"],
        ),
        LoRAMetadata(
            id="zit_v6",
            name="ZIT V6",
            trigger_word="zit v6",
            template="zit v6, {prompt}",
            url="https://netwrckstatic.netwrck.com/static/loras/ZIT-V6.safetensors",
            keywords=["zit", "z image", "v6", "turbo", "anime", "illustration"],
            negative_keywords=["sdxl", "realistic photo", "plain", "minimal"],
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
