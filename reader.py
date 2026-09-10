"""Core capture v1 -> passive, transactional local observations. No network I/O."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit, parse_qs

OPERATIONS = {'voyagerFeedDashUpdates', 'voyagerSocialDashReactions', 'voyagerSocialDashComments'}
KINDS = {'Update', 'Profile', 'Reaction', 'Comment', 'SocialDetail', 'SocialActivityCounts',
         'FollowingState', 'SocialPermissions', 'SaveState', 'UpdateActions'}
MAX_BODY = 16 * 1024 * 1024
SCHEMA = '''
CREATE TABLE IF NOT EXISTS observations(
 delivery TEXT PRIMARY KEY, record_id TEXT NOT NULL, observed_at REAL NOT NULL,
 operation TEXT NOT NULL, variables TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS versions(
 urn TEXT NOT NULL, digest TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL,
 PRIMARY KEY(urn,digest));
CREATE TABLE IF NOT EXISTS sightings(
 delivery TEXT NOT NULL REFERENCES observations(delivery), urn TEXT NOT NULL,
 digest TEXT NOT NULL, PRIMARY KEY(delivery,urn,digest),
 FOREIGN KEY(urn,digest) REFERENCES versions(urn,digest));
CREATE TABLE IF NOT EXISTS collections(
 delivery TEXT NOT NULL REFERENCES observations(delivery), path TEXT NOT NULL,
 body TEXT NOT NULL, PRIMARY KEY(delivery,path));
CREATE VIEW IF NOT EXISTS latest_entities AS
 SELECT urn,digest,kind,body,observed_at FROM (
 SELECT v.*,o.observed_at,ROW_NUMBER() OVER (
 PARTITION BY v.urn ORDER BY o.observed_at DESC,o.rowid DESC) AS rank
 FROM versions v JOIN sightings s USING(urn,digest)
 JOIN observations o ON o.delivery=s.delivery) WHERE rank=1;
'''


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def collection_rows(value, path='data', depth=0):
    if depth > 40:
        raise ValueError('Collection nesting limit')
    if isinstance(value, dict):
        if 'paging' in value or '*elements' in value:
            # Keep metadata, cursors, order and entity references together.
            yield path, value
        else:
            for key, child in value.items():
                yield from collection_rows(child, path + '/' + key, depth+1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from collection_rows(child, path + '/' + str(index), depth+1)


def accept(record, context, delivery):
    if record.get('record_version') != 1 or type(record.get('record_version')) is not int:
        raise ValueError('Expected Core capture record v1')
    url = urlsplit(record.get('url', ''))
    if url.scheme != 'https' or url.netloc != 'www.linkedin.com' or url.path != '/voyager/api/graphql':
        return 'ignored'
    query = parse_qs(url.query)
    operation = query.get('queryId', [''])[0].split('.')[0]
    if operation not in OPERATIONS:
        return 'ignored'
    if not delivery or not isinstance(record.get('record_id'), str):
        raise ValueError('Core delivery and record IDs required')
    state, body = 'observed', None
    if record.get('status') != 200:
        state = 'http_error'
    elif not record.get('body_kept') or not isinstance(record.get('body'), str):
        state = 'body_unavailable'
    elif len(record['body'].encode('utf-8')) > MAX_BODY:
        state = 'body_over_limit'
    else:
        try:
            body = json.loads(record['body'])
            if not isinstance(body, dict) or not isinstance(body.get('included'), list):
                state, body = 'unsupported_shape', None
        except (ValueError, TypeError):
            state = 'invalid_json'
    entities = []
    collections = []
    if body is not None:
        for entity in body['included']:
            if not isinstance(entity, dict):
                continue
            urn, kind = entity.get('entityUrn'), str(entity.get('$type', '')).split('.')[-1]
            if not isinstance(urn, str) or not urn.startswith('urn:li:') or kind not in KINDS:
                continue
            serialized = encode(entity)
            entities.append((urn, hashlib.sha256(serialized.encode()).hexdigest(), kind, serialized))
            # Inline post comment lists and reply lists also carry collection context.
            for path, collection in collection_rows(entity, 'entity/' + urn):
                collections.append((path, encode(collection)))
        for path, collection in collection_rows(body.get('data', {})):
            collections.append((path, encode(collection)))
    output = Path(context['output_dir'])
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.umask(0o077)
    with sqlite3.connect(output / 'archive.sqlite3') as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(SCHEMA)
        with db:
            cursor = db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?)',
                (delivery, record['record_id'], record['ts'], operation,
                 encode(query.get('variables', [])), state))
            if not cursor.rowcount:
                return 'duplicate'
            for urn, digest, kind, serialized in entities:
                db.execute('INSERT OR IGNORE INTO versions VALUES(?,?,?,?)', (urn,digest,kind,serialized))
                db.execute('INSERT OR IGNORE INTO sightings VALUES(?,?,?)', (delivery,urn,digest))
            for path, serialized in collections:
                db.execute('INSERT OR REPLACE INTO collections VALUES(?,?,?)', (delivery,path,serialized))
    return state


def main():
    context = json.loads(os.environ['TAP_PACK_CONTEXT'])
    delivery = os.environ.get('TAP_READER_DELIVERY_ID')
    for line in sys.stdin:
        print(json.dumps({'state':accept(json.loads(line),context,delivery)}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not echo source bodies, URLs or user data into diagnostics.
        print(json.dumps({'error':type(error).__name__}), file=sys.stderr)
        sys.exit(1)
