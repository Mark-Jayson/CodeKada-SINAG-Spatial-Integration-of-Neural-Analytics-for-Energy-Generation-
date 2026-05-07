<div align="center">
  <h1>SINAG</h1>
  <p><strong>Spatial Integration of Neural Analytics for Energy Generation</strong></p>
  <p>A GeoAI rooftop solar potential estimator for Laguna Province, Philippines</p>

  <p>
    <img src="https://img.shields.io/badge/track-Green%20Tech%20%26%20Sustainability-22c55e?style=flat-square"/>
    <img src="https://img.shields.io/badge/hackathon-CodeKada%202026-7c3aed?style=flat-square"/>
    <img src="https://img.shields.io/badge/team-Organic%20Encoders-f59e0b?style=flat-square"/>
  </p>
</div>

---

## What is SINAG?

The Philippines has the second highest electricity rates in Southeast Asia at over ₱12.00/kWh  yet most homeowners never go solar because they don't know if their specific roof is worth it.

SINAG solves this. Pin any address in Laguna Province, and in seconds you get your roof's usable area, estimated solar system size, monthly savings, payback period, and a 25-year ROI, all powered by real satellite data, no manual inspection needed.

---

## How It Works

1. **Find your building** — Satellite imagery identifies your exact rooftop and usable area
2. **Analyze your roof** — Slope and orientation are calculated from elevation data
3. **Model the sun** — 20 years of solar irradiance data is used to estimate your annual energy yield
4. **Calculate your ROI** — Monthly savings, payback period, and CO₂ offset are computed using current Meralco/FLECO rates

---

## Running the App

### Requirements

- Python 3.11 (via [Miniconda](https://docs.conda.io/en/latest/miniconda.html))
- Google Cloud project with Earth Engine API enabled
- Mapbox account (free tier works)
- ngrok (free) for sharing a live link

### Setup

```bash
# 1. Install dependencies
conda create -n sinag python=3.11 -y
conda activate sinag
pip install -r requirements.txt

# 2. Authenticate Google Earth Engine
earthengine authenticate --project YOUR_GCP_PROJECT_ID

# 3. Set up your secrets
cp .env.example .env
# Fill in MAPBOX_TOKEN and GOOGLE_CLOUD_PROJECT in .env

# 4. Copy the frontend
mkdir -p static && cp ../app.html static/app.html

# 5. Start the server
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) — pin any location in Laguna to get your solar report.

To share a live link: `ngrok http 8000`

---

## Solar Readiness Score

| Score | Payback Period |
|---|---|
| **A+** | ≤ 5 years |
| **A** | 5–7 years |
| **B+** | 7–9 years |
| **B** | 9–12 years |
| **C** | > 12 years |

---

## Team — Organic Encoders

| Member | Role |
|---|---|
| **Jayson** | UI Design & Frontend |
| **Judie** | Backend + AI Engineering & Documentation|
| **Klyde** | Video & Presentation |

*Built for the CodeKada 2026 Hackathon — Green Tech & Sustainability track.*

---

<div align="center">
  <sub>Made with ☀️ in Laguna, Philippines</sub>
</div>
