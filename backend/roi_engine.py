"""
roi_engine.py — Financial ROI & Environmental Impact

Localised for the Philippine market:
  • Electricity tariff: Meralco / FLECO ₱12.00/kWh (2026 average per doc)
  • Installation cost:  ₱55,000/kWp (panels + inverter + mounting + labour)
  • Escalation rate:    4% per year (EPIRA-mandated annual rate review trend)
  • Net-metering:       Republic Act 9513 / ERC Resolution No. 09-2013
  • CO₂ factor:         0.6820 kg CO₂/kWh (DOE Philippines 2023 grid emission)
  • Tree equivalent:    1 tree sequesters ~29.5 kg CO₂/yr (FAO estimate)
"""

import logging

log = logging.getLogger("sinag.roi")

# ── Tariff & system cost ───────────────────────────────────────────────────
MERALCO_RATE_PHP_KWH  = 12.00   # ₱/kWh — average 2026 (doc states ₱12.00)
INSTALL_COST_PHP_KWP  = 55_000  # ₱/kWp installed (2026 market rates)
NET_METER_EXPORT_RATE = 8.00    # ₱/kWh buyback (WESM spot, conservative)

# ── Financial model ────────────────────────────────────────────────────────
ELECTRICITY_ESCALATION = 0.04   # 4% annual price increase
NPV_YEARS              = 25     # system design life
DISCOUNT_RATE          = 0.06   # 6% cost of capital (PH bank rate)

# ── Environmental constants ────────────────────────────────────────────────
PH_GRID_EMISSION_KG_KWH = 0.6820   # kg CO₂/kWh  (DOE 2023)
TREE_CO2_SEQUESTER_KG   = 29.5     # kg CO₂ per tree per year (FAO)


def calculate_roi(annual_yield_kwh: float, system_size_kwp: float) -> dict:
    """
    Compute all financial metrics for a given solar system.

    Parameters
    ----------
    annual_yield_kwh : float  — annual energy output from solar_engine
    system_size_kwp  : float  — system capacity (kWp)

    Returns
    -------
    dict with monthly_savings, payback_years, savings_25yr, readiness_score
    """
    # ── System capital cost ────────────────────────────────────────────────
    system_cost_php  = system_size_kwp * INSTALL_COST_PHP_KWP
    log.debug(f"System cost: ₱{system_cost_php:,.0f} ({system_size_kwp:.1f}kWp × ₱{INSTALL_COST_PHP_KWP:,})")

    # ── Year-1 savings ─────────────────────────────────────────────────────
    # Under net-metering (RA 9513), a typical household consumes all generated
    # power (self-consumption model). Savings = avoided grid purchase.
    annual_savings_yr1 = annual_yield_kwh * MERALCO_RATE_PHP_KWH
    monthly_savings    = annual_savings_yr1 / 12

    log.debug(
        f"Year-1 annual savings: ₱{annual_savings_yr1:,.0f}  "
        f"Monthly: ₱{monthly_savings:,.0f}"
    )

    # ── Simple payback ─────────────────────────────────────────────────────
    payback_years = system_cost_php / annual_savings_yr1

    # ── 25-year discounted NPV ─────────────────────────────────────────────
    # Revenue grows at electricity escalation rate;
    # cash flows discounted at Philippine cost of capital.
    npv_savings = 0.0
    for year in range(1, NPV_YEARS + 1):
        # Electricity savings grow with tariff escalation
        annual_rate     = MERALCO_RATE_PHP_KWH * (1 + ELECTRICITY_ESCALATION) ** (year - 1)
        annual_savings  = annual_yield_kwh * annual_rate
        # Discount to present value
        discount_factor = (1 + DISCOUNT_RATE) ** year
        npv_savings    += annual_savings / discount_factor

    # Net position after deducting system cost
    net_25yr_php = npv_savings - system_cost_php

    log.debug(
        f"25yr NPV savings: ₱{npv_savings:,.0f}  "
        f"Net (after capex): ₱{net_25yr_php:,.0f}  "
        f"Payback: {payback_years:.1f} yr"
    )

    # ── Readiness score ────────────────────────────────────────────────────
    score = _readiness_score(payback_years)

    return {
        "system_cost_php":    round(system_cost_php),
        "monthly_savings_php": round(monthly_savings, 2),
        "annual_savings_php": round(annual_savings_yr1, 2),
        "payback_years":      round(payback_years, 2),
        "npv_savings_php":    round(npv_savings),
        "savings_25yr_php":   round(max(net_25yr_php, 0)),  # floor at 0
        "readiness_score":    score,
    }


def co2_offset(annual_yield_kwh: float) -> float:
    """
    Annual CO₂ avoided by displacing grid electricity with solar.
    Returns tonnes CO₂/year (1 decimal).
    """
    kg = annual_yield_kwh * PH_GRID_EMISSION_KG_KWH
    return round(kg / 1000, 1)


def trees_equivalent(annual_yield_kwh: float) -> int:
    """
    Number of mature trees needed to sequester the same CO₂ per year.
    """
    kg_co2 = annual_yield_kwh * PH_GRID_EMISSION_KG_KWH
    return round(kg_co2 / TREE_CO2_SEQUESTER_KG)


# ── Internal helpers ───────────────────────────────────────────────────────
def _readiness_score(payback_years: float) -> str:
    """
    Convert payback period to a letter grade.

    Grade  Payback    Interpretation
    A+     ≤ 5 yr     Excellent — fast ROI, strong net-metering candidate
    A      5–7 yr     Very good — standard residential solar economics
    B+     7–9 yr     Good — still viable, slightly larger roof or suboptimal aspect
    B      9–12 yr    Fair — consider smaller system or energy audit first
    C      > 12 yr    Marginal — heavy shading or poor orientation; consult installer
    """
    if payback_years <= 5:
        return "A+"
    elif payback_years <= 7:
        return "A"
    elif payback_years <= 9:
        return "B+"
    elif payback_years <= 12:
        return "B"
    else:
        return "C"