"""Conservative pole-name reconciliation with explicit review candidates."""
import re
from difflib import SequenceMatcher
from collections import defaultdict

REJECTED_REFERENCES={'0','AR48G','AR48H/E2','AR48H/E','AR48UT-1/1'}

def normalize(value):
    return re.sub(r'/+', '/', str(value).strip().upper())

def compact(value):
    return re.sub(r'[^A-Z0-9]', '', normalize(value))

def reconcile(reference, pole_ids):
    raw=str(reference).strip()
    if normalize(raw) in REJECTED_REFERENCES:
        return {'original':raw,'resolved':None,'method':'rejected_by_user','candidates':[]}
    if raw in pole_ids:return {'original':raw,'resolved':raw,'method':'exact','candidates':[]}
    if normalize(raw) in ['0','','NAN','NONE']:
        return {'original':raw,'resolved':None,'method':'missing','candidates':[]}
    equivalent=[p for p in pole_ids if normalize(p)==normalize(raw)]
    if len(equivalent)==1:
        return {'original':raw,'resolved':equivalent[0],'method':'separator_normalization','candidates':[]}
    # User-authorized estimate: missing later poles in a mapped numbered run
    # attach to its last mapped pole. Do not merge the missing pole's identity.
    numbered=re.fullmatch(r'(.+[A-Z/])(\d+)',normalize(raw))
    if numbered:
        stem,target=numbered.group(1),int(numbered.group(2))
        sequence=defaultdict(list)
        for p in pole_ids:
            match=re.fullmatch(re.escape(stem)+r'(\d+)',normalize(p))
            if match:sequence[int(match.group(1))].append(p)
        if sequence:
            last=max(sequence)
            if last>=2 and target>last and set(sequence)==set(range(1,last+1)) and all(len(v)==1 for v in sequence.values()):
                return {'original':raw,'resolved':sequence[last][0],'method':'estimated_continuation_attachment','candidates':[],
                        'note':'Load/PV aggregated at last mapped continuation pole; missing downstream span and its voltage drop are not modeled.'}
    # Unique punctuation-equivalent IDs are naming estimates, not new poles.
    punctuation=[p for p in pole_ids if compact(p)==compact(raw)]
    if len(punctuation)==1:
        return {'original':raw,'resolved':punctuation[0],'method':'estimated_punctuation_attachment','candidates':[],
                'note':'Unique punctuation-insensitive name equivalent; original reference preserved.'}
    if not punctuation:
        # Keep within the named branch. Prefer the deepest mapped ancestor.
        ancestors=[]
        for p in pole_ids:
            prefix=normalize(p);ref=normalize(raw)
            if not ref.startswith(prefix) or len(ref)==len(prefix):continue
            tail=ref[len(prefix):]
            if tail[0] in '/-' or tail[0].isdigit() or (prefix[-1].isdigit() and tail[0].isalpha()):
                ancestors.append(p)
        if ancestors:
            deepest=max(len(normalize(p)) for p in ancestors)
            parents=[p for p in ancestors if len(normalize(p))==deepest]
            if len(parents)==1:
                return {'original':raw,'resolved':parents[0],'method':'estimated_parent_attachment','candidates':[],
                        'note':'Missing branch/service pole load aggregated at deepest mapped named parent. Omitted downstream spans have no modeled voltage drop.'}
    candidates={}
    for p in pole_ids:
        score=SequenceMatcher(None,normalize(raw),normalize(p)).ratio()
        reason='name_similarity'
        if compact(raw)==compact(p):reason='punctuation_variant'
        elif normalize(raw).startswith(normalize(p)+'/'):reason='possible_parent_attachment'
        if score>=.7 or reason!='name_similarity':
            candidates[p]={'pole':p,'similarity':round(score,3),'reason':reason}
    ranked=sorted(candidates.values(),key=lambda c:({'punctuation_variant':0,'name_similarity':1,'possible_parent_attachment':2}[c['reason']],-c['similarity'],c['pole']))
    return {'original':raw,'resolved':None,'method':'needs_review','candidates':ranked[:5]}
