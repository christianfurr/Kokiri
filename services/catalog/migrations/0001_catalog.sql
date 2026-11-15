CREATE TABLE contexts(context_id TEXT PRIMARY KEY CHECK(length(context_id)=64), context_json TEXT NOT NULL CHECK(length(context_json)<=2048));
CREATE TABLE inbox(context_id TEXT NOT NULL REFERENCES contexts(context_id), record_id TEXT NOT NULL CHECK(length(record_id)=64), kind TEXT NOT NULL, row TEXT NOT NULL CHECK(length(row)<=4096), PRIMARY KEY(context_id,record_id)) WITHOUT ROWID;
CREATE TABLE packs(sha256 TEXT PRIMARY KEY CHECK(length(sha256)=64), body TEXT NOT NULL CHECK(length(body)<=262144));
CREATE TABLE manifests(context_id TEXT PRIMARY KEY REFERENCES contexts(context_id), envelope TEXT NOT NULL CHECK(length(envelope)<=262144));
-- Constant-time counters are maintained in the same transaction as inserts and
-- deletes. Duplicate INSERT OR IGNORE never fires AFTER INSERT accounting.
CREATE TABLE catalog_limits(singleton INTEGER PRIMARY KEY CHECK(singleton=1), contexts INTEGER NOT NULL, records INTEGER NOT NULL, per_context INTEGER NOT NULL);
INSERT INTO catalog_limits VALUES(1,256,200000,100000);
CREATE TABLE catalog_usage(singleton INTEGER PRIMARY KEY CHECK(singleton=1), contexts INTEGER NOT NULL CHECK(contexts>=0), records INTEGER NOT NULL CHECK(records>=0));
INSERT INTO catalog_usage VALUES(1,0,0);
CREATE TABLE context_usage(context_id TEXT PRIMARY KEY REFERENCES contexts(context_id) ON DELETE CASCADE, records INTEGER NOT NULL CHECK(records>=0));
CREATE TRIGGER contexts_capacity BEFORE INSERT ON contexts WHEN NOT EXISTS(SELECT 1 FROM contexts WHERE context_id=NEW.context_id) AND (SELECT contexts FROM catalog_usage WHERE singleton=1)>=(SELECT contexts FROM catalog_limits WHERE singleton=1) BEGIN SELECT RAISE(ABORT,'context capacity'); END;
CREATE TRIGGER contexts_added AFTER INSERT ON contexts BEGIN UPDATE catalog_usage SET contexts=contexts+1 WHERE singleton=1; INSERT INTO context_usage VALUES(NEW.context_id,0); END;
CREATE TRIGGER contexts_removed AFTER DELETE ON contexts BEGIN UPDATE catalog_usage SET contexts=contexts-1 WHERE singleton=1; END;
CREATE TRIGGER inbox_capacity BEFORE INSERT ON inbox WHEN NOT EXISTS(SELECT 1 FROM inbox WHERE context_id=NEW.context_id AND record_id=NEW.record_id) AND ((SELECT records FROM catalog_usage WHERE singleton=1)>=(SELECT records FROM catalog_limits WHERE singleton=1) OR (SELECT records FROM context_usage WHERE context_id=NEW.context_id)>=(SELECT per_context FROM catalog_limits WHERE singleton=1)) BEGIN SELECT RAISE(ABORT,'inbox capacity'); END;
CREATE TRIGGER inbox_added AFTER INSERT ON inbox BEGIN UPDATE catalog_usage SET records=records+1 WHERE singleton=1; UPDATE context_usage SET records=records+1 WHERE context_id=NEW.context_id; END;
CREATE TRIGGER inbox_removed AFTER DELETE ON inbox BEGIN UPDATE catalog_usage SET records=records-1 WHERE singleton=1; UPDATE context_usage SET records=records-1 WHERE context_id=OLD.context_id; END;
