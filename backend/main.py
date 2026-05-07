"""
SINAG — Solar Intelligence for Laguna
FastAPI Backend · /estimate endpoint

Usage:
    conda activate sinag
    uvicorn main:app --reload --port 8000

Visit http://localhost:8000 to open the app (token injected automatically).
For public access:  ngrok http 8000
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator

from gee_client import init_gee, get_building_footprint, get_terrain_params
from solar_engine import get_ghi_from_nasa_power, calculate_solar_yield
from roi_engine import calculate_roi, co2_offset, trees_equivalent

# ── Load secrets from .env ─────────────────────────────────────────────────
load_dotenv()
MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN", "")
if not MAPBOX_TOKEN:
    print("⚠️  MAPBOX_TOKEN not set in .env — maps won't load")

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sinag")

# ── Philippine grid emission factor (kg CO₂ / kWh) ────────────────────────
PH_GRID_EMISSION_FACTOR = 0.6820  # DOE 2023 average

# ── App lifespan: authenticate GEE once at startup ────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🌞 SINAG API starting up…")
    init_gee()          # authenticate + initialise Earth Engine
    log.info("✅ Google Earth Engine ready")
    yield
    log.info("🌙 SINAG API shutting down")

app = FastAPI(
    title="SINAG Solar Estimation API",
    description="GeoAI rooftop solar potential estimator for Laguna Province, Philippines.",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow the local HTML file (file://) and any localhost port to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to your domain before production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Request / Response models ──────────────────────────────────────────────
class EstimateRequest(BaseModel):
    lat: float
    lng: float

    @field_validator("lat")
    @classmethod
    def check_lat(cls, v):
        if not (13.5 <= v <= 15.0):
            raise ValueError("Latitude must be within Laguna province (~13.5–15.0°N)")
        return round(v, 6)

    @field_validator("lng")
    @classmethod
    def check_lng(cls, v):
        if not (120.5 <= v <= 122.0):
            raise ValueError("Longitude must be within Laguna province (~120.5–122.0°E)")
        return round(v, 6)


class EstimateResponse(BaseModel):
    # Identity
    address:            str
    lat:                float
    lng:                float
    # Scores
    readiness_score:    str
    # Physical
    usable_area_sqm:    float
    system_size_kwp:    float
    annual_yield_mwh:   float
    roof_tilt_deg:      float
    roof_aspect:        str
    # Financial
    monthly_savings_php: float
    payback_years:       float
    savings_25yr_php:    float
    # Environmental
    co2_offset_tons:     float
    trees_equivalent:    int
    # Technical params (shown on frontend)
    ghi_kwh_m2_day:     float
    performance_ratio:  float
    soiling_factor:     float
    # Debug / confidence
    building_found:     bool
    building_confidence: float


# ── Main endpoint ──────────────────────────────────────────────────────────
@app.post("/estimate", response_model=EstimateResponse)
async def estimate(req: EstimateRequest):
    """
    Full GeoAI solar potential pipeline for a pinned lat/lng.

    Pipeline:
      1. Google Open Buildings V3  →  building footprint + usable area
      2. Copernicus 30m DEM        →  terrain slope / aspect
      3. NASA POWER API            →  20-yr average daily GHI
      4. pvlib (Reindl model)      →  Plane-of-Array irradiance → annual kWh
      5. ROI engine                →  Meralco tariff + 25-yr NPV
    """
    log.info(f"📍 Estimate request  lat={req.lat}  lng={req.lng}")

    # ── Step 1: Building footprint ─────────────────────────────────────────
    try:
        footprint = await get_building_footprint(req.lat, req.lng)
        log.info(
            f"🏠 Building  area={footprint['usable_area_sqm']:.1f}m²  "
            f"found={footprint['building_found']}  conf={footprint['confidence']:.2f}"
        )
    except Exception as e:
        log.error(f"GEE footprint error: {e}")
        raise HTTPException(status_code=502, detail=f"Earth Engine footprint query failed: {e}")

    # ── Step 2: Terrain ────────────────────────────────────────────────────
    try:
        terrain = await get_terrain_params(req.lat, req.lng)
        log.info(
            f"⛰️  Terrain  tilt={terrain['tilt_deg']:.1f}°  "
            f"aspect={terrain['aspect_label']} ({terrain['aspect_deg']:.0f}°)"
        )
    except Exception as e:
        log.warning(f"GEE terrain error (using defaults): {e}")
        terrain = {"tilt_deg": 22.5, "aspect_deg": 200.0, "aspect_label": "South-Southwest"}

    # ── Step 3: GHI from NASA POWER ────────────────────────────────────────
    try:
        ghi_daily = await get_ghi_from_nasa_power(req.lat, req.lng)
        log.info(f"☀️  NASA POWER  GHI={ghi_daily:.3f} kWh/m²/day")
    except Exception as e:
        log.warning(f"NASA POWER error (using Laguna climatology fallback): {e}")
        ghi_daily = 5.10  # Laguna province 20-yr average from PVGIS

    # ── Step 4: Solar physics ──────────────────────────────────────────────
    solar = calculate_solar_yield(
        usable_area_sqm=footprint["usable_area_sqm"],
        ghi_daily=ghi_daily,
        tilt_deg=terrain["tilt_deg"],
        aspect_deg=terrain["aspect_deg"],
    )
    log.info(
        f"⚡ Solar  system={solar['system_size_kwp']:.1f}kWp  "
        f"yield={solar['annual_yield_kwh']:.0f}kWh/yr"
    )

    # ── Step 5: ROI ────────────────────────────────────────────────────────
    roi = calculate_roi(
        annual_yield_kwh=solar["annual_yield_kwh"],
        system_size_kwp=solar["system_size_kwp"],
    )
    log.info(
        f"💰 ROI  monthly=₱{roi['monthly_savings_php']:,.0f}  "
        f"payback={roi['payback_years']:.1f}yr  score={roi['readiness_score']}"
    )

    # ── Assemble response ──────────────────────────────────────────────────
    annual_kwh = solar["annual_yield_kwh"]

    return EstimateResponse(
        address            = footprint.get("address", f"{req.lat:.4f}°N, {req.lng:.4f}°E"),
        lat                = req.lat,
        lng                = req.lng,
        readiness_score    = roi["readiness_score"],
        usable_area_sqm    = round(footprint["usable_area_sqm"], 1),
        system_size_kwp    = round(solar["system_size_kwp"], 1),
        annual_yield_mwh   = round(annual_kwh / 1000, 2),
        roof_tilt_deg      = round(terrain["tilt_deg"], 1),
        roof_aspect        = terrain["aspect_label"],
        monthly_savings_php = round(roi["monthly_savings_php"], 2),
        payback_years      = round(roi["payback_years"], 1),
        savings_25yr_php   = round(roi["savings_25yr_php"]),
        co2_offset_tons    = co2_offset(annual_kwh),
        trees_equivalent   = trees_equivalent(annual_kwh),
        ghi_kwh_m2_day     = round(ghi_daily, 3),
        performance_ratio  = solar["performance_ratio"],
        soiling_factor     = solar["soiling_factor"],
        building_found     = footprint["building_found"],
        building_confidence = footprint["confidence"],
    )


# ── Serve frontend ────────────────────────────────────────────────────────
# app.html lives at backend/static/app.html
# We read it, inject the Mapbox token, and serve it — token never touches git.
STATIC_DIR = Path(__file__).parent / "static"

@app.get("/", response_class=HTMLResponse)
async def serve_app():
    html_path = STATIC_DIR / "app.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="app.html not found in backend/static/")
    html = html_path.read_text()
    # Replace the placeholder with the real token from .env
    html = html.replace("YOUR_MAPBOX_TOKEN_HERE", MAPBOX_TOKEN)
    # Point the frontend at this server automatically
    html = html.replace("window.SINAG_API_URL = null", "window.SINAG_API_URL = '/estimate'")
    return HTMLResponse(html)


# ── Health check ───────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Quick liveness probe — returns EE auth status."""
    import ee
    try:
        # Cheap EE call to confirm auth is valid
        ee.Number(1).getInfo()
        ee_ok = True
    except Exception:
        ee_ok = False

    return {
        "status":  "ok" if ee_ok else "degraded",
        "service": "SINAG Solar API",
        "ee_auth": ee_ok,
        "note":    "If ee_auth=false, run: earthengine authenticate --project YOUR_PROJECT",
    }