# ADR 001: Use PostGIS geography for discovery

Status: accepted for the demo.

Roommate discovery needs real distance filtering. PostgreSQL already stores profiles, so PostGIS avoids another service. Store WGS84 geography points; a GiST index supports `ST_DWithin` in meters. Prisma handles ordinary models; tagged parameterized SQL handles unsupported geography fields and the spatial index is defined in migrations.

Tradeoff: the demo needs a PostGIS-capable local database. Performance tuning and pagination await measured workloads.
