from pathlib import Path
from threading import Lock
import csv,io
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from model import DATA,simulate
app=FastAPI(title='LECO Network Lab')
lock=Lock()
@app.get('/')
def home(): return FileResponse(Path(__file__).parent/'static/index.html')
@app.get('/api/network')
def network():return DATA
@app.get('/api/run')
def run(index:int=0,r:float=.443,x:float=.08,pf:float=.95,solar_fraction:float=1,load_model:int=3,phase_case:str="balanced",neutral_r:float=.641):
    try:
        with lock:return simulate(index,r,x,pf,solar_fraction,load_model,phase_case,neutral_r)
    except ValueError as e:raise HTTPException(422,str(e))
@app.get('/api/export')
def export(index:int=0,r:float=.443,x:float=.08,pf:float=.95,solar_fraction:float=1,load_model:int=3,phase_case:str="balanced",neutral_r:float=.641,format:str=Query('csv',pattern='^(csv|dss)$')):
    result=run(index,r,x,pf,solar_fraction,load_model,phase_case,neutral_r)
    if format=='dss':return Response(result['dss'],media_type='text/plain',headers={'Content-Disposition':'attachment; filename=BZ0109.dss'})
    s=io.StringIO();w=csv.writer(s);w.writerow(['time','pole','feeder','connected','A_V','B_V','C_V','VUF_percent','magnitude_imbalance_percent'])
    for p in result['poles']:w.writerow([result['time'],p['id'],p['feeder'],p['connected'],*(p['volts'] or ['','','']),p['vuf'],p['magnitude_imbalance']])
    return Response(s.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=pole_voltages.csv'})
@app.get('/api/day')
def day(index:int=0,r:float=.443,x:float=.08,pf:float=.95,solar_fraction:float=1,load_model:int=3,phase_case:str="balanced",neutral_r:float=.641):
    if not 0<=index<len(DATA['readings']):raise HTTPException(422,'Invalid reading index')
    date=DATA['readings'][index]['time'][:10]
    indices=[i for i,v in enumerate(DATA['readings']) if v['time'].startswith(date)]
    s=io.StringIO();w=csv.writer(s);w.writerow(['time','pole','feeder','converged','A_V','B_V','C_V','VUF_percent','solar_kw','measured_net_kw','modeled_source_kw'])
    for i in indices:
        result=run(i,r,x,pf,solar_fraction,load_model,phase_case,neutral_r)
        for p in result['poles']:
            if not p['virtual']:w.writerow([result['time'],p['id'],p['feeder'],result['converged'],*(p['volts'] or ['','','']),p['vuf'],p['solar_kw'],result['measured_net_kw'],result['source_kw']])
    return Response(s.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename=BZ0109_{date}.csv'})
@app.get('/api/compare')
def compare(index:int=0,r:float=.443,x:float=.08,pf:float=.95,solar_fraction:float=1,load_model:int=3,neutral_r:float=.641):
    cases=[]
    for case in ['balanced','round_robin','skewed','all_a']:
        result=run(index,r,x,pf,solar_fraction,load_model,case,neutral_r)
        volts=[v for p in result['poles'] for v in (p['volts'] or [])]
        cases.append({'case':case,'converged':result['converged'],'min_v':min(volts) if volts else None,'max_v':max(volts) if volts else None,'max_vuf':max((p['vuf'] or 0 for p in result['poles']),default=0),'max_neutral_v':max((p['neutral_voltage'] or 0 for p in result['poles']),default=0),'source_kw':result['source_kw']})
    return {'time':DATA['readings'][index]['time'],'cases':cases,'note':'Scenario comparison, not proven best/worst bounds. Single-phase PV follows the customer scenario; inverter phases are inferred from customer service type.'}
@app.get('/api/pole-matches.csv')
def pole_matches():
    s=io.StringIO();w=csv.writer(s)
    w.writerow(['kind','original_reference','accounts','resolved_pole','status','candidate_poles','candidate_reasons','name_similarity_scores'])
    for m in DATA['pole_matches']:
        w.writerow([m['kind'],m['original'],m['accounts'],m['resolved'] or '',m['method'],'; '.join(c['pole'] for c in m['candidates']),'; '.join(c['reason'] for c in m['candidates']),'; '.join(str(c['similarity']) for c in m['candidates'])])
    return Response(s.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=pole_match_review.csv'})
