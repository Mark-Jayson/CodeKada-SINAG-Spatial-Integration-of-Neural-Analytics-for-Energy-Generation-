"""
gee_client.py — Google Earth Engine queries

Covers:
  • init_gee()              — authenticate once at startup
  • get_building_footprint() — Google Open Buildings V3 → usable area
  • get_terrain_params()     — Copernicus 30m DEM → slope & aspect
"""

import math
import asyncio
import logging
import os

import ee

log = logging.getLogger("sinag.gee")

# ── Constants ──────────────────────────────────────────────────────────────
OPEN_BUILDINGS_ASSET = "GOOGLE/Research/open-buildings/v3/polygons"
COPERNICUS_DEM_ASSET = "COPERNICUS/DEM/GLO30"

SETBACK_FACTOR       = 0.90   # 10% edge setback (structural clearance per doc)
SEARCH_RADIUS_M      = 100    # metres around the pin to find buildings
DEM_RADIUS_M         = 150    # neighbourhood average radius for slope/aspect

# Fallback values (typical urban residential in Laguna)
FALLBACK_AREA_SQM    = 72.0   # m² usable (conservative residential)
FALLBACK_TILT_DEG    = 22.5   # Philippine average roof pitch per doc
FALLBACK_ASPECT_DEG  = 195.0  # South-Southwest (good for PH)


# ── GEE Initialisation ─────────────────────────────────────────────────────
def init_gee() -> None:
    """
    Initialise the Earth Engine Python API.

    Priority order for credentials:
      1. GOOGLE_CLOUD_PROJECT env var   (CI / cloud deployments)
      2. ~/.config/earthengine/         (local: after `earthengine authenticate`)

    If neither works, the API starts in degraded mode and GEE calls will
    fall through to their fallback values.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")

    try:
        if project:
            ee.Initialize(project=project)
            log.info(f"GEE initialised with project='{project}'")
        else:
            ee.Initialize()
            log.info("GEE initialised using local credentials")
    except ee.EEException as exc:
        log.warning(
            f"GEE auth failed ({exc}). "
            "Run:  earthengine authenticate --project YOUR_GCP_PROJECT_ID"
        )


# ── Building Footprint ─────────────────────────────────────────────────────
async def get_building_footprint(lat: float, lng: float) -> dict:
    """
    Async wrapper — runs blocking GEE call in a thread pool so FastAPI
    stays non-blocking while Earth Engine does its thing.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _query_building, lat, lng)


def _query_building(lat: float, lng: float) -> dict:
    """
    Query Google Open Buildings V3 for the nearest polygon to (lat, lng).

    Returns a dict with:
      usable_area_sqm   — footprint × 0.90 setback
      total_area_sqm    — raw Open Buildings polygon area_in_meters
      confidence        — Open Buildings model confidence (0–1)
      address           — human-readable string
      building_found    — bool
    """
    point  = ee.Geometry.Point([lng, lat])
    buffer = point.buffer(SEARCH_RADIUS_M)

    try:
        collection = (
            ee.FeatureCollection(OPEN_BUILDINGS_ASSET)
            .filterBounds(buffer)
            .limit(10)          # grab a few candidates, pick closest
        )
        info = collection.getInfo()
    except Exception as exc:
        log.error(f"Open Buildings query failed: {exc}")
        return _fallback_building(lat, lng)

    features = info.get("features", [])
    if not features:
        log.info(f"No building found within {SEARCH_RADIUS_M}m of ({lat:.5f}, {lng:.5f})")
        return _fallback_building(lat, lng)

    best  = _nearest_feature(lat, lng, features)
    props = best.get("properties", {})

    raw_area   = float(props.get("area_in_meters", FALLBACK_AREA_SQM / SETBACK_FACTOR))
    confidence = float(props.get("confidence", 0.0))
    usable     = raw_area * SETBACK_FACTOR

    log.debug(
        f"Building found  raw={raw_area:.1f}m²  "
        f"usable={usable:.1f}m²  conf={confidence:.2f}"
    )

    return {
        "usable_area_sqm":  round(usable, 2),
        "total_area_sqm":   round(raw_area, 2),
        "confidence":       round(confidence, 3),
        "address":          f"{lat:.4f}°N, {lng:.4f}°E",
        "building_found":   True,
    }


