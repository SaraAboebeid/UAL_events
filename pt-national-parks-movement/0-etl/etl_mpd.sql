- Jorge Gil, 2025
-- process mobile traces data to create data point types for classification


-- THIS WAS ADAPTED TO RUN FROM preprocessed data and not from the original raw data
-- FOR THE CODE TO PROCESS ORIGINAL RAW DATA REFER TO THE RAW_SAMPLE CODE


-- The fastest way of doing it does not involve any updates but consumes a lot of memory/disk for larger data sets.
-- Splitting by month, or even week is not desirable but necessary. But also reintroducing updates after the first classification.
-- Importantly, these additional attributes are not essential (especially is_grid) or can be calculated for local samples later.
-- Probably can even be made faster with some clever tricks...

CREATE INDEX swe_national_parks_movement_data_2023_aid_idx ON raw_data.swe_national_parks_movement_data_2023 (device_aid) INCLUDE (timestamp);

DROP TABLE IF EXISTS processed.swe_national_parks_movement_point_types_2023 CASCADE;
CREATE TABLE processed.swe_national_parks_movement_point_types_2023
(
    sid          BIGSERIAL PRIMARY KEY,
    geom         GEOMETRY('Point', 4326),
    device_aid   UUID,                     -- unique device/user id
    timestamp    TIMESTAMP WITH TIME ZONE, -- timestamp with Swedish time zone
    x            FLOAT,                  -- WGS 84 coordinates
    y            FLOAT,                  -- WGS 84 coordinates
    accuracy     NUMERIC(6, 1),            -- (horizontal) metres
    method       VARCHAR(5),               -- label for location method (gps, wifi, fused,?)
    type         VARCHAR,                  -- data point class (custom TBD)
    in_duration  FLOAT,                  -- seconds
    in_distance  FLOAT,                  -- metres
    in_bearing   FLOAT,                   -- degrees
    in_speed     DOUBLE PRECISION,          -- km/h
    out_duration FLOAT,                  -- seconds
    out_distance FLOAT,                  -- metres
    out_bearing   FLOAT,                   -- degrees
    out_speed    DOUBLE PRECISION,          -- km/h
    series       INTEGER,                  -- sequence for each unique device
    is_last      BOOLEAN,                  -- last point in the series
    is_grid      BOOLEAN,                  -- likely to be in a grid pattern
    is_stationary BOOLEAN                   -- only location of device
);

WITH data_with_geom AS(
        SELECT geom, device_aid::uuid AS device_aid, to_timestamp (timestamp) AT TIME ZONE 'CET' as timestamp, horizontal_accuracy, location_method
        FROM  raw_data.swe_national_parks_movement_data_2023
    ),
     points_sequence AS (
        SELECT geom, device_aid, timestamp, ST_X(geom) AS x, ST_Y(geom) AS y,
               horizontal_accuracy AS accuracy, location_method AS method,
            EXTRACT(epoch FROM age(timestamp,lag(timestamp) OVER device_window)) AS in_duration,
            ST_DistanceSpheroid(geom,lag(geom) OVER device_window, 'SPHEROID["WGS 84",6378137,298.257223563]') AS in_distance,
            degrees(ST_Azimuth(geom,lag(geom) OVER device_window)) AS in_bearing,
            EXTRACT(epoch FROM age(lead(timestamp) OVER device_window, timestamp)) AS out_duration,
            ST_DistanceSpheroid(geom,lead(geom) OVER device_window, 'SPHEROID["WGS 84",6378137,298.257223563]') AS out_distance,
            degrees(ST_Azimuth(geom,lead(geom) OVER device_window)) AS out_bearing,
            row_number() OVER device_window AS series
        FROM data_with_geom
        WINDOW device_window AS (PARTITION BY device_aid ORDER BY timestamp)
),
     points_with_speed AS (
         SELECT *,
            (in_distance/1000.0)/NULLIF((in_duration/3600.0),0) AS in_speed,
            (out_distance/1000.0)/NULLIF((out_duration/3600.0),0) AS out_speed
         FROM points_sequence
)
INSERT INTO processed.swe_national_parks_movement_point_types_2023(geom, device_aid, timestamp, x, y, accuracy, method,
            in_duration, in_distance, in_bearing, out_duration, out_distance, out_bearing, series, in_speed, out_speed, type)
    SELECT geom, device_aid, timestamp, x, y, accuracy, method, in_duration, in_distance, in_bearing,
           out_duration, out_distance, out_bearing, series, in_speed, out_speed,
        CASE
            WHEN (in_speed > 250 AND out_speed > 250) THEN 'error'
            WHEN (in_speed IS NULL AND out_speed IS NULL) THEN 'singular'
            WHEN (in_speed > 3) AND (out_speed > 3) THEN 'movement'
            WHEN (in_speed > 3) AND ((out_speed <= 3 AND out_distance <= 100) OR out_speed IS NULL) THEN 'stop'
            WHEN ((in_speed <= 3 AND in_distance <= 100) OR in_speed IS NULL) AND (out_speed > 3) THEN 'start'
            WHEN ((in_speed <= 3 AND in_distance <= 100) OR in_speed IS NULL) AND ((out_speed <= 3 AND out_distance <= 100) OR out_speed IS NULL) THEN 'stay'
            WHEN ((in_speed <= 3 AND in_distance > 100) AND (out_speed <= 3 AND out_distance > 100)) THEN 'isolated'
            WHEN (in_speed <= 3 AND in_distance > 100) AND (out_speed > 3) THEN 'speed up'
            WHEN (in_speed > 3) AND (out_speed <= 3 AND out_distance > 100) THEN 'slow down'
            WHEN (in_speed <= 3 AND in_distance > 100) AND ((out_speed <= 3 AND out_distance <= 100) OR out_speed IS NULL) THEN 'slow stop'
            WHEN ((in_speed <= 3 AND in_distance <= 100) OR in_speed IS NULL) AND (out_speed <= 3 AND out_distance > 100) THEN 'slow start'
        END AS type
    FROM points_with_speed
