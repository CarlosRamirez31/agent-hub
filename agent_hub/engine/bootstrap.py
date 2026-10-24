"""Explicit native-profile registration; no models, auth changes or overrides."""
from pathlib import Path
from ..agents import registry
from .profiles import Profiles


def initialize(conn, agents=None):
    profiles=Profiles(conn)
    existing={p['id'] for p in profiles.list()}
    created=[];preserved=[];unsupported=[]
    for agent in (registry() if agents is None else agents):
        base=list(agent.command)
        if agent.container:
            if base and base[0]=='podman' and agent.container in base:
                base=base[base.index(agent.container)+1:]
            else:
                base=[agent.kind]
        if agent.kind=='codex':
            command=[*base,'exec','--json','--skip-git-repo-check','-']
            resume=[*base,'exec','resume','{session}','--json','--skip-git-repo-check','-']
            output='codex-jsonl';capabilities=['coding','debugging','refactoring','testing','architecture','security-review']
        elif agent.kind=='hermes':
            command=[*base,'chat','--oneshot','--format','stream-json','--query-file','-','--max-turns','{max_turns}']
            resume=command+['--resume','{session}']
            output='hermes-jsonl';capabilities=['coding','research','summarization','document-analysis','security-review']
        elif agent.kind=='gemini':
            command=[*base,'--output-format','stream-json','--prompt','Perform the task contract supplied on stdin.']
            resume=command+['--resume','{session}']
            output='gemini-jsonl';capabilities=['coding','research','summarization','security-review']
        elif agent.kind=='antigravity':
            command=['agent-hub','agy-run','--no-record','--json']
            resume=command+['--conversation','{session}']
            output='json';capabilities=['coding','research','summarization','security-review']
        else:
            unsupported.append(agent.id);continue
        container={'name':agent.container,'host_root':agent.host_root,'runtime_root':agent.runtime_root} if agent.container else None
        for role in ('worker','reviewer'):
            ident=agent.id if role=='worker' else agent.id+'-reviewer'
            if ident in existing:
                preserved.append(ident);continue
            role_command=list(command);role_resume=list(resume)
            if role=='reviewer' and agent.kind=='codex':
                schema=str(Path(__file__).resolve().parents[2]/'docs/review.schema.json')
                role_command=[*role_command[:-1],'--output-schema',schema,role_command[-1]]
                role_resume=[*role_resume[:-1],'--output-schema',schema,role_resume[-1]]
            if role=='reviewer' and agent.kind=='antigravity':
                schema=str(Path(__file__).resolve().parents[2]/'docs/review.schema.json')
                role_command+=['--schema',schema];role_resume+=['--schema',schema]
            profiles.register({'id':ident,'provider':agent.kind,'description':agent.name+' '+role+' · native CLI authentication; explicit policy/approvals required',
                'capabilities':capabilities,'roles':[role],'command':role_command,'resume_command':role_resume,'format':output,
                'adapter':agent.id,'tools':['filesystem','shell'],'cost_class':'unknown','container':container,
                'priority_domains':['coding'] if agent.kind=='codex' else []})
            created.append(ident)
    return {'created':created,'preserved':preserved,'session_only_adapters':unsupported,
            'models_started':False,'policy_changed':False}
