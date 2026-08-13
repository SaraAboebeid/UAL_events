-- Jorge Gil, 2025
-- process mobile traces data to create stops

-------------------------------------
-- create stops table
--------------------------------------
-- identify stop locations (isolated and complete) and calculate duration based on series sequence and duration
-- assumptions: combine stops that are not more than 1 hour apart, stops have at least 10 minutes if no stay is present,
CREATE INDEX IF NOT EXISTS point_types_2024_device_uuid_idx ON processed.point_types_2024 (device_uid, series);

DROP TABLE IF EXISTS processed.stops_2024 CASCADE;
CREATE TABLE processed.stops_2024
(
    sid          SERIAL PRIMARY KEY,
    geom         GEOMETRY('Point', 4326),
    device_uid   UUID,                     -- unique device/user id
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
INSERT INTO processed.stops_2024 (geom, device_uid, arrive_id, arrive_time, arrive_type, depart_id, depart_time, depart_type, data_points)
    SELECT coalesce(ST_Centroid(ST_Collect(CASE WHEN type IN ('start','stop','slow start','slow stop','stay','isolated') THEN geom END)), ST_Centroid(ST_Collect(geom))) AS geom,
           device_uid, min(series) AS arrive_id, min(timestamp_se) AS arrive_time, min(arrive_type) AS arrive_type,
           max(series) AS depart_id, max(timestamp_se) AS depart_time, max(depart_type) AS depart_type, count(*) AS data_points
    FROM (
        SELECT device_uid, series, geom, timestamp_se, sum(rst) OVER (ORDER BY device_uid, series) AS grp, arrive_type, depart_type, type
        FROM (
             SELECT device_uid, series, geom, timestamp_se,
                    CASE WHEN coalesce(lag(series) OVER (PARTITION BY device_uid ORDER BY series), series) + 1 <> series
                            OR EXTRACT(epoch FROM age(timestamp_se, lag(timestamp_se) OVER (PARTITION BY device_uid ORDER BY series))) > 3600 -- account for temporal breaks
                            OR type IN ('stop','slow stop') -- account for spatial breaks
                            OR (type = 'slow down' AND out_duration > 600) -- account for missing stay data
                        THEN 1 END rst,
                    CASE WHEN coalesce(lag(series) OVER (PARTITION BY device_uid ORDER BY series), series) + 1 <> series
                            OR EXTRACT(epoch FROM age(timestamp_se, lag(timestamp_se) OVER (PARTITION BY device_uid ORDER BY series))) > 3600
                            OR type IN ('stop','slow stop')
                            OR (type = 'slow down' AND out_duration > 600) -- account for missing stay data
                        THEN type END arrive_type,
                    CASE WHEN coalesce(lead(series) OVER (PARTITION BY device_uid ORDER BY series), series) <> series + 1
                            OR EXTRACT(epoch FROM age(lead(timestamp_se) OVER (PARTITION BY device_uid ORDER BY series),timestamp_se)) > 3600
                            OR type IN ('start','slow start')
                            OR (type = 'speed up' AND in_duration > 600) -- account for missing stay data
                        THEN type END depart_type, type
             FROM processed.point_types_2024
             WHERE type IN ('start','stop','slow start','slow stop','stay','slow down','speed up','isolated')
             --AND is_stationary IS FALSE
           ) t1
        ) t2
    GROUP BY grp, device_uid
    ORDER BY device_uid, grp
;
UPDATE processed.stops_2024 SET
    x = ST_X(geom),
    y = ST_Y(geom)
;
UPDATE processed.stops_2024 SET
    duration = EXTRACT(epoch FROM age(depart_time, arrive_time))
WHERE data_points > 1 --arrive_type IN ('stop','stay') AND depart_type IN ('start','stay')
;

DROP INDEX IF EXISTS processed.point_types_2024_device_uuid_idx;

-- DROP INDEX IF EXISTS processed_stops_2024_geom_idx
CREATE INDEX processed_stops_2024_geom_idx ON processed.stops_2024 USING GIST(geom);