;

-- This update is quite fast
UPDATE processed.swe_national_parks_movement_point_types_2023 SET
    is_last = TRUE
    WHERE out_speed IS NULL
;

UPDATE processed.swe_national_parks_movement_point_types_2023 SET
    is_stationary = TRUE
    WHERE device_aid IN (SELECT device_aid FROM (
            SELECT device_aid, count(DISTINCT geom) count
            FROM processed.swe_national_parks_movement_point_types_2023
            GROUP BY device_aid) AS a
            WHERE a.count = 1
        )
;

/*
-- This update is slower than the main classification.
UPDATE processed.point_types_2024 SET
    is_grid = TRUE
    WHERE geom IN (SELECT geom
        FROM (SELECT geom, count(*) points_count, count(DISTINCT device_uid) device_count
            FROM processed.point_types_2024
            GROUP BY geom) AS a
        WHERE a.points_count > 200 AND a.device_count > 5
        )
;
*/

-- add spatial index to geometries
CREATE INDEX swe_national_parks_movement_point_types_2023_uid_idx ON processed.swe_national_parks_movement_point_types_2023(device_aid);
CREATE INDEX swe_national_parks_movement_point_types_2023_geom_sidx ON processed.swe_national_parks_movement_point_types_2023 USING GIST (geom);


-- Jorge Gil, 2025
-- process mobile traces data to create stops
-- identify stop locations (isolated and complete) and calculate duration based on series sequence and duration
-- assumptions: combine stops that are not more than 1 hour apart, stops have at least 10 minutes if no stay is present,
CREATE INDEX IF NOT EXISTS swe_np_movement_point_types_2025_uuid_idx ON extracts.swe_national_parks_movement_data_2025 (device_aid, series);

DROP TABLE IF EXISTS extracts.swe_national_parks_movement_stops_2025 CASCADE;
CREATE TABLE extracts.swe_national_parks_movement_stops_2025
(
    sid          SERIAL PRIMARY KEY,
    geom         GEOMETRY('Point', 4326),
    device_aid   UUID,                     -- unique device/user id
    x            FLOAT,                  -- SWED projected coordinates
    y            FLOAT,                  -- SWED projected coordinates
    arrive_id    BIGINT,                --REFERENCES point_types
    arrive_time  TIMESTAMP WITH TIME ZONE, -- timestamp with Swedish time zone
    arrive_type VARCHAR,                    -- point_type
    depart_id   BIGINT,                    --REFERENCES point_types
    depart_time  TIMESTAMP WITH TIME ZONE, -- timestamp with Swedish time zone
    depart_type VARCHAR,                    -- point_type
    duration    BIGINT,                   -- seconds
    data_points BIGINT                    -- number of points per activity
);
INSERT INTO extracts.swe_national_parks_movement_stops_2025 (geom, device_aid, arrive_id, arrive_time, arrive_type, depart_id, depart_time, depart_type, data_points)
    SELECT coalesce(ST_Centroid(ST_Collect(CASE WHEN type IN ('start','stop','slow start','slow stop','stay','isolated') THEN geom END)), ST_Centroid(ST_Collect(geom))) AS geom,
           device_aid, min(series) AS arrive_id, min(timestamp_se) AS arrive_time, min(arrive_type) AS arrive_type,
           max(series) AS depart_id, max(timestamp_se) AS depart_time, max(depart_type) AS depart_type, count(*) AS data_points
    FROM (
        SELECT device_aid, series, geom, timestamp_se, sum(rst) OVER (ORDER BY device_aid, series) AS grp, arrive_type, depart_type, type
        FROM (
             SELECT device_aid, series, geom, timestamp_se,
                    CASE WHEN coalesce(lag(series) OVER (PARTITION BY device_aid ORDER BY series), series) + 1 <> series
                            OR EXTRACT(epoch FROM age(timestamp_se, lag(timestamp_se) OVER (PARTITION BY device_aid ORDER BY series))) > 3600 -- account for temporal breaks
                            OR type IN ('stop','slow stop') -- account for spatial breaks
                            OR (type = 'slow down' AND out_duration > 600) -- account for missing stay data
                        THEN 1 END rst,
                    CASE WHEN coalesce(lag(series) OVER (PARTITION BY device_aid ORDER BY series), series) + 1 <> series
                            OR EXTRACT(epoch FROM age(timestamp_se, lag(timestamp_se) OVER (PARTITION BY device_aid ORDER BY series))) > 3600
                            OR type IN ('stop','slow stop')
                            OR (type = 'slow down' AND out_duration > 600) -- account for missing stay data
                        THEN type END arrive_type,
                    CASE WHEN coalesce(lead(series) OVER (PARTITION BY device_aid ORDER BY series), series) <> series + 1
                            OR EXTRACT(epoch FROM age(lead(timestamp_se) OVER (PARTITION BY device_aid ORDER BY series),timestamp_se)) > 3600
                            OR type IN ('start','slow start')
                            OR (type = 'speed up' AND in_duration > 600) -- account for missing stay data
                        THEN type END depart_type, type
             FROM extracts.swe_national_parks_movement_data_2025
             WHERE type IN ('start','stop','slow start','slow stop','stay','slow down','speed up','isolated')
             --AND is_stationary IS FALSE
           ) t1
        ) t2
    GROUP BY grp, device_aid
    ORDER BY device_aid, grp
