CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE "Profile" (
  "id" uuid PRIMARY KEY, "name" text NOT NULL, "bio" text NOT NULL,
  "budgetMin" integer NOT NULL CHECK ("budgetMin" >= 0),
  "budgetMax" integer NOT NULL CHECK ("budgetMax" >= "budgetMin"),
  "area" text NOT NULL, "moveIn" date NOT NULL,
  "smoking" text NOT NULL CHECK ("smoking" IN ('no','yes','outside')),
  "pets" text NOT NULL CHECK ("pets" IN ('none','cat','dog','other')),
  "sleep" text NOT NULL CHECK ("sleep" IN ('early','regular','late')),
  "photoPath" text, "pushToken" text,
  "createdAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE "Swipe" (
  "actorId" uuid NOT NULL REFERENCES "Profile"("id"),
  "targetId" uuid NOT NULL REFERENCES "Profile"("id"),
  "decision" text NOT NULL CHECK ("decision" IN ('like','pass')),
  PRIMARY KEY ("actorId", "targetId"), CHECK ("actorId" <> "targetId")
);
CREATE TABLE "Match" (
  "id" uuid PRIMARY KEY, "lowId" uuid NOT NULL REFERENCES "Profile"("id"),
  "highId" uuid NOT NULL REFERENCES "Profile"("id"),
  "createdAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK ("lowId" < "highId")
);
CREATE UNIQUE INDEX "Match_lowId_highId_key" ON "Match"("lowId", "highId");
CREATE INDEX "Match_highId_idx" ON "Match"("highId");
CREATE TABLE "Block" (
  "actorId" uuid NOT NULL REFERENCES "Profile"("id"),
  "targetId" uuid NOT NULL REFERENCES "Profile"("id"),
  PRIMARY KEY ("actorId", "targetId"), CHECK ("actorId" <> "targetId")
);
CREATE INDEX "Block_targetId_idx" ON "Block"("targetId");
CREATE TABLE "Notification" (
  "id" uuid PRIMARY KEY, "matchId" uuid NOT NULL REFERENCES "Match"("id"),
  "recipientId" uuid NOT NULL REFERENCES "Profile"("id"),
  "status" text NOT NULL DEFAULT 'pending'
    CHECK ("status" IN ('pending','accepted','simulated','skipped','suppressed','failed')),
  "attempts" integer NOT NULL DEFAULT 0, "ticketId" text, "lastError" text,
  "createdAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX "Notification_matchId_recipientId_key" ON "Notification"("matchId", "recipientId");
CREATE INDEX "Notification_status_createdAt_idx" ON "Notification"("status", "createdAt");
CREATE TABLE "FixtureMessage" (
  "id" uuid PRIMARY KEY, "matchId" uuid NOT NULL REFERENCES "Match"("id"),
  "senderId" uuid NOT NULL REFERENCES "Profile"("id"), "text" text NOT NULL,
  "createdAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX "FixtureMessage_matchId_createdAt_idx" ON "FixtureMessage"("matchId", "createdAt");