def _fallback_building(lat: float, lng: float) -> dict:
    return {
        "usable_area_sqm":  FALLBACK_AREA_SQM,
        "total_area_sqm":   FALLBACK_AREA_SQM / SETBACK_FACTOR,
        "confidence":       0.0,
        "address":          f"{lat:.4f}°N, {lng:.4f}°E (estimated footprint)",
        "building_found":   False,
    }


def _nearest_feature(lat: float, lng: float, features: list) -> dict:
    """Return the feature whose centroid is closest to the pin."""
    def centroid_dist(feat):
        geom = feat.get("geometry", {})
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])

        if gtype == "Polygon" and coords:
            ring = coords[0]
            cx = sum(c[0] for c in ring) / len(ring)
            cy = sum(c[1] for c in ring) / len(ring)
            return math.hypot(cx - lng, cy - lat)

        if gtype == "MultiPolygon" and coords:
            ring = coords[0][0]
            cx = sum(c[0] for c in ring) / len(ring)
            cy = sum(c[1] for c in ring) / len(ring)
            return math.hypot(cx - lng, cy - lat)

        return float("inf")

    return min(features, key=centroid_dist)


# ── Terrain (DEM slope + aspect) ───────────────────────────────────────────
async def get_terrain_params(lat: float, lng: float) -> dict:
    """Async wrapper for Copernicus DEM slope/aspect query."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _query_terrain, lat, lng)


def _query_terrain(lat: float, lng: float) -> dict:
    """
    Extract terrain slope and aspect from Copernicus GLO-30 DEM.

    Per doc (Technical Refinements section):
      • 30m pixel = neighbourhood terrain, not individual roof pitch.
      • Hybrid model: use terrain slope for hillside areas (>5°),
        otherwise apply Philippine standard 22.5° residential pitch.
      • Aspect identifies predominant South-facing surfaces.
    """
    point  = ee.Geometry.Point([lng, lat])
    region = point.buffer(DEM_RADIUS_M)

    try:
        dem        = ee.Image(COPERNICUS_DEM_ASSET).select("DEM")
        slope_img  = ee.Terrain.slope(dem)
        aspect_img = ee.Terrain.aspect(dem)

        slope_info  = slope_img.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=30
        ).getInfo()
        aspect_info = aspect_img.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=30
        ).getInfo()

        raw_slope  = float(slope_info.get("slope",  FALLBACK_TILT_DEG))
        raw_aspect = float(aspect_info.get("aspect", FALLBACK_ASPECT_DEG))

    except Exception as exc:
        log.warning(f"DEM query failed (using defaults): {exc}")
        raw_slope  = FALLBACK_TILT_DEG
        raw_aspect = FALLBACK_ASPECT_DEG

    # Hybrid tilt model
    if raw_slope > 5.0:
        # Significant terrain (hillside — e.g. near Mt. Makiling or Los Baños slopes)
        tilt_deg = min(raw_slope, 35.0)   # cap at 35° — very steep roofs uncommon
        log.debug(f"Using terrain slope: {tilt_deg:.1f}°")
    else:
        # Flat urban area — apply PH residential standard
        tilt_deg = FALLBACK_TILT_DEG
        log.debug(f"Urban area — using standard PH roof pitch: {tilt_deg:.1f}°")

    aspect_label = _aspect_label(raw_aspect)

    return {
        "tilt_deg":     round(tilt_deg, 2),
        "aspect_deg":   round(raw_aspect, 1),
        "aspect_label": aspect_label,
        "raw_slope":    round(raw_slope, 2),
    }


def _aspect_label(deg: float) -> str:
    """Convert compass degrees to cardinal/intercardinal label."""
    # Normalise to [0, 360)
    deg = deg % 360
    labels = [
        (22.5,  "North"),
        (67.5,  "Northeast"),
        (112.5, "East"),
        (157.5, "Southeast"),
        (202.5, "South"),            # optimal in Philippines (equatorial)
        (247.5, "South-Southwest"),  # next best — long afternoon sun
        (292.5, "West"),
        (337.5, "Northwest"),
        (360.0, "North"),
    ]
    for threshold, label in labels:
        if deg < threshold:
            return label
    return "North"