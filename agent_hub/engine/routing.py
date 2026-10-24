"""Deterministic complexity/domain hints and specialization-aware routing."""
import json
import re
from .profiles import Profiles
from .tasks import TaskStore, COMPLEXITIES, number


def classify(contract):
    title = (contract['title']+' '+contract['objective']).casefold()
    sensitive = re.search(r'\b(auth(?:entication|orization)?|autenticaci[oó]n|autorizaci[oó]n|password|contrase[nñ]a|security|seguridad|production|producci[oó]n|drop\s+column|destructiv[oa])\b', title)
    if sensitive:
        return {'complexity':'critical','domain':'security','reason':'sensitive operation requires human and independent reviews'}
    if re.search(r'\b(academic|acad[eé]mic[oa]|apa|universitari[oa]|filosof[ií]a)\b',title):
        return {'complexity':contract['complexity'],'domain':'academic','reason':'academic specialization requested'}
    if len(contract['scope']['files']) <= 1 and re.search(r'\b(color|typo|errata|rename|renombrar|texto|constante)\b',title):
        return {'complexity':'trivial','domain':contract['domain'],'reason':'single-file cosmetic/text change; verify scope before completion'}
    if len(contract['scope']['files']) > 5 or re.search(r'\b(architectur[ea]|arquitectura|migraci[oó]n|subsystem|subsistema)\b',title):
        return {'complexity':'complex','domain':contract['domain'],'reason':'cross-cutting structure or migration'}
    return {'complexity':contract['complexity'],'domain':contract['domain'],'reason':'explicit contract complexity'}


class Router:
    def __init__(self, conn):
        self.conn = conn
        self.profiles = Profiles(conn)

    def candidates(self, task, role='worker'):
        assignment = task.contract['assignment']
        hint = classify(task.contract)
        candidates = []
        for profile in self.profiles.list():
            if role not in profile['roles'] or not profile['available']:
                continue
            if role == 'worker' and assignment['mode'] == 'fixed' and profile['id'] != assignment['agent']:
                continue
            required = set(task.contract['capabilities']) if role == 'worker' else set()
            if not required <= set(profile['capabilities']):
                continue
            if not set(task.contract['skills']) <= set(profile['skills']) and role == 'worker':
                # Global/project skills can be injected; private capabilities must
                # still be explicitly declared in a profile to influence routing.
                from .skills import Skills
                try:
                    Skills(self.conn).for_task(task, profile)
                except ValueError:
                    continue
            previous = self.conn.execute("SELECT profile FROM executions WHERE task=? AND role='worker' ORDER BY id DESC LIMIT 1", (number(task.id),)).fetchone()
            if role == 'reviewer' and previous and previous[0] == profile['id']:
                continue
            metrics = self.conn.execute('SELECT COUNT(*),AVG(success) FROM agent_metrics WHERE profile=? AND domain=? AND complexity=?',
                                        (profile['id'], hint['domain'], task.contract['complexity'])).fetchone()
            historical = (metrics[1] or 0)*5 if metrics[0] >= 3 else 0
            specialization = len(set(task.contract['specializations']) & set(profile['specializations']))*20
            domain = 40 if hint['domain'] in profile['priority_domains'] else 0
            skills = len(set(task.contract['skills']) & set(profile['skills']))*10
            capacity = min(10, profile['context_max_chars']/10000)
            cost = {'local':0,'low':3,'medium':8,'high':15,'unknown':20}[profile['cost_class']]
            # Complexity makes context fit more valuable; no model/provider substitution.
            scale = 2 if hint['complexity'] in ('complex','critical') else 1
            score = 50 + specialization + domain + skills + historical + scale*capacity-cost
            candidates.append({'id':profile['id'],'score':round(score,3),
                               'reason':{'domain':domain,'specialization':specialization,'skills':skills,'history':historical,'cost':cost}})
        return sorted(candidates, key=lambda row: (-row['score'],row['id']))

    def choose(self, ident, role='worker', persist=True):
        task = TaskStore(self.conn).get(ident)
        options = self.candidates(task,role)
        if not options:
            raise ValueError('No hay un perfil compatible/disponible; no se sustituirá una asignación fixed.')
        selected = options[0]
        if persist:
            with self.conn:
                TaskStore(self.conn).event(ident,'task.assigned',{'role':role,'profile':selected['id'],'candidates':options})
        return {'task':ident,'role':role,'selected':selected['id'],'candidates':options,'classification':classify(task.contract)}
