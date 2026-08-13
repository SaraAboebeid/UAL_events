# Running the pre-processing SQL code on the server

For this operation we need two terminal connections, one to the local machine to copy the code, another to the remote server to execute the code.

## start terminal and transfer the code
```bash
cd 01-etl
scp some_slow_sql_query.sql CID@cirrus.ita.chalmers.se:/database/files/source/some_slow_sql_query.sql
```

## execute the code
```bash
ssh CID@cirrus.ita.chalmers.se
cd /
cd database/files/source
rm nohup.out
nohup psql -d se_mobile_data -U mobiledata -f some_slow_sql_query.sql
```

## With timing to measure performance of the queries. This is permanently turned on in the psql configuration file individually.
```bash
nohup psql -d se_mobile_data -U mobiledata -c "\timing" -f some_slow_sql_query.sql
```

## Running a long query instead of a file
```bash
nohup psql -d se_mobile_data -U mobiledata -c "CREATE INDEX point_types_sample_geom_sidx ON processed.point_types_sample USING GIST (geom);"
```

## Checking the output timing and if it has completed
```bash
ssh CID@cirrus.ita.chalmers.se
cd /
cd database/files/source
cat nohup.out
```