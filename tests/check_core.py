"""Installed artifact -> Core Writer -> Core Reader subprocess. Synthetic only."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import uuid

args=argparse.ArgumentParser()
args.add_argument('--core',type=Path,required=True)
args.add_argument('--artifact',type=Path,required=True)
args=args.parse_args()
core=args.core.resolve();sys.path.insert(0,str(core))
from tap_core.runtime import Profile
from tap_core.capture import Writer
from tap_core.pack_store import PackStore
from tap_core.readers import Reader

with tempfile.TemporaryDirectory(prefix='linkedin-core-') as tmp:
    profile=Profile(Path(tmp),'/unused/backend',18997,'explicit','https://www.linkedin.com',[],
        bridge={'version':1,'enabled':False,'hub_port':19002,'allow_origins':[],'exclude_origins':[],'page_scripts':[]},
        components={'version':1,'python':sys.executable,'bun':'','readers':{},'handlers':{}})
    profile.save();store=PackStore(profile.root)
    store.install(args.artifact.resolve())
    store.enable('linkedin.archive','0.1.0',origins=['https://www.linkedin.com'],capabilities=['capture.read'])
    spec=store.effective_components(profile.components)['readers']['linkedin.archive']
    seed=json.loads((core/'fixtures/capture/v1.jsonl').read_text().splitlines()[0])
    writer=Writer(profile.root/'data',profile.root/'state')
    urn='urn:li:comment:(activity:1111111111111111111,2222222222222222222)'
    for n,text in enumerate(['A','B','A']):
        entity={'$type':'com.linkedin.voyager.social.Comment','entityUrn':urn,
                'commentary':{'text':text},'commenter':{'actorUrn':'urn:li:fsd_profile:synthetic'},
                'parentComment':'urn:li:comment:synthetic-parent'}
        reaction={'$type':'com.linkedin.voyager.social.Reaction','entityUrn':'urn:li:fsd_reaction:(urn:li:fsd_profile:synthetic,urn:li:activity:1111111111111111111,0)','actorUrn':'urn:li:fsd_profile:synthetic','reactionType':'LIKE'}
        body={'included':[entity,reaction], 'data':{'data':{'socialDashCommentsBySocialDetail':{
            '*elements':[urn],'paging':{'start':0,'count':10,'total':22},
            'metadata':{'sortOrder':'RELEVANCE','paginationToken':'synthetic-cursor'}}}}}
        writer.submit(dict(seed,record_id=str(uuid.uuid4()),ts=1700000000+n,
            url='https://www.linkedin.com/voyager/api/graphql?queryId=voyagerSocialDashComments.fixture&variables=(post:synthetic)',body=json.dumps(body)))
    writer.submit(dict({k:v for k,v in seed.items() if k not in ('body','req_body')},record_id=str(uuid.uuid4()),ts=1700000004,
        url='https://www.linkedin.com/voyager/api/graphql?queryId=voyagerSocialDashComments.fixture',
        body_kept=False,body_reason="media_type",req_body_kept=False,req_body_reason="response_not_retained"))
    writer.submit(dict(seed,record_id=str(uuid.uuid4()),url='https://example.invalid/voyager/api/graphql?queryId=voyagerSocialDashComments.fixture'))
    writer.close();assert writer.written==5
    reader=Reader(profile,'linkedin.archive')
    assert reader.run(spec,max_records=2)['completed_this_run']==2
    assert reader.run(spec)['completed_this_run']==3
    dbpath=profile.root/'data/readers/linkedin.archive/archive.sqlite3'
    def verify():
        with sqlite3.connect(dbpath) as db:
            assert db.execute('select count(*) from observations').fetchone()[0]==4
            assert db.execute('select count(*) from versions').fetchone()[0]==3
            assert db.execute('select count(*) from sightings').fetchone()[0]==6
            latest=json.loads(db.execute('select body from latest_entities where kind="Comment"').fetchone()[0])
            assert latest['commentary']['text']=='A' and latest['parentComment'].endswith('synthetic-parent')
            collection=json.loads(db.execute('select body from collections').fetchone()[0])
            assert collection['paging']['total']==22 and collection['metadata']['sortOrder']=='RELEVANCE'
            assert db.execute("select count(*) from observations where state='body_unavailable'").fetchone()[0]==1
    verify();reader.replay(spec);assert reader.run(spec)['completed_this_run']==5;verify()
    store.disable('linkedin.archive')
    assert dbpath.exists() and not store.effective_components(profile.components)['readers']
print(json.dumps({'scope':'installed artifact, Core Writer and Core Reader; synthetic, no network or launchd',
    'resume':True,'replay_without_duplicates':True,'versions_a_b_a':True,'collection_context':True,
    'missing_body_visible':True,'foreign_origin_ignored':True,'disable_retains_archive':True,'live_capture':False},indent=2))
