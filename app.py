import streamlit as st
import pydeck as pdk
import pandas as pd
import numpy as np

# Set Streamlit page configuration for a premium, wide layout
st.set_page_config(
    page_title="SINAG (Spatial Integration of Neural Analytics for Energy Generation)",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded"
)

@st.cache_data
def load_mock_data():
    """
    Simulates the data that will eventually come from your PostGIS database.
    Centers around Santa Rosa, Laguna.
    """
    np.random.seed(42)
    num_buildings = 800
    
    # Santa Rosa coordinates approx: 14.3146, 121.1114
    lats = np.random.normal(14.3146, 0.005, num_buildings)
    lons = np.random.normal(121.1114, 0.005, num_buildings)
    
    # Simulate building footprint area (sq meters)
    areas = np.random.uniform(40, 300, num_buildings)
    
    # Apply 10% setback for usable area
    usable_areas = areas * 0.90
    
    # Simulate roof orientation (South is best in PH)
    orientations = np.random.choice(['South', 'South-West', 'West', 'East', 'North'], num_buildings, p=[0.4, 0.2, 0.15, 0.15, 0.1])
    
    # Base efficiency and irradiance (NASA POWER simulation)
    # E = A * efficiency * irradiance * PR (Performance Ratio)
    efficiency = 0.18 # 18% panel efficiency
    base_irradiance = 1800 # kWh/m2/year
    pr = 0.75 # Performance Ratio
    
    # Calculate yield with orientation penalties
    yields = []
    scores = []
    for area, orientation in zip(usable_areas, orientations):
        multiplier = 1.0 if orientation in ['South', 'South-West'] else (0.85 if orientation in ['East', 'West'] else 0.7)
        energy = area * efficiency * (base_irradiance * multiplier) * pr
        yields.append(energy)
        
        # Calculate a "Solar Score" out of 100 based on yield per sqm
        score = min(100, (energy / area) / (efficiency * base_irradiance * pr) * 100)
        scores.append(score)
        
    # Create DataFrame
    df = pd.DataFrame({
        'lat': lats,
        'lon': lons,
        'usable_area_sqm': usable_areas,
        'orientation': orientations,
        'annual_yield_kwh': yields,
        'solar_score': scores,
        'building_height': np.random.uniform(5, 20, num_buildings) # For 3D extrusion
    })
    
    # Green: High (>80), Yellow: Moderate (60-80), Red: Low (<60)
    def get_color(score):
        if score >= 80:
            return [34, 197, 94, 200]  # Tailwind Green-500
        elif score >= 60:
            return [234, 179, 8, 200]  # Tailwind Yellow-500
        else:
            return [239, 68, 68, 200]  # Tailwind Red-500

    df['color'] = df['solar_score'].apply(get_color)
    return df

# Load the data
df = load_mock_data()

with st.sidebar:
    st.image("https://placehold.co/600x200/22c55e/ffffff?text=SinagMap+MVP", use_container_width=True)
    st.markdown("### 🇵🇭 Laguna Solar Readiness")
    st.markdown("Automated GeoAI Pipeline for Multi-Scalar Solar Potential Auditing. Currently viewing the **Santa Rosa** pilot area.")
    
    st.divider()
    
    # Financial assumptions controls
    st.markdown("#### 💰 Financial Parameters")
    elec_rate = st.slider("Meralco/Coop Rate (PHP/kWh)", min_value=9.0, max_value=18.0, value=12.5, step=0.5)
    sys_cost_per_kwp = st.number_input("System Cost per kWp (PHP)", value=45000, step=1000)
    
    st.divider()
    
    # Map Filters
    st.markdown("#### 🔍 Map Filters")
    min_score = st.slider("Minimum Solar Score", 0, 100, 50)
    filter_orientation = st.multiselect(
        "Filter by Orientation", 
        ['South', 'South-West', 'West', 'East', 'North'],
        default=['South', 'South-West', 'East', 'West']
    )
    
    st.divider()
    
    # The LGU Campaign Angle
    st.markdown("#### 🏆 LGU Leaderboard (Mock)")
    st.dataframe(pd.DataFrame({
        "LGU": ["Santa Rosa", "Biñan", "Calamba"],
        "Green Roofs": ["12,400", "9,850", "8,200"]
    }), hide_index=True)

