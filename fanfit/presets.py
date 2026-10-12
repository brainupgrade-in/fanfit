"""Preset briefs for one-click demo runs. Fixture-mode presets use the fictional brands in fixtures/world.json;
live presets will be replaced with real brands after the SPEC §9 data check."""
from fanfit.pipeline import Brief

PRESETS = {
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
