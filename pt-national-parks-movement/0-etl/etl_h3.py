import os
import time

import geopandas as gpd
import h3
import pandas as pd
from dotenv import load_dotenv
from shapely.geometry import Polygon
from sqlalchemy import create_engine, text


load_dotenv()

print("Libraries imported!")


# ---------- CONFIG ----------

# Prefer defining this in your .env file:
# DATABASE_URL=postgresql://user:password@host/database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://ual:@cirrus.ita.chalmers.se/ual_prototyping",
)

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set.")

BOUNDARIES_SCHEMA = "boundaries"
BOUNDARIES_TABLE = "swe_national_parks_bbox"
BOUNDARIES_GEOM_COL = "geom"

# Set this to an existing column such as "city_name" when available.
# Leave as None to generate area names from the row index.
AREA_NAME_COL = None

OUTPUT_SCHEMA = "boundaries"
OUTPUT_TABLE = "h3_national_parks_h3"

CRS = "EPSG:4326"

# H3 supports resolutions from 0 to 15.
MIN_H3_RESOLUTION = 10
MAX_H3_RESOLUTION = 12

# True:
# Retain only hexagons whose centres fall within the boundary.
#
# False:
# Also retain neighbouring hexagons that intersect the boundary.
INCLUDE_INTERSECTING_HEXAGONS = True

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

print("Database engine created!")


# ---------- EXTRACT ----------

def load_boundaries():
    """Load the H3 generation boundaries from PostGIS."""
    query = f"""
        SELECT *
        FROM "{BOUNDARIES_SCHEMA}"."{BOUNDARIES_TABLE}"
        WHERE "{BOUNDARIES_GEOM_COL}" IS NOT NULL
    """

    boundaries = gpd.read_postgis(
        query,
        con=engine,
        geom_col=BOUNDARIES_GEOM_COL,
    )

    if boundaries.empty:
        raise ValueError(
            f"No boundaries found in "
            f"{BOUNDARIES_SCHEMA}.{BOUNDARIES_TABLE}."
        )

    if boundaries.crs is None:
        raise ValueError(
            f"{BOUNDARIES_SCHEMA}.{BOUNDARIES_TABLE} has no CRS."
        )

    boundaries = boundaries.to_crs(CRS)

    boundaries = boundaries[
        boundaries.geometry.notna()
        & ~boundaries.geometry.is_empty
    ].copy()

    if boundaries.empty:
        raise ValueError(
            "No valid boundary geometries were found."
        )

    print(f"Loaded {len(boundaries)} boundaries.")

    return boundaries


def get_area_name(boundary, boundary_index):
    """Return a readable identifier for a boundary."""
    if AREA_NAME_COL and AREA_NAME_COL in boundary.index:
        value = boundary[AREA_NAME_COL]

        if pd.notna(value):
            return str(value)

    return f"area_{boundary_index}"


# ---------- TRANSFORM ----------

def validate_h3_resolutions():
    """Validate the configured H3 resolution range."""
    if not 0 <= MIN_H3_RESOLUTION <= 15:
        raise ValueError(
            "MIN_H3_RESOLUTION must be between 0 and 15."
        )

    if not 0 <= MAX_H3_RESOLUTION <= 15:
        raise ValueError(
            "MAX_H3_RESOLUTION must be between 0 and 15."
        )

    if MIN_H3_RESOLUTION > MAX_H3_RESOLUTION:
        raise ValueError(
            "MIN_H3_RESOLUTION cannot be greater than "
            "MAX_H3_RESOLUTION."
        )


def geometry_to_h3_shape(geometry):
    """Convert a Shapely geometry into an H3 shape."""
    return h3.geo_to_h3shape(
        geometry.__geo_interface__
    )


def get_boundary_h3_cells(geometry, resolution):
    """Return the H3 cells covering a boundary."""
    h3_shape = geometry_to_h3_shape(geometry)

    if INCLUDE_INTERSECTING_HEXAGONS:
        cells = h3.h3shape_to_cells_experimental(
            h3_shape,
            res=resolution,
            contain="overlap",
        )
    else:
        cells = h3.h3shape_to_cells(
            h3_shape,
            res=resolution,
        )

    return sorted(cells)


def h3_cell_to_polygon(h3_index):
    """Convert an H3 cell into a Shapely polygon."""
    boundary = h3.cell_to_boundary(h3_index)

    # H3 returns coordinates as latitude and longitude.
    # Shapely expects longitude and latitude.
    coordinates = [
        (longitude, latitude)
        for latitude, longitude in boundary
    ]

    return Polygon(coordinates)


