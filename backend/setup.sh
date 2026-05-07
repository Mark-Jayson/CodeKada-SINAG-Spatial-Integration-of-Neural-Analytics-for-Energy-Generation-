#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# SINAG Backend — One-shot setup for Mac M4 (Apple Silicon)
# Run this once from the sinag_backend/ folder:
#   chmod +x setup.sh && ./setup.sh
# ═══════════════════════════════════════════════════════════════════════════
set -e

CONDA_BIN="$HOME/miniconda3/bin/conda"
ENV_NAME="sinag"
PYTHON_VER="3.11"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   SINAG Backend Setup  ·  Mac M4 / ARM64        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. Init conda ─────────────────────────────────────────────────────────
if ! command -v conda &>/dev/null; then
    if [ -f "$CONDA_BIN" ]; then
        eval "$($CONDA_BIN shell.bash hook)"
    else
        echo "❌  conda not found. Make sure Miniconda is installed."
        echo "    Run the installer you already have:"
        echo "    bash ~/Miniconda3-latest-MacOSX-arm64.sh"
        exit 1
    fi
fi

# ── 2. Create env ──────────────────────────────────────────────────────────
echo "▶ Creating conda env '$ENV_NAME' (Python $PYTHON_VER)…"
conda create -n "$ENV_NAME" python="$PYTHON_VER" -y --quiet

# ── 3. Activate ───────────────────────────────────────────────────────────
eval "$(conda shell.bash hook)"
conda activate "$ENV_NAME"
echo "✅ Activated: $ENV_NAME"

# ── 4. Install numpy via conda-forge first (best ARM64 wheels) ───────────
echo "▶ Installing numpy + pandas via conda-forge (ARM64 optimised)…"
conda install -c conda-forge numpy=1.26 pandas=2.2 -y --quiet

# ── 5. Install remaining deps via pip ────────────────────────────────────
echo "▶ Installing Python dependencies…"
pip install -r requirements.txt --quiet

echo "✅ All packages installed"

# ── 6. Verify pvlib ───────────────────────────────────────────────────────
python -c "import pvlib; print(f'  pvlib {pvlib.__version__} ✓')"
python -c "import fastapi; print(f'  fastapi {fastapi.__version__} ✓')"
python -c "import ee; print(f'  earthengine-api {ee.__version__} ✓')"

# ── 7. Earth Engine authentication ───────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo " NEXT STEP: Authenticate Google Earth Engine"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo " You need a Google Cloud project with Earth Engine enabled."
echo " If you don't have one:"
echo "   → https://console.cloud.google.com/  (create project)"
echo "   → https://earthengine.google.com/    (enable EE API)"
echo ""
echo " Then run:"
echo ""
echo "   conda activate sinag"
echo "   earthengine authenticate --project YOUR_GCP_PROJECT_ID"
echo ""
echo " This opens a browser for OAuth2. After completing it, test:"
echo ""
echo "   python -c \"import ee; ee.Initialize(); print(ee.Number(42).getInfo())\""
echo ""
echo " You should see:  42"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo " START THE API SERVER"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "   conda activate sinag"
echo "   uvicorn main:app --reload --port 8000"
echo ""
echo " Then open app.html in your browser, find this line:"
echo "   window.SINAG_API_URL = null;"
echo " and change it to:"
echo "   window.SINAG_API_URL = 'http://localhost:8000/estimate';"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ Setup complete!"
echo ""