# Filter data
filtered_df = df[(df['solar_score'] >= min_score) & (df['orientation'].isin(filter_orientation))].copy()

# Calculate dynamic financials
# 1 kWp requires roughly 5.5 sqm of space.
filtered_df['est_system_kwp'] = filtered_df['usable_area_sqm'] / 5.5
filtered_df['monthly_savings_php'] = (filtered_df['annual_yield_kwh'] / 12) * elec_rate
filtered_df['est_install_cost'] = filtered_df['est_system_kwp'] * sys_cost_per_kwp
filtered_df['payback_years'] = filtered_df['est_install_cost'] / (filtered_df['monthly_savings_php'] * 12)

st.title("☀️ SINAG (Spatial Integration of Neural Analytics for Energy Generation)")
st.markdown("Identify high-yield rooftops to accelerate renewable energy adoption and combat localized brownouts.")

# Top-level metrics
col1, col2, col3, col4 = st.columns(4)
col1.metric("Analyzed Rooftops", f"{len(filtered_df):,}")
col2.metric("Total Solar Potential", f"{filtered_df['annual_yield_kwh'].sum() / 1e6:.2f} GWh/yr")
col3.metric("Avg. Monthly Savings", f"₱{filtered_df['monthly_savings_php'].mean():,.2f}")
col4.metric("Avg. Payback Period", f"{filtered_df['payback_years'].mean():.1f} Years")

st.markdown("---")

# We use ColumnLayer to represent buildings as 3D extruded columns. 
# Once you have real polygons, you will switch to pdk.Layer("PolygonLayer")
layer = pdk.Layer(
    "ColumnLayer",
    data=filtered_df,
    get_position='[lon, lat]',
    get_elevation='building_height',
    elevation_scale=3,
    radius=15, # Approximates building size
    get_fill_color='color',
    pickable=True,
    auto_highlight=True,
)

# Set the viewport location to Santa Rosa
view_state = pdk.ViewState(
    longitude=121.1114,
    latitude=14.3146,
    zoom=14.5,
    min_zoom=10,
    max_zoom=20,
    pitch=45,
    bearing=-15,
)

# Tooltip to show details when hovering over a "roof"
tooltip = {
    "html": """
    <b>Solar Readiness Score:</b> {solar_score}<br/>
    <hr style="margin: 4px 0px;" />
    <b>Usable Area:</b> {usable_area_sqm} m²<br/>
    <b>Orientation:</b> {orientation}<br/>
    <b>Est. System Size:</b> {est_system_kwp} kWp<br/>
    <b>Annual Yield:</b> {annual_yield_kwh} kWh<br/>
    <hr style="margin: 4px 0px;" />
    <b>Est. Monthly Savings:</b> ₱{monthly_savings_php}<br/>
    <b>ROI Payback:</b> {payback_years} years
    """,
    "style": {
        "backgroundColor": "#1e293b",
        "color": "white",
        "borderRadius": "8px",
        "padding": "12px",
        "fontFamily": "Inter, sans-serif"
    }
}

# Render map
r = pdk.Deck(
    layers=[layer],
    initial_view_state=view_state,
    tooltip=tooltip,
    map_style="mapbox://styles/mapbox/dark-v11", # Dark mode makes the colors pop
)

st.pydeck_chart(r)

st.markdown("### 📋 Highest ROI Targets (Investment Grade)")
st.markdown("This table simulates the 'Lead Generation' output for solar installers or NGOs targeting high-impact areas.")

# Sort by highest yield and format for display
top_targets = filtered_df.sort_values(by='annual_yield_kwh', ascending=False).head(10).copy()
top_targets = top_targets[['lat', 'lon', 'orientation', 'usable_area_sqm', 'est_system_kwp', 'annual_yield_kwh', 'monthly_savings_php']]

# Format columns for readability
st.dataframe(
    top_targets.style.format({
        'lat': '{:.4f}',
        'lon': '{:.4f}',
        'usable_area_sqm': '{:.1f} m²',
        'est_system_kwp': '{:.1f} kWp',
        'annual_yield_kwh': '{:,.0f} kWh',
        'monthly_savings_php': '₱{:,.2f}'
    }),
    use_container_width=True
)

st.caption("Data is currently simulated for the Santa Rosa pilot. Connect the GEE + PostGIS backend in Phase 3 to populate with live geospatial data.")