;
UPDATE extracts.swe_national_parks_movement_stops_2025  SET
    x = ST_X(geom),
    y = ST_Y(geom)
;
UPDATE extracts.swe_national_parks_movement_stops_2025 SET
    duration = EXTRACT(epoch FROM age(depart_time, arrive_time))
WHERE data_points > 1 --arrive_type IN ('stop','stay') AND depart_type IN ('start','stay')
;

DROP INDEX IF EXISTS extracts.swe_national_parks_movement_stops_2025_uuid_idx;

-- DROP INDEX IF EXISTS processed_stops_2024_geom_idx
CREATE INDEX swe_national_parks_movement_stops_2025_geom_idx ON extracts.swe_national_parks_movement_stops_2025 USING GIST(geom);


-- Filter stops
SET intervalstyle = 'postgres';

DROP TABLE IF EXISTS extracts.ldhm_kv_infostops_stops_2025_ext_area_15min;

CREATE TABLE extracts.ldhm_kv_infostops_stops_2025_extended_area_no_time_filter AS
SELECT
    device_uid,
    loc,
    MIN("timestamp") AS start_time,
    MAX("timestamp") AS end_time,
    MAX("timestamp") - MIN("timestamp") AS duration,
    ST_SetSRID(
        ST_Centroid(ST_Collect(geometry)),
        4326
    ) AS geometry
FROM extracts.ldhm_kv_infostops_stops_2025_ext_area
GROUP BY
    device_uid,
    loc
HAVING
    MAX("timestamp") - MIN("timestamp") > INTERVAL '0 minutes';

CREATE INDEX IF NOT EXISTS ldhm_kv_infostops_stops_2025_extended_area_no_time_filter_geom_sidx
ON extracts.ldhm_kv_infostops_stops_2025_ext_area_15min
USING GIST (geometry);

-- filtering 10 min
DROP TABLE IF EXISTS extracts.ldhm_kv_infostops_stops_2024_extended_area_10min;
CREATE TABLE extracts.ldhm_kv_infostops_stops_2024_extended_area_10min AS
SELECT *
FROM extracts.ldhm_kv_infostops_stops_2024_ext_area_15min
WHERE duration::interval > INTERVAL '10 minutes';

CREATE INDEX IF NOT EXISTS ldhm_kv_infostops_stops_2024_extended_area_10min_geom_sidx
ON extracts.ldhm_kv_infostops_stops_2024_extended_area_10min
USING GIST (geometry);


-- create spatial clip
DROP TABLE IF EXISTS extracts.swe_national_parks_movement_point_types_2024;

CREATE TABLE extracts.swe_national_parks_movement_point_types_2024 AS
SELECT
    d.*,
    b.namn
FROM processed.point_types_2024 AS d
JOIN boundaries.swe_national_parks_bbox AS b
  ON d.geom && b.geom
 AND ST_Intersects(d.geom, b.geom);

CREATE INDEX sswe_national_parks_movement_point_types_2024_gix
    ON extracts.swe_national_parks_movement_point_types_2024
    USING GIST (geom);

--create spatial clip raw_data
DROP TABLE IF EXISTS extracts.swe_national_parks_movement_data_2023;

CREATE TABLE extracts.swe_proto_movement_national_parks_2023 AS
points AS (
    SELECT
        c.*,
        ST_SetSRID(
            ST_MakePoint(c.longitude, c.latitude),
            4326
        )::geometry(Point, 4326) AS geom
    FROM candidates AS c
)
SELECT
    p.*,
    b.namn AS national_park_name
FROM points AS p
JOIN boundaries.swe_national_parks_bbox AS b
  ON b.geom && p.geom
 AND ST_Covers(b.geom, p.geom);

CREATE INDEX swe_proto_movement_np_2023_geometry_gix
    ON extracts.swe_national_parks_movement_data_2023
    USING GIST (geom);

-- change schema
ALTER TABLE extracts.swe_national_parks_movement_data_2023
SET SCHEMA raw_data;

