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
}

PRESETS = FIXTURE_PRESETS  # tests and fixture mode


def presets_for(mode: str) -> dict:
    return FIXTURE_PRESETS if mode == "fixture" else LIVE_PRESETS
