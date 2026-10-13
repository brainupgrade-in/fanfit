"""Preset briefs for one-click demo runs.

FIXTURE_PRESETS use the fictional brands in fixtures/world.json (tests, offline dev).
LIVE_PRESETS use real brands. All three were run against live Qloo on 2026-10-13 and give strong, distinct shortlists.
"""
from fanfit.pipeline import Brief

FIXTURE_PRESETS = {
    "cold-brew": {
        "title": "Premium cold brew → Gen-Z in Austin",
        "text": "Launching Northbound Cold Brew, a premium cold brew coffee, to 25-29 year olds in Austin. Looking for artists and podcasts.",
        "brief": Brief(brand="Northbound Cold Brew", category_terms=["cold brew"], age="25_to_29", market="Austin",
                       partner_types=["artist", "podcast"]),
    },
    "trail": {
        "title": "Trail running shoes → outdoor podcasts and creators",
        "text": "Ridgeline Trail Co wants podcasts and creators whose fans love trail running, 30-34, Denver.",
        "brief": Brief(brand="Ridgeline Trail Co", category_terms=["trail running"], age="30_to_34", market="Denver",
                       partner_types=["podcast", "person"]),
    },
    "tour": {
        "title": "Audio brand → tour sponsorship",
        "text": "Vantage Audio, a headphone brand, wants to sponsor a music tour. Which artists' fans fit us? Under 24, Los Angeles.",
        "brief": Brief(brand="Vantage Audio", category_terms=["vinyl records"], age="24_and_younger", market="Los Angeles",
                       partner_types=["artist"]),
    },
}

LIVE_PRESETS = {
    "patagonia-tour": {
        "title": "Patagonia → which tour to sponsor",
        "text": "Patagonia wants to sponsor a music tour. Which artists' fans fit the brand? 30-34 year olds, Denver.",
        "brief": Brief(brand="Patagonia", age="30_to_34", market="Denver", partner_types=["artist"]),
    },
    "glossier": {
        "title": "Glossier → Gen-Z podcasts and creators",
        "text": "Glossier is looking for podcasts and creators whose fans already love the brand. Under 25, Los Angeles.",
        "brief": Brief(brand="Glossier", age="24_and_younger", market="Los Angeles", partner_types=["podcast", "person"]),
    },
    "oatly": {
        "title": "Oatly → podcasts and TV for a London launch",
        "text": "Oatly is launching a new product in London and wants podcasts and TV shows for 25-29 year olds.",
        "brief": Brief(brand="Oatly", age="25_to_29", market="London", partner_types=["podcast", "tv_show"]),
    },
    # Shown as compact chips under the three above. Checked live on 2026-10-13; all are cached for replay mode.
    "red-bull": {
        "title": "Red Bull → artists and athletes",
        "text": "Red Bull is planning a music-and-action-sports event in Los Angeles. Which artists and athletes fit? Under 25.",
        "brief": Brief(brand="Red Bull", age="24_and_younger", market="Los Angeles", partner_types=["artist", "person"]),
    },
    "liquid-death": {
        "title": "Liquid Death → bands and podcasts",
        "text": "Liquid Death wants bands and podcasts whose fans fit the brand, 25-29 year olds in Austin.",
        "brief": Brief(brand="Liquid Death", age="25_to_29", market="Austin", partner_types=["artist", "podcast"]),
    },
    "fenty": {
        "title": "Fenty Beauty → artists and creators",
        "text": "Fenty Beauty is launching in London and wants artists and creators for 25-29 year olds.",
        "brief": Brief(brand="Fenty Beauty", age="25_to_29", market="London", partner_types=["artist", "person"]),
    },
    "taco-bell": {
        "title": "Taco Bell → a festival stage",
        "text": "Taco Bell wants to sponsor a festival stage in Chicago. Which artists' fans fit? Under 25.",
        "brief": Brief(brand="Taco Bell", age="24_and_younger", market="Chicago", partner_types=["artist"]),
    },
    "nike": {
        "title": "Nike → sports podcasts",
        "text": "Nike wants podcast sponsorships in New York for 25-29 year olds.",
        "brief": Brief(brand="Nike", age="25_to_29", market="New York", partner_types=["podcast"]),
    },
    "yeti": {
        "title": "YETI → outdoor podcasts",
        "text": "YETI is looking for podcasts whose listeners fit the brand, 35-44 year olds in Denver.",
        "brief": Brief(brand="YETI", age="35_to_44", market="Denver", partner_types=["podcast"]),
    },
    "ben-jerrys": {
        "title": "Ben & Jerry's → TV and podcasts",
        "text": "Ben & Jerry's wants TV shows and podcasts for 30-34 year olds in Chicago.",
        "brief": Brief(brand="Ben & Jerry's", age="30_to_34", market="Chicago", partner_types=["tv_show", "podcast"]),
    },
}

PRESETS = FIXTURE_PRESETS  # tests and fixture mode


def presets_for(mode: str) -> dict:
    return FIXTURE_PRESETS if mode == "fixture" else LIVE_PRESETS
