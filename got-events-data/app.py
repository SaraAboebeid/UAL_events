import calendar
from pathlib import Path

import folium
import pandas as pd
import plotly.express as px
import streamlit as st

from streamlit_folium import st_folium


# CONFIG

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
WEEKDAYS = list(calendar.day_name)

# Broad categories set in 1-etl_data.ipynb, in color-slot order
CATEGORY_ORDER = [
    "Concert",
    "Theatre & shows",
    "Sports",
    "Festival",
    "Exhibition",
    "Market",
    "Family",
    "Tours",
    "Food & drink",
    "Other",
]

# Colorblind-checked palette for the dark background (max 8 hues);
# the two smallest groups share a neutral grey
CATEGORY_COLORS = {
    "Concert": "#3987e5",
    "Theatre & shows": "#d95926",
    "Sports": "#199e70",
    "Festival": "#c98500",
    "Exhibition": "#d55181",
    "Market": "#008300",
    "Family": "#9085e9",
    "Tours": "#e66767",
    "Food & drink": "#898781",
    "Other": "#898781",
}


# PAGE CONFIG
st.set_page_config(
    page_title="Gothenburg Events",
    page_icon="🎟️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# CUSTOM CSS
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


# LOAD DATA (events.csv is written by 1-etl_data.ipynb)

HERE = Path(__file__).resolve().parent

DATA = next(
    (
        p / "events.csv"
        for p in [HERE, HERE / "got-events-data", *HERE.parents]
        if (p / "events.csv").exists()
    ),
    None,
)

if DATA is None:
    st.error(
        "events.csv not found. Run 1-etl_data.ipynb first, "
        f"so the file is saved in {HERE} or a folder above it."
    )
    st.stop()


@st.cache_data
def load(path, modified):
    data = pd.read_csv(path, parse_dates=["start", "end"])
    data["free"] = data["free"].fillna(False).astype(bool)
    return data


df = load(DATA, DATA.stat().st_mtime)

st.sidebar.caption(
    "Data: Göteborg & Co events API · "
    f"fetched {pd.Timestamp(DATA.stat().st_mtime, unit='s'):%d %b %Y %H:%M}"
)


# HEADER

st.title("Gothenburg Events")

st.markdown(
    """
    <div class="subtitle">
        Upcoming event activity, categories and venues across Gothenburg
    </div>
    """,
    unsafe_allow_html=True,
)


# SIDEBAR FILTERS

st.sidebar.markdown("## Filters")

# Past editions of yearly events are estimated in 1-etl_data.ipynb
show_estimated = st.sidebar.toggle(
    "Include estimated past editions",
    value=True,
    help=(
        "The API only keeps the next edition of yearly events (e.g. Way Out "
        "West 2027). Earlier editions are estimated by repeating the same "
        "dates each year since the listing was created."
    ),
)

if not show_estimated:
    df = df[df["source"] == "API"]

# Year
years = sorted(df["year"].unique())
this_year = pd.Timestamp.today().year

year = st.sidebar.selectbox(
    "Year",
    years,
    index=years.index(this_year) if this_year in years else len(years) - 1,
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
    "Event category",
    options=available_categories,
    default=available_categories,
)

filtered = filtered[
    filtered["category"].isin(selected_categories)
]

# Free events only (only some events are marked free in the API)
free_only = st.sidebar.toggle("Free events only")
if free_only:
    filtered = filtered[filtered["free"]]

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


# KPI CARDS

total_events = filtered["event_id"].nunique()
total_dates = len(filtered)
estimated_dates = int((filtered["source"] != "API").sum())
venue_count = filtered["venue"].nunique()
free_events = filtered.loc[filtered["free"], "event_id"].nunique()


def metric_card(label, value):
    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
    </div>
    """


cards = [
    ("EVENTS", total_events),
    ("EVENT DATES", total_dates),
    ("VENUES", venue_count),
    ("FREE EVENTS", free_events),
]

for column, (label, value) in zip(st.columns(4), cards):
    with column:
        st.markdown(
            metric_card(label, f"{value:,}"),
            unsafe_allow_html=True,
        )

if estimated_dates:
    st.caption(
        f"{estimated_dates:,} of {total_dates:,} event dates are estimated "
        "past editions of yearly events (see Source in the schedule)."
    )

st.markdown("")


# MAP

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

# One dot per venue, sized by number of event dates
spots = (
    filtered
    .groupby(
        ["venue", "lat", "lon"],
        as_index=False,
    )
    .agg(
        events=("event_id", "nunique"),
        dates=("event_id", "count"),
        # Dot color = the venue's most common category
        main_category=("category", lambda x: x.value_counts().index[0]),
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

    biggest = spots["dates"].max()

    # Small dots on top of big ones
    for _, s in spots.sort_values("dates", ascending=False).iterrows():

        venue = s["venue"]
        color = CATEGORY_COLORS.get(s["main_category"], MUTED)

        size = 5 + 25 * (s["dates"] / biggest) ** 0.5

        popup_html = f"""
        <div style="font-family:Arial; min-width:220px;">
            <h4 style="margin-bottom:8px;">{venue}</h4>
            <b>Events:</b> {int(s["events"]):,}<br>
            <b>Event dates:</b> {int(s["dates"]):,}<br>
            <b>Main category:</b> {s["main_category"]}<br>
            <b>All categories:</b><br>
            {category_summary.get(venue, "—")}
        </div>
        """

        folium.CircleMarker(
            location=[s["lat"], s["lon"]],
            radius=size,
            color=color,
            weight=1.5,
            opacity=1,
            fill=True,
            fill_color=color,
            fill_opacity=0.35,
            tooltip=(
                f"<b>{venue}</b><br>"
                f"{s['main_category']} · "
                f"{int(s['events']):,} events · "
                f"{int(s['dates']):,} dates"
            ),
            popup=folium.Popup(
                popup_html,
                max_width=300,
            ),
        ).add_to(m)

# Legend for the categories currently on the map
legend = "".join(
    f'<span style="margin-right:16px; white-space:nowrap;">'
    f'<span style="display:inline-block; width:10px; height:10px; '
    f'border-radius:50%; background:{CATEGORY_COLORS[c]}; '
    f'margin-right:6px;"></span>{c}</span>'
    for c in CATEGORY_ORDER
    if c in set(spots["main_category"])
)

st.markdown(
    f'<div style="color:{MUTED}; font-size:0.85rem; margin-bottom:8px;">'
    f'Dot colour = venue\'s main category · size = number of event dates'
    f'<br>{legend}</div>',
    unsafe_allow_html=True,
)

st_folium(
    m,
    height=560,
    use_container_width=True,
    returned_objects=[],
)


# CHART STYLE

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


# ANALYTICS

st.markdown(
    '<div class="section-title">Event analytics</div>',
    unsafe_allow_html=True,
)

tab1, tab2, tab3 = st.tabs(
    [
        "Event volume",
        "Weekdays",
        "Event categories",
    ]
)

# TAB 1: the whole upcoming calendar by month, stacked by category.
# Ignores the year/month/day filters (it is the timeline itself) but
# follows the category, free and venue filters.
with tab1:

    timeline = df[df["category"].isin(selected_categories)]
    if selected_venues:
        timeline = timeline[timeline["venue"].isin(selected_venues)]
    if free_only:
        timeline = timeline[timeline["free"]]

    per_month = (
        timeline
        .assign(month_start=timeline["start"].dt.to_period("M").dt.to_timestamp())
        .groupby(["month_start", "category"])
        .size()
        .reset_index(name="dates")
    )

    fig = px.bar(
        per_month,
        x="month_start",
        y="dates",
        color="category",
        category_orders={"category": CATEGORY_ORDER},
        color_discrete_map=CATEGORY_COLORS,
        title="Upcoming event dates per month, by category",
        labels={
            "month_start": "Month",
            "dates": "Event dates",
            "category": "Category",
        },
    )

    fig.update_traces(
        marker_line_color=DARK,
        marker_line_width=1,
        hovertemplate="%{x|%b %Y}<br>%{fullData.name}: %{y}<extra></extra>",
    )
    fig.update_xaxes(dtick="M1", tickformat="%b\n%Y")
    fig.update_layout(
        bargap=0.25,
        legend=dict(title=None, orientation="h", y=-0.25),
    )

    st.plotly_chart(
        style(fig).update_layout(height=420),
        width="stretch",
    )

    st.caption(
        "Before today the API only keeps events that are still listed "
        "(mostly the start dates of ongoing seasons and series); finished "
        "events are removed. Months far ahead look smaller because "
        "organisers publish closer to the date, not because fewer events "
        "happen."
    )

# TAB 2: event dates per weekday, follows the filters
with tab2:

    per_weekday = (
        filtered
        .groupby("weekday")
        .size()
        .reindex(
            WEEKDAYS,
            fill_value=0,
        )
        .reset_index(name="dates")
    )

    fig = px.bar(
        per_weekday,
        x="weekday",
        y="dates",
        title="Event dates by weekday",
        labels={
            "weekday": "Weekday",
            "dates": "Event dates",
        },
        color_discrete_sequence=[YELLOW],
    )

    st.plotly_chart(
        style(fig),
        width="stretch",
    )

# TAB 3: events by category, follows the filters
with tab3:

    category_counts = (
        filtered
        .groupby("category")["event_id"]
        .nunique()
        .reindex(
            available_categories,
            fill_value=0,
        )
        .reset_index(name="events")
    )

    fig = px.bar(
        category_counts,
        x="category",
        y="events",
        color="category",
        color_discrete_map=CATEGORY_COLORS,
        title="Events by category",
        labels={
            "category": "Category",
            "events": "Events",
        },
    )
    fig.update_layout(showlegend=False)

    st.plotly_chart(
        style(fig),
        width="stretch",
    )


# CATEGORY OVERVIEW

st.markdown(
    '<div class="section-title">Category overview</div>',
    unsafe_allow_html=True,
)

category_summary_df = (
    filtered
    .groupby("category")
    .agg(
        events=("event_id", "nunique"),
        dates=("event_id", "count"),
        venues=("venue", "nunique"),
        free_events=("free", "sum"),
    )
    .reindex(CATEGORY_ORDER)
    .dropna(how="all")
    .astype(int)
    .reset_index()
)

st.dataframe(
    category_summary_df,
    width="stretch",
    hide_index=True,
    column_config={
        "category": "Category",
        "events": "Events",
        "dates": "Event dates",
        "venues": "Venues",
        "free_events": "Free event dates",
    },
)


# EVENT SCHEDULE

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
            "free",
            "source",
            "link",
        ]
    ]
    .sort_values("start")
    .copy()
)

display_df["start"] = (
    display_df["start"]
    .dt.strftime("%d %b %Y · %H:%M")
)

st.dataframe(
    display_df,
    width="stretch",
    hide_index=True,
    column_config={
        "start": "Date & time",
        "name": "Event",
        "category": "Category",
        "event_type": "Type",
        "venue": "Venue",
        "free": st.column_config.CheckboxColumn("Free"),
        "source": "Source",
        "link": st.column_config.LinkColumn(
            "More info",
            display_text="goteborg.com",
        ),
    },
)