def generate_h3_hexagons(boundaries):
    """Generate H3 polygons for all configured resolutions."""
    validate_h3_resolutions()

    results = []

    resolutions = range(
        MIN_H3_RESOLUTION,
        MAX_H3_RESOLUTION + 1,
    )

    for boundary_index, boundary in boundaries.iterrows():
        area_name = get_area_name(
            boundary=boundary,
            boundary_index=boundary_index,
        )

        area_geom = boundary[BOUNDARIES_GEOM_COL]

        print(f"Generating H3 hexagons for {area_name}...")

        for resolution in resolutions:
            try:
                h3_cells = get_boundary_h3_cells(
                    geometry=area_geom,
                    resolution=resolution,
                )

                if not h3_cells:
                    print(
                        f"No H3 cells found for {area_name} "
                        f"at resolution {resolution}."
                    )
                    continue

                records = [
                    {
                        "area_name": area_name,
                        "h3_resolution": resolution,
                        "h3_index": h3_index,
                        "geom": h3_cell_to_polygon(h3_index),
                    }
                    for h3_index in h3_cells
                ]

                resolution_gdf = gpd.GeoDataFrame(
                    records,
                    geometry="geom",
                    crs=CRS,
                )

                results.append(resolution_gdf)

                print(
                    f"Generated {len(resolution_gdf):,} "
                    f"H3 hexagons for {area_name} "
                    f"at resolution {resolution}."
                )

            except Exception as error:
                print(
                    f"Skipped {area_name} at resolution "
                    f"{resolution}: "
                    f"{type(error).__name__}: {error}"
                )

    if not results:
        return None

    result = gpd.GeoDataFrame(
        pd.concat(
            results,
            ignore_index=True,
        ),
        geometry="geom",
        crs=CRS,
    )

    result = result.drop_duplicates(
        subset=[
            "area_name",
            "h3_resolution",
            "h3_index",
        ]
    ).reset_index(drop=True)

    print(
        f"Final H3 features: {len(result):,}"
    )

    return result


# ---------- LOAD ----------

def ensure_output_schema():
    """Create the output schema when it does not exist."""
    with engine.begin() as connection:
        connection.execute(
            text(
                f'CREATE SCHEMA IF NOT EXISTS '
                f'"{OUTPUT_SCHEMA}"'
            )
        )


def export_resolution_tables(gdf):
    """Export each H3 resolution to a separate PostGIS table."""
    if gdf is None or gdf.empty:
        print(
            f"Nothing to export to schema "
            f"{OUTPUT_SCHEMA}."
        )
        return

    resolutions = sorted(
        gdf["h3_resolution"].unique()
    )

    for resolution in resolutions:
        table_name = (
            f"{OUTPUT_TABLE}_res_{resolution}"
        )

        resolution_gdf = gdf[
            gdf["h3_resolution"] == resolution
        ].copy()

        resolution_gdf.to_postgis(
            name=table_name,
            con=engine,
            schema=OUTPUT_SCHEMA,
            if_exists="replace",
            index=False,
            chunksize=5_000,
        )

        create_output_indexes(
            table_name=table_name,
        )

        print(
            f"Exported {len(resolution_gdf):,} features "
            f"to {OUTPUT_SCHEMA}.{table_name}"
        )


def create_output_indexes(table_name):
    """Create attribute and spatial indexes on an H3 table."""
    statements = [
        f"""
            CREATE UNIQUE INDEX IF NOT EXISTS
            "{table_name}_h3_index_idx"
            ON "{OUTPUT_SCHEMA}"."{table_name}"
            ("h3_index")
        """,
        f"""
            CREATE INDEX IF NOT EXISTS
            "{table_name}_area_name_idx"
            ON "{OUTPUT_SCHEMA}"."{table_name}"
            ("area_name")
        """,
        f"""
            CREATE INDEX IF NOT EXISTS
            "{table_name}_geom_idx"
            ON "{OUTPUT_SCHEMA}"."{table_name}"
            USING GIST ("geom")
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(
                text(statement)
            )

    print(
        f"Indexes created for "
        f"{OUTPUT_SCHEMA}.{table_name}."
    )


# ---------- RUN PIPELINE ----------

def run():
    start = time.perf_counter()

    ensure_output_schema()

    boundaries = load_boundaries()

    h3_gdf = generate_h3_hexagons(
        boundaries=boundaries,
    )

    export_resolution_tables(
        gdf=h3_gdf,
    )

    elapsed = time.perf_counter() - start
    print(f"\nAll done! Time: {elapsed:.2f}s")


if __name__ == "__main__":
    try:
        run()
    finally:
        engine.dispose()


# ---------- RUN PIPELINE ----------

def run():
    start = time.perf_counter()

    ensure_output_schema()

    boundaries = load_boundaries()

    h3_gdf = generate_h3_hexagons(
        boundaries=boundaries,
    )

    export_to_postgis(
        gdf=h3_gdf,
        table_name=OUTPUT_TABLE,
    )

    if h3_gdf is not None and not h3_gdf.empty:
        create_output_indexes()

    elapsed = time.perf_counter() - start
    print(f"\nAll done! Time: {elapsed:.2f}s")


if __name__ == "__main__":
    try:
        run()
    finally:
        engine.dispose()