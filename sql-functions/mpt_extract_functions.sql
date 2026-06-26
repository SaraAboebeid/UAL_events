
-- Extract mobile data based on a boundary, getting complete device ID trajectories
-- DROP FUNCTION extracts.create_clipped_mpt_extract;
CREATE OR REPLACE FUNCTION extracts.create_clipped_mpt_extract(
    p_result_table       text,
    p_input_table        text,
    p_boundary_table     text,
    p_clip_column        text,
    p_clip_value         text,
    p_result_schema      text DEFAULT 'extracts',
    p_input_schema       text DEFAULT 'raw_data',
    p_boundary_schema    text DEFAULT 'boundaries',
    p_time_zone          text DEFAULT 'CET',
    p_clip_geom_column   text DEFAULT 'geom'
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_sql        text;
    v_rows       bigint;
    v_index_name text;
BEGIN
    /*
      Build index name.
      PostgreSQL identifiers are limited to 63 bytes, so keep it short.
    */
    v_index_name := left(p_result_table || '_geom_sidx', 63);

    -- Make sure the output schema exists
    EXECUTE format(
        'CREATE SCHEMA IF NOT EXISTS %I',
        p_result_schema
    );

    -- Create result table
    EXECUTE format(
        'DROP TABLE IF EXISTS %I.%I',
        p_result_schema,
        p_result_table
    );
    EXECUTE format(
        'CREATE TABLE %I.%I
         (
             sid SERIAL NOT NULL,
             geom geometry(Point, 4326),
             device_uid uuid,
             timestamp_se timestamp with time zone,
             longitude double precision,
             latitude double precision,
             accuracy numeric(6,1),
             method character varying(5)
         )',
        p_result_schema,
        p_result_table
    );

    /*
      Insert clipped records.
      - identify devices that have at least one point whose bounding box overlaps
        the selected clip geometry;
      - then insert all rows belonging to those devices.
    */
    v_sql := format(
        'INSERT INTO %I.%I
             (geom, device_uid, timestamp_se, longitude, latitude, accuracy, method)
         SELECT
             ST_Point(src.longitude, src.latitude, 4326),
             src.device_aid::uuid,
             to_timestamp(src."timestamp") AT TIME ZONE $1,
             src.longitude,
             src.latitude,
             src.horizontal_accuracy,
             src.location_method
         FROM %I.%I AS src
         WHERE src.device_aid IN
         (
             SELECT DISTINCT a.device_aid
             FROM
             (
                 SELECT
                     device_aid,
                     ST_Point(longitude, latitude, 4326) AS geom
                 FROM %I.%I
             ) AS a,
             (
                 SELECT ST_Transform(%I, 4326) AS geom
                 FROM %I.%I
                 WHERE %I = $2
             ) AS b
             WHERE a.geom && b.geom
         )',
        p_result_schema,
        p_result_table,
        p_input_schema,
        p_input_table,
        p_input_schema,
        p_input_table,
        p_clip_geom_column,
        p_boundary_schema,
        p_boundary_table,
        p_clip_column
    );

    EXECUTE v_sql USING p_time_zone, p_clip_value;

    GET DIAGNOSTICS v_rows = ROW_COUNT;

    -- Create spatial index.
    EXECUTE format(
        'CREATE INDEX %I ON %I.%I USING GIST (geom)',
        v_index_name,
        p_result_schema,
        p_result_table
    );

    RETURN v_rows;
END;
$$;

-- Test function
-- create small sample table
CREATE TABLE raw_data.data_sample_small AS
    SELECT device_uid as device_aid, timestamp_se as timestamp, x as longitude, y as latitude,
           accuracy as horizontal_accuracy, method as location_method FROM extracts.data_sample_extended_area LIMIT 100000;
-- update  raw_data.data_sample_small set timestamp = EXTRACT(EPOCH FROM timestamp_se)::bigint;

-- test clip
SELECT extracts.create_clipped_mpt_extract('ldhm_kultvis_test',
    'data_sample_small','kommun_swe_region',
    'knnamn','Göteborg',
    p_result_schema := 'extracts')
;


-- Extract mobile data based on a geographic boundary only
