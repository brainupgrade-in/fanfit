"""Generate fixtures/world.json: a small, fully fictional taste graph for fixture mode.

Usage: uv run scripts/gen_world.py
"""
import json
import random
import uuid
from pathlib import Path

rng = random.Random(42)
uid = lambda name: str(uuid.uuid5(uuid.NAMESPACE_URL, "fanfit/" + name)).upper()

TAGS = {
    "specialty coffee": "keyword", "cold brew": "keyword", "indie folk": "genre:music", "lo-fi": "genre:music",
    "hip hop": "genre:music", "trail running": "keyword", "outdoor adventure": "keyword", "hot sauce": "keyword",
    "street food": "keyword", "comedy": "genre:media", "true crime": "genre:media", "design": "keyword",
    "sustainability": "keyword", "skateboarding": "keyword", "synthwave": "genre:music", "productivity": "keyword",
    "craft beer": "keyword", "vinyl records": "keyword", "camping": "keyword", "latin pop": "genre:music",
}
tag_id = {n: f"urn:tag:{t}:fanfit:{n.replace(' ', '_')}" for n, t in TAGS.items()}

BRANDS = [
    ("Northbound Cold Brew", ["specialty coffee", "cold brew", "indie folk", "design", "sustainability"]),
    ("Ridgeline Trail Co", ["trail running", "outdoor adventure", "camping", "sustainability", "craft beer"]),
    ("Ember & Ash Hot Sauce", ["hot sauce", "street food", "hip hop", "comedy", "craft beer"]),
    ("Vantage Audio", ["vinyl records", "synthwave", "hip hop", "design", "latin pop"]),
]
PARTNERS = {
    "urn:entity:artist": ["The Low Pines", "Mara Quill", "Static Harbor", "DJ Copperline", "Neon Avenue", "Sol y Brasa",
                          "Juniper Ash", "Kilo Verse", "Velvet Arcade", "Rio Marea", "Hollow Creek", "Bassline Union"],
    "urn:entity:podcast": ["Grounds for Thought", "The Long Trail", "Spice Route Radio", "Deep Focus", "Case Files Weekly",
                           "Stand-Up Breakdown", "Analog Hours", "Weekend Wild", "Build Better", "Late Night Snacks"],
    "urn:entity:tv_show": ["Off the Map", "Kitchen Underground", "Laugh Track Live", "Cold Case Coast", "Studio Sessions",
                           "Wild Weekends", "Made by Hand", "Night Market"],
    "urn:entity:person": ["Ava Stride", "Leo Kettle", "Priya Ramp", "Marcus Vane", "Nina Board", "Theo Summit",
                          "Lena Fuego", "Omar Grind"],
}
BANDS = ["24_and_younger", "25_to_29", "30_to_34", "35_to_44", "45_to_54", "55_and_older"]


def entity(name, etype, tags):
    # Shapes follow live Qloo (checked 2026-10-13): age values are -1..1 affinity indices.
    return {
        "entity_id": uid(name), "name": name, "type": etype,
        "popularity": round(rng.uniform(0.2, 0.95), 3),
        "tags": [tag_id[t] for t in tags],
        "demographics": {"age": {b: round(rng.uniform(-1, 1), 2) for b in BANDS},
                         "gender": {"male": (g := round(rng.uniform(-0.5, 0.5), 2)), "female": -g}},
    }


entities = [entity(n, "urn:entity:brand", t) for n, t in BRANDS]
for etype, names in PARTNERS.items():
    for n in names:
        entities.append(entity(n, etype, rng.sample(list(TAGS), rng.randint(2, 4))))

world = {
    "_note": "Synthetic, fictional data for fixture mode. Not Qloo data.",
    "tags": [{"id": tag_id[n], "name": n, "type": f"urn:tag:{t}"} for n, t in TAGS.items()],
    "entities": entities,
}
out = Path(__file__).resolve().parent.parent / "fixtures" / "world.json"
out.write_text(json.dumps(world, indent=1))
print(f"wrote {out} ({len(entities)} entities)")
