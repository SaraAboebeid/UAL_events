-- Jorge Gil, 2025
-- process mobile traces data to create data point types for classification


-- THIS WAS ADAPTED TO RUN FROM preprocessed data and not from the original raw data
-- FOR THE CODE TO PROCESS ORIGINAL RAW DATA REFER TO THE RAW_SAMPLE CODE


-- The fastest way of doing it does not involve any updates but consumes a lot of memory/disk for larger data sets.
-- Splitting by month, or even week is not desirable but necessary. But also reintroducing updates after the first classification.
-- Importantly, these additional attributes are not essential (especially is_grid) or can be calculated for local samples later.
-- Probably can even be made faster with some clever tricks...

CREATE INDEX data_2024_aid_idx ON raw_data.data_2024 (device_aid) INCLUDE (timestamp);

DROP TABLE IF EXISTS processed.point_types_2024 CASCADE;
CREATE TABLE processed.point_types_2024
(
    sid          BIGSERIAL PRIMARY KEY,
    geom         GEOMETRY('Point', 4326),
    device_uid   UUID,                     -- unique device/user id
    timestamp_se TIMESTAMP WITH TIME ZONE, -- timestamp with Swedish time zone
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
        SELECT ST_SetSRID(ST_Point(longitude, latitude), 4326) AS geom,
              device_aid, timestamp, horizontal_accuracy, location_method
        FROM  raw_data.data_2024
    ),
     points_sequence AS (
        SELECT geom, device_aid AS device_uid, timestamp AS timestamp_se, ST_X(geom) AS x, ST_Y(geom) AS y,
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
INSERT INTO processed.point_types_2024 (geom, device_uid, timestamp_se, x, y, accuracy, method,
            in_duration, in_distance, in_bearing, out_duration, out_distance, out_bearing, series, in_speed, out_speed, type)
    SELECT geom, device_uid, timestamp_se, x, y, accuracy, method, in_duration, in_distance, in_bearing,
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
UPDATE processed.point_types_2024 SET
    is_last = TRUE
    WHERE out_speed IS NULL
;

UPDATE processed.point_types_2024 SET
    is_stationary = TRUE
    WHERE device_uid IN (SELECT device_uid FROM (
            SELECT device_uid, count(DISTINCT geom) count
            FROM processed.point_types_2024
            GROUP BY device_uid) AS a
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
CREATE INDEX point_types_2024_uid_idx ON processed.point_types_2024 (device_uid);
CREATE INDEX point_types_2024_geom_sidx ON processed.point_types_2024 USING GIST (geom);

