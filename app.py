import calendar
from pathlib import Path

import folium
import pandas as pd
import plotly.express as px
import streamlit as st

from streamlit_folium import st_folium


# ================================================================
# CONFIG
# ================================================================

YELLOW = "#FFD400"
DARK = "#0B0D10"
CARD = "#15181D"
MUTED = "#9AA0A6"
WHITE = "#F5F5F5"

ESRI = (
    "https://server.arcgisonline.com/"
    "ArcGIS/rest/services/Canvas"
)

MONTHS = list(calendar.month_abbr)[1:]

CATEGORY_ORDER = [
    "Concert",
    "Sports",
    "Theatre",
    "Festival",
    "Exhibition",
    "Market",
]


# ================================================================
# PAGE CONFIG
# ================================================================

st.set_page_config(
    page_title="Gothenburg Events",
    page_icon="🎟️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ================================================================
# CUSTOM CSS
# ================================================================

st.markdown(
    f"""
    <style>

    .stApp {{
        background-color: {DARK};
        color: {WHITE};
    }}

    section[data-testid="stSidebar"] {{
        background-color: #101216;
        border-right: 1px solid #242830;
    }}

    h1 {{
        font-size: 2.4rem !important;
        font-weight: 700 !important;
        letter-spacing: -0.03em;
    }}

    h2, h3 {{
        font-weight: 600 !important;
    }}

    .subtitle {{
        color: {MUTED};
        font-size: 1rem;
        margin-top: -15px;
        margin-bottom: 25px;
    }}

    .metric-card {{
        background: {CARD};
        border: 1px solid #252930;
        border-radius: 12px;
        padding: 18px 20px;
        min-height: 110px;
    }}

    .metric-label {{
        color: {MUTED};
        font-size: 0.85rem;
        margin-bottom: 8px;
    }}

    .metric-value {{
        color: {WHITE};
        font-size: 1.8rem;
        font-weight: 700;
    }}

    .section-title {{
        font-size: 1.15rem;
        font-weight: 600;
        margin-top: 25px;
        margin-bottom: 10px;
    }}

    </style>
    """,
    unsafe_allow_html=True,
)


# ================================================================
# LOAD DATA
# ================================================================

HERE = Path(__file__).resolve().parent

DATA = next(
    (
        p / "events.csv"
        for p in [HERE, *HERE.parents]
        if (p / "events.csv").exists()
    ),
    None,
)

if DATA is None:
    st.error(
        "events.csv not found. Run the data cell first, "
        f"so the file is saved in {HERE} or a folder above it."
    )
    st.stop()

df = pd.read_csv(
    DATA,
    parse_dates=["start"],
)


# ================================================================
# HEADER
# ================================================================

st.title("Gothenburg Events")

st.markdown(
    """
    <div class="subtitle">
        Event activity, attendance and venue analysis across Gothenburg
    </div>
    """,
    unsafe_allow_html=True,
)


# ================================================================
# SIDEBAR FILTERS
# ================================================================

st.sidebar.markdown("## Filters")

# Year
year = st.sidebar.selectbox(
    "Year",
    sorted(df["year"].unique()),
)

year_df = df[df["year"] == year].copy()

# Month
month = st.sidebar.selectbox(
    "Month",
    ["All"] + list(range(1, 13)),
    format_func=lambda m:
        m if m == "All"
        else calendar.month_name[m],
)

filtered = year_df.copy()

if month != "All":
    filtered = filtered[
        filtered["month"] == month
    ]

# Day
if month == "All":

    st.sidebar.selectbox(
        "Day",
        ["All"],
        disabled=True,
    )

else:

    available_days = sorted(
        filtered["day"].unique().tolist()
    )

    day = st.sidebar.selectbox(
        "Day",
        ["All"] + available_days,
    )

    if day != "All":
        filtered = filtered[
            filtered["day"] == day
        ]

# Event category
available_categories = [
    c for c in CATEGORY_ORDER
    if c in year_df["category"].unique()
]

selected_categories = st.sidebar.multiselect(
    "Event type",
    options=available_categories,
    default=available_categories,
)

filtered = filtered[
    filtered["category"].isin(selected_categories)
]

# Venue
venues = sorted(
    filtered["venue"].unique()
)

selected_venues = st.sidebar.multiselect(
    "Venue",
    options=venues,
    default=[],
    help="Leave empty to include all venues.",
)

if selected_venues:
    filtered = filtered[
        filtered["venue"].isin(selected_venues)
    ]


# ================================================================
# KPI CARDS
# ================================================================

total_events = len(filtered)

total_people = int(
    filtered["expected_people"].sum()
)

venue_count = filtered["venue"].nunique()

avg_attendance = (
    int(filtered["expected_people"].mean())
    if not filtered.empty
    else 0
)


def metric_card(label, value):
    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
    </div>
    """


cards = [
    ("EVENTS", total_events),
    ("EXPECTED ATTENDANCE", total_people),
    ("VENUES", venue_count),
    ("AVG. ATTENDANCE / EVENT", avg_attendance),
]

for column, (label, value) in zip(st.columns(4), cards):
    with column:
        st.markdown(
            metric_card(label, f"{value:,}"),
            unsafe_allow_html=True,
        )

st.markdown("")


# ================================================================
# MAP
# ================================================================

st.markdown(
    '<div class="section-title">Event activity by venue</div>',
    unsafe_allow_html=True,
)

m = folium.Map(
    location=[57.702, 11.972],
    zoom_start=13,
    max_zoom=16,
    tiles=(
        f"{ESRI}/World_Dark_Gray_Base/"
        "MapServer/tile/{z}/{y}/{x}"
    ),
    attr=(
        "Tiles © Esri, HERE, Garmin, "
        "© OpenStreetMap contributors"
    ),
)

folium.TileLayer(
    tiles=(
        f"{ESRI}/World_Dark_Gray_Reference/"
        "MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri",
    max_zoom=16,
    overlay=True,
    control=False,
).add_to(m)

# Dark overlay: raise fill_opacity for a darker map
folium.Rectangle(
    bounds=[
        [-90, -180],
        [90, 180],
    ],
    stroke=False,
    fill=True,
    fill_color="#000000",
    fill_opacity=0.45,
).add_to(m)

# One dot per venue
spots = (
    filtered
    .groupby(
        ["venue", "lat", "lon"],
        as_index=False,
    )
    .agg(
        events=("name", "count"),
        people=("expected_people", "sum"),
    )
)

# Categories per venue
category_summary = (
    filtered
    .groupby("venue")["category"]
    .apply(
        lambda x: ", ".join(
            sorted(x.unique())
        )
    )
    .to_dict()
)

if not spots.empty:

    biggest = spots["people"].max()

    for _, s in spots.iterrows():

        venue = s["venue"]

        size = (
            5 + 35 * (s["people"] / biggest) ** 0.5
            if biggest > 0
            else 5
        )

        popup_html = f"""
        <div style="font-family:Arial; min-width:220px;">
            <h4 style="margin-bottom:8px;">{venue}</h4>
            <b>Events:</b> {int(s["events"]):,}<br>
            <b>Expected attendance:</b> {int(s["people"]):,}<br>
            <b>Event categories:</b><br>
            {category_summary.get(venue, "—")}
        </div>
        """

        folium.CircleMarker(
            location=[s["lat"], s["lon"]],
            radius=size,
            color=YELLOW,
            weight=1.5,
            opacity=1,
            fill=True,
            fill_color=YELLOW,
            fill_opacity=0.25,
            tooltip=(
                f"<b>{venue}</b><br>"
                f"{int(s['events']):,} events · "
                f"{int(s['people']):,} expected people"
            ),
            popup=folium.Popup(
                popup_html,
                max_width=300,
            ),
        ).add_to(m)

st_folium(
    m,
    height=560,
    use_container_width=True,
    returned_objects=[],
)


# ================================================================
# CHART STYLE
# ================================================================

def style(fig):

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=55, b=10),
        height=360,
        font=dict(color=WHITE),
    )

    fig.update_yaxes(
        gridcolor="rgba(255,255,255,0.08)"
    )

    fig.update_xaxes(
        showgrid=False
    )

    return fig


# ================================================================
# ANALYTICS
# ================================================================

st.markdown(
    '<div class="section-title">Event analytics</div>',
    unsafe_allow_html=True,
)

tab1, tab2, tab3 = st.tabs(
    [
        "Event volume",
        "Attendance",
        "Event categories",
    ]
)

# TAB 1: events per month, fixed to the selected year
with tab1:

    per_month = (
        year_df
        .groupby("month")
        .size()
        .reindex(
            range(1, 13),
            fill_value=0,
        )
    )

    fig = px.line(
        x=MONTHS,
        y=per_month.values,
        markers=True,
        title=f"Events per month · {year}",
        labels={
            "x": "Month",
            "y": "Events",
        },
        color_discrete_sequence=[YELLOW],
    )

    fig.update_traces(
        line=dict(width=3),
        marker=dict(size=7),
    )

    st.plotly_chart(
        style(fig),
        width="stretch",
    )

# TAB 2: expected people per event, fixed to the selected year
with tab2:

    per_event = year_df.assign(
        month_name=year_df["month"].map(
            lambda n: calendar.month_abbr[n]
        )
    )

    fig = px.strip(
        per_event,
        x="month_name",
        y="expected_people",
        hover_name="name",
        hover_data=[
            "category",
            "venue",
            "start",
        ],
        log_y=True,
        category_orders={
            "month_name": MONTHS
        },
        title=f"Expected attendance per event · {year}",
        labels={
            "month_name": "Month",
            "expected_people": "Expected people",
        },
        color_discrete_sequence=[YELLOW],
    )

    fig.update_traces(
        marker=dict(
            size=7,
            opacity=0.55,
            line=dict(
                width=1,
                color=YELLOW,
            ),
        )
    )

    st.plotly_chart(
        style(fig),
        width="stretch",
    )

# TAB 3: events by category, follows the filters
with tab3:

    category_counts = (
        filtered
        .groupby("category")
        .size()
        .reindex(
            CATEGORY_ORDER,
            fill_value=0,
        )
        .reset_index(name="events")
    )

    fig = px.bar(
        category_counts,
        x="category",
        y="events",
        title="Events by event type",
        labels={
            "category": "Event type",
            "events": "Events",
        },
        color_discrete_sequence=[YELLOW],
    )

    st.plotly_chart(
        style(fig),
        width="stretch",
    )


# ================================================================
# CATEGORY OVERVIEW
# ================================================================

st.markdown(
    '<div class="section-title">Category overview</div>',
    unsafe_allow_html=True,
)

category_summary_df = (
    filtered
    .groupby("category")
    .agg(
        events=("event_id", "count"),
        expected_people=("expected_people", "sum"),
        avg_attendance=("expected_people", "mean"),
        venues=("venue", "nunique"),
    )
    .reindex(CATEGORY_ORDER)
    .dropna(how="all")
    .round()
    .astype(int)
    .reset_index()
)

st.dataframe(
    category_summary_df,
    width="stretch",
    hide_index=True,
    column_config={
        "category": "Event type",
        "events": "Events",
        "expected_people": "Expected attendance",
        "avg_attendance": "Avg. attendance",
        "venues": "Venues",
    },
)


# ================================================================
# EVENT SCHEDULE
# ================================================================

st.markdown(
    '<div class="section-title">Event schedule</div>',
    unsafe_allow_html=True,
)

display_df = (
    filtered[
        [
            "start",
            "name",
            "category",
            "event_type",
            "venue",
            "expected_people",
        ]
    ]
    .sort_values("start")
    .copy()
)

display_df["start"] = (
    display_df["start"]
    .dt.strftime("%d %b %Y · %H:%M")
)

display_df.columns = [
    "Date & time",
    "Event",
    "Category",
    "Type",
    "Venue",
    "Expected people",
]

st.dataframe(
    display_df,
    width="stretch",
    hide_index=True,
)
