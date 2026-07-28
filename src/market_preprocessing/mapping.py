"""Administrative-region to GME-zone mapping for the 2024 baseline.

The mapping follows the geography of the Italian zonal market used in Sapio
(2015, 2019). Sapio (2015) is especially useful for the spatial interpretation
of Italian price effects and the Sicily-mainland interface; Sapio (2019)
provides the later Energy Policy reference for Italian wholesale price zones.
"""

from __future__ import annotations

from collections import defaultdict


REGION_TO_ZONE: dict[str, str] = {
    "Piemonte": "Nord",
    "Valle d'Aosta": "Nord",
    "Lombardia": "Nord",
    "Trentino-Alto Adige": "Nord",
    "Veneto": "Nord",
    "Friuli-Venezia Giulia": "Nord",
    "Liguria": "Nord",
    "Emilia-Romagna": "Nord",
    "Toscana": "Centro Nord",
    "Umbria": "Centro Sud",
    "Marche": "Centro Nord",
    "Lazio": "Centro Sud",
    "Abruzzo": "Centro Sud",
    "Molise": "Sud",
    "Campania": "Centro Sud",
    "Puglia": "Sud",
    "Basilicata": "Sud",
    "Calabria": "Calabria",
    "Sicilia": "Sicilia",
    "Sardegna": "Sardegna",
}

REGION_ALIASES: dict[str, str] = {
    "Valle D'Aosta": "Valle d'Aosta",
    "Trentino Alto Adige": "Trentino-Alto Adige",
    "Friuli Venezia Giulia": "Friuli-Venezia Giulia",
    "Emilia Romagna": "Emilia-Romagna",
}


def canonical_region(region: str) -> str:
    """Return the canonical spelling used in the mapping dictionary."""

    return REGION_ALIASES.get(region, region)


def map_region_to_zone(region: str) -> str:
    """Map one administrative region to its GME bidding zone."""

    canonical = canonical_region(region)
    if canonical not in REGION_TO_ZONE:
        raise ValueError(f"Region not mapped to a GME bidding zone: {region}")
    return REGION_TO_ZONE[canonical]


def regions_by_zone() -> dict[str, list[str]]:
    """Return mapped administrative regions grouped by GME bidding zone."""

    grouped: dict[str, list[str]] = defaultdict(list)
    for region, zone in REGION_TO_ZONE.items():
        grouped[zone].append(region)
    return {zone: sorted(regions) for zone, regions in grouped.items()}

