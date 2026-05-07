"""
solar_engine.py — Solar Physics Engine

Pipeline:
  1. NASA POWER API  →  20-year climatological average GHI (kWh/m²/day)
  2. pvlib           →  GHI → Plane-of-Array (POA) irradiance via Reindl model
  3. Energy equation →  E = A_panel × η × H_POA × PR × soiling_factor

Philippines-specific tuning:
  • Soiling factor 0.93 — Taal volcano dust + urban particulates per doc
  • Performance ratio 0.75 — standard (heat, cabling, inverter losses)
  • Panel efficiency 18% — modern monocrystalline (2026 standard)
  • Panel size 1.7 m² / 400 Wp — current commodity spec
"""

import logging
import math
from typing import Optional

import httpx
import numpy as np
import pvlib

log = logging.getLogger("sinag.solar")

# ── System constants ───────────────────────────────────────────────────────
PANEL_EFFICIENCY   = 0.18     # η  — monocrystalline mono-Si
PANEL_AREA_SQM     = 1.7      # m² per panel (standard 400 Wp)
PANEL_WATT_PEAK    = 400      # Wp

PERFORMANCE_RATIO  = 0.75     # PR — inverter + cabling + temp losses
SOILING_FACTOR     = 0.93     # Laguna dust/volcanic ash correction (doc §2)

# Temperature coefficient loss — PH average ~32°C ambient, panels reach ~55°C
TEMP_COEFF         = -0.004   # per °C, typical mono-Si
TEMP_LOSS          = 1 + TEMP_COEFF * (55 - 25)   # ≈ 0.88

# Laguna location for pvlib (used for astronomical calculations)
LAGUNA_LAT  = 14.28
LAGUNA_LNG  = 121.10
LAGUNA_ALT  = 35      # metres above sea level
TIMEZONE    = "Asia/Manila"

# NASA POWER endpoint
NASA_POWER_URL = (
    "https://power.larc.nasa.gov/api/temporal/climatology/point"
    "?parameters=ALLSKY_SFC_SW_DWN,CLRSKY_SFC_SW_DWN,ALLSKY_SFC_SW_DNI,ALLSKY_SFC_SW_DIF"
    "&community=RE"
    "&longitude={lng}&latitude={lat}"
    "&format=JSON"
)

# Laguna 20-yr climatology fallback (from PVGIS) — used if NASA POWER is unavailable
LAGUNA_GHI_FALLBACK = 5.10   # kWh/m²/day


