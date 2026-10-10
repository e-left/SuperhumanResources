-- Prisma ordinary writes omit this unsupported field. Coordinates are coarse demo areas.
ALTER TABLE "Profile" ADD COLUMN "location" geography(Point,4326);
CREATE INDEX "Profile_location_gist" ON "Profile" USING GIST ("location");
