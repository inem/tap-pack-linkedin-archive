# linkedin.archive 0.1.0

Passive external TAP Core reader pack. Opening a LinkedIn post, its reactions or
comments supplies material; this pack never makes requests, opens pages, collects
credentials or imports legacy TAP directories. No Hub, browser script or Bun is
needed. Python uses only the standard library and the existing python-jsonl-v1
Core contract.

## First slice

Recognizes captured HTTPS www.linkedin.com/voyager/api/graphql responses for
voyagerFeedDashUpdates, voyagerSocialDashReactions and voyagerSocialDashComments.
Stores the observed entity pool (posts, profiles, reactions, comments and related
social state) plus collection envelopes from data and inline entity collections.
The latter preserve element references, paging, sorting and cursor metadata.
Request variables retain the selected post/filter context; request headers,
cookies and unrelated GraphQL operations are not copied.

This collects observed posts, not exclusively the owner's posts. Own-post filtering,
network enumeration, a complete Saved collection, SDUI/RSC decoding and a readable
UI/export are not implemented in this release. A SaveState encountered in an
accepted response can be stored, but that is not a Saved-list collector.

## Data

Core supplies TAP_PACK_CONTEXT.output_dir and TAP_READER_DELIVERY_ID. The reader
requires versioned Core capture records and writes archive.sqlite3 only under
that output directory (normally <profile>/data/readers/linkedin.archive).
There are no source paths or legacy capture paths in runtime code.

- observations: stable delivery ID, source record ID, observation time, operation,
  request variables and observed/error/unavailable state.
- versions: immutable entity JSON keyed by original URN and content digest.
- sightings: delivery-to-version links. A → B → A retains all three observations
  and two distinct versions.
- collections: original page/list envelopes associated with their observation.
- latest_entities: latest observed entity version, ordered by observation time.

All writes for a delivery commit in one SQLite transaction. Retry/replay of the
same delivery does not duplicate or regress observations. This v1 replay policy
keeps already archived deliveries; it is not a projection-migration mechanism.
Missing bodies, invalid JSON and unrecognized response shapes are visible states.
Bodies larger than 16 MiB are recorded as over-limit rather than parsed.
The existing schema is not migrated automatically; future changes need an explicit
migration strategy.

An observation timestamp is not the time somebody reacted. Absence from a partial
page is not deletion. Raw parent/reply references, when present, are retained;
thread reconstruction and completeness inference are deliberately not claimed.
Counts can differ from visible entity lists. Sorting and page context are retained
so a later view can describe those differences honestly.

## Build and verify

Set CORE and SDK to the relevant source checkouts and OUT to a fresh directory:

```sh
python3 "$SDK/sdk.py" --core "$CORE" build . --out "$OUT"
python3 "$SDK/sdk.py" --core "$CORE" check "$OUT/linkedin.archive-0.1.0.tap-pack"
python3 tests/check_core.py --core "$CORE" --artifact "$OUT/linkedin.archive-0.1.0.tap-pack"
```

The acceptance check uses the real Core immutable pack store, Writer and Reader
subprocesses in a temporary reader-only profile. It verifies continuation, replay,
A → B → A, reactions, comment parent references, collection context, unavailable
bodies, foreign-origin rejection and retention after disable.
Validated with Core b7c3cdd and Pack SDK 0.1.0. No legacy importer is involved.
Live Core capture also produced archive observations while opening LinkedIn
reactions. That run does not claim complete reaction or comment coverage.

Install on a Core profile configured for Python reader components:

```sh
tap --profile <profile> pack install <artifact-path>
tap --profile <profile> pack enable linkedin.archive --version 0.1.0 \
  --grant-origin https://www.linkedin.com --grant-capability capture.read
tap --profile <profile> on
```

Configure/install while the profile is stopped, per Core's reader lifecycle.
The pack does not configure system routing or start a second capture process.
Disabling/uninstalling the pack preserves archived data under Core's normal policy.
