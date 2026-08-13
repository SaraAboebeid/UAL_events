-- Jorge Gil, 2025
-- process mobile traces data to create trajectories

-------------------------------------
-- create trajectories table
--------------------------------------
-- Create real paths, combining movement points to start/end of stops/stays. It builds on the assumptions of the stops, getting the opposite: movement instead of stays.
-- count points, distance, duration, average speed
-- a simpler approach would be to connect all the points from a single user

DROP TABLE IF EXISTS processed.trajectories_2024 CASCADE;
CREATE TABLE processed.trajectories_2024
(
    sid          SERIAL PRIMARY KEY,
    geom         GEOMETRY('Linestring', 4326),
    device_uid   UUID,                     -- unique device/user id
    start_id    BIGINT,                --REFERENCES point_types
    start_time  TIMESTAMP WITH TIME ZONE, -- timestamp with Swedish time zone
    start_type VARCHAR,                    -- point_type
    stop_id   BIGINT,                    --REFERENCES point_types
    stop_time  TIMESTAMP WITH TIME ZONE, -- timestamp with Swedish time zone
    stop_type VARCHAR,                    -- point_type
    duration    BIGINT,                   -- seconds
    data_points SMALLINT,                    -- number of points per activity
    distance BIGINT,                         -- in meters
    speed DOUBLE PRECISION                -- in km/h
);
INSERT INTO processed.trajectories_2024 (geom, device_uid, start_id, start_time, start_type, stop_id, stop_time, stop_type, duration, data_points)
    SELECT ST_MakeLine(geom ORDER BY timestamp_se) AS geom,
           device_uid, min(series) AS start_id, min(timestamp_se) AS start_time, min(start_type) AS start_type,
           max(series) AS stop_id, max(timestamp_se) AS stop_time, max(stop_type) AS stop_type, EXTRACT(epoch FROM age(max(timestamp_se), min(timestamp_se))) AS duration, count(*) AS data_points
    FROM (
        SELECT device_uid, series, geom, timestamp_se, sum(rst) OVER (ORDER BY device_uid, series) AS grp, start_type, stop_type, type
        FROM (
             SELECT device_uid, series, geom, timestamp_se,
                    CASE WHEN coalesce(lag(series) OVER (PARTITION BY device_uid ORDER BY series), series) + 1 <> series
                            OR EXTRACT(epoch FROM age(timestamp_se, lag(timestamp_se) OVER (PARTITION BY device_uid ORDER BY series))) > 3600 -- account for temporal breaks
                           OR type IN ('start','slow start') -- account for spatial breaks
                           OR (type = 'speed up' AND in_duration > 600) -- account for missing movement
                            OR in_distance > 1000 -- account for missing movement
                        THEN 1 END rst,
                    CASE WHEN coalesce(lag(series) OVER (PARTITION BY device_uid ORDER BY series), series) + 1 <> series
                           OR EXTRACT(epoch FROM age(timestamp_se, lag(timestamp_se) OVER (PARTITION BY device_uid ORDER BY series))) > 3600
                           OR type IN ('start','slow start')
                            OR (type = 'speed up' AND in_duration > 600) -- account for missing movement
                        OR in_distance > 1000 -- account for missing movement
                        THEN type END start_type,
                    CASE WHEN coalesce(lead(series) OVER (PARTITION BY device_uid ORDER BY series), series) <> series + 1
                            OR EXTRACT(epoch FROM age(lead(timestamp_se) OVER (PARTITION BY device_uid ORDER BY series),timestamp_se)) > 3600
                           OR type IN ('stop','slow stop')
                           OR (type = 'slow down' AND out_duration > 600) -- account for missing stay data
                            OR out_distance > 1000 -- account for missing movement
                        THEN type END stop_type, type
             FROM processed.point_types_2024
             WHERE type IN ('start','stop','slow start','slow stop','slow down','speed up','movement')
            AND is_stationary IS NULL
           ) t1
        ) t2
    GROUP BY grp, device_uid
    ORDER BY device_uid, grp
;
UPDATE processed.trajectories_2024 SET distance = ST_Length(geom)::BIGINT;
UPDATE processed.trajectories_2024 SET speed = (distance/1000::NUMERIC)/(duration/3600::NUMERIC) WHERE duration > 0 AND duration IS NOT NULL;