# ── NASA POWER ─────────────────────────────────────────────────────────────
async def get_ghi_from_nasa_power(lat: float, lng: float) -> float:
    """
    Fetch 20-year climatological average daily Global Horizontal Irradiance
    from NASA POWER API.

    Returns GHI in kWh/m²/day (annual average).
    Falls back to Laguna climatology constant on any HTTP error.
    """
    url = NASA_POWER_URL.format(lat=lat, lng=lng)

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        ghi_params = data["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
        # "ANN" key = annual average across all months
        ghi_annual = float(ghi_params["ANN"])

        # Sanity check (Laguna gets 4.5–5.8 kWh/m²/day)
        if not (3.5 <= ghi_annual <= 8.0):
            log.warning(f"Unexpected NASA POWER GHI={ghi_annual}, using fallback")
            return LAGUNA_GHI_FALLBACK

        log.debug(f"NASA POWER GHI = {ghi_annual:.3f} kWh/m²/day")
        return ghi_annual

    except Exception as exc:
        log.warning(f"NASA POWER unavailable ({exc}) — using Laguna fallback {LAGUNA_GHI_FALLBACK}")
        return LAGUNA_GHI_FALLBACK


# ── pvlib Solar Physics ────────────────────────────────────────────────────
def calculate_solar_yield(
    usable_area_sqm: float,
    ghi_daily: float,
    tilt_deg: float,
    aspect_deg: float,
) -> dict:
    """
    Convert usable roof area + GHI into annual energy yield using pvlib.

    The key physics step: GHI (horizontal) → POA (tilted surface).
    We use the Reindl diffuse irradiance transposition model,
    which is recommended by pvlib for tropical locations.

    Formula from doc:
        E = A_usable × η × H_POA × PR × soiling

    Parameters
    ----------
    usable_area_sqm : float  — usable roof area (m²) after setback
    ghi_daily       : float  — annual avg daily GHI (kWh/m²/day)
    tilt_deg        : float  — roof/terrain tilt angle (°)
    aspect_deg      : float  — surface azimuth clockwise from North (°)

    Returns
    -------
    dict with system_size_kwp, annual_yield_kwh, poa_daily, etc.
    """
    # ── 1. Derive panel count and system capacity ──────────────────────────
    n_panels       = max(1, int(usable_area_sqm / PANEL_AREA_SQM))
    system_kwp     = (n_panels * PANEL_WATT_PEAK) / 1000.0

    log.debug(f"Panels: {n_panels} × {PANEL_WATT_PEAK}Wp = {system_kwp:.2f} kWp")

    # ── 2. pvlib location ──────────────────────────────────────────────────
    location = pvlib.location.Location(
        latitude  = LAGUNA_LAT,
        longitude = LAGUNA_LNG,
        tz        = TIMEZONE,
        altitude  = LAGUNA_ALT,
    )

    # ── 3. Build a synthetic TMY-like annual time series (hourly) ──────────
    # We use pvlib's clear-sky model scaled to the NASA POWER GHI to get a
    # representative annual irradiance profile without needing actual TMY data.
    times = pvlib.location.Location(
        latitude=LAGUNA_LAT, longitude=LAGUNA_LNG, tz=TIMEZONE
    )

    # Use a full typical-year time index (2019 = no major anomalies in PH)
    import pandas as pd
    times_index = pd.date_range(
        start="2019-01-01", end="2019-12-31 23:00", freq="h", tz=TIMEZONE
    )

    # Solar position
    solar_pos = location.get_solarposition(times_index)

    # Ineichen clear-sky model (fast, good for tropical latitudes)
    clear_sky = location.get_clearsky(times_index, model="ineichen")

    # Scale clear-sky GHI to match the NASA POWER climatological average
    # NASA POWER gives annual avg daily GHI; convert to annual total kWh/m²
    nasa_annual_total = ghi_daily * 365   # kWh/m²/yr
    cs_annual_total   = clear_sky["ghi"].sum() / 1000  # Wh→kWh
    scale_factor      = nasa_annual_total / max(cs_annual_total, 1.0)

    ghi_series  = clear_sky["ghi"]  * scale_factor   # W/m²  (scaled)
    dni_series  = clear_sky["dni"]  * scale_factor
    dhi_series  = clear_sky["dhi"]  * scale_factor

    # ── 4. Transpose GHI → POA using Reindl model ─────────────────────────
    # Reindl requires extraterrestrial DNI (solar constant adjusted for
    # Earth-Sun distance variation throughout the year)
    dni_extra = pvlib.irradiance.get_extra_radiation(times_index)

    poa_irradiance = pvlib.irradiance.get_total_irradiance(
        surface_tilt    = tilt_deg,
        surface_azimuth = aspect_deg,
        solar_zenith    = solar_pos["apparent_zenith"],
        solar_azimuth   = solar_pos["azimuth"],
        dni             = dni_series,
        ghi             = ghi_series,
        dhi             = dhi_series,
        model           = "reindl",   # recommended for tropics
        dni_extra       = dni_extra,  # required by Reindl decomposition
    )

    poa_annual_kwh_m2 = poa_irradiance["poa_global"].sum() / 1000  # kWh/m²/yr
    poa_daily         = poa_annual_kwh_m2 / 365

    log.debug(
        f"POA annual={poa_annual_kwh_m2:.1f} kWh/m²/yr  "
        f"daily={poa_daily:.3f} kWh/m²/day  (GHI daily={ghi_daily:.3f})"
    )

    # ── 5. Energy equation ─────────────────────────────────────────────────
    #   E = A_panel_total × η × H_POA × PR × soiling × temp_loss
    panel_total_area  = n_panels * PANEL_AREA_SQM   # m²
    annual_yield_kwh  = (
        panel_total_area
        * PANEL_EFFICIENCY
        * poa_annual_kwh_m2
        * PERFORMANCE_RATIO
        * SOILING_FACTOR
        * TEMP_LOSS
    )

    log.debug(
        f"Energy: {panel_total_area:.1f}m² × {PANEL_EFFICIENCY} × "
        f"{poa_annual_kwh_m2:.0f} × {PERFORMANCE_RATIO} × {SOILING_FACTOR} "
        f"× {TEMP_LOSS:.3f} = {annual_yield_kwh:.0f} kWh/yr"
    )

    return {
        "system_size_kwp":   round(system_kwp, 2),
        "n_panels":          n_panels,
        "annual_yield_kwh":  round(annual_yield_kwh, 1),
        "poa_annual_kwh_m2": round(poa_annual_kwh_m2, 2),
        "poa_daily":         round(poa_daily, 3),
        "scale_factor":      round(scale_factor, 4),
        "performance_ratio": PERFORMANCE_RATIO,
        "soiling_factor":    SOILING_FACTOR,
        "temp_loss":         round(TEMP_LOSS, 4),
    }