"""BZ0109 importer and explicitly provisional LV power-flow model."""
from pathlib import Path
import io, zipfile, re, html, math, json
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
import pandas as pd
import opendssdirect as dss
from pole_matching import reconcile, normalize, REJECTED_REFERENCES

ROOT = Path(__file__).parent
NS = {'k': 'http://www.opengis.net/kml/2.2'}

def distance(a,b):
    return math.hypot((a[0]-b[0])*110500*math.cos(math.radians(a[1])), (a[1]-b[1])*110500)

def import_data():
    poles, geometries, transformer = {}, [], {}
    outer = zipfile.ZipFile(ROOT/'data/BZ0109kmz.zip')
    for name in outer.namelist():
        if not name.endswith('.kmz'): continue
        z = zipfile.ZipFile(io.BytesIO(outer.read(name)))
        root = ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith('.kml'))))
        for p in root.findall('.//k:Placemark', NS):
            cells = re.findall(r'<td[^>]*>(.*?)</td>', p.findtext('k:description', '', NS), re.S)
            cells = [html.unescape(re.sub('<.*?>', '', x)).strip() for x in cells]
            attrs = dict(zip(cells[1::2], cells[2::2]))
            def coords(el): return [[float(v) for v in t.split(',')[:2]] for t in el.text.split()]
            point = p.find('.//k:Point/k:coordinates', NS)
            if point is not None:
                c = coords(point)[0]
                if name.endswith('/BZ0109.kmz'): transformer = dict(attrs, coordinates=c)
                else:
                    pid = attrs.get('Pole_ID', p.findtext('k:name','',NS))
                    poles[pid] = {'id':pid,'coordinates':c,'virtual':False}
            for line in p.findall('.//k:LineString/k:coordinates',NS):
                geometries.append({'coordinates':coords(line), 'conductor':attrs.get('LV_Conductor','unknown'), 'gis_id':attrs.get('LV_L_ID','unknown')})
    transformer['tap_position']=2
    root_id = transformer['Pole_ID']
    poles.setdefault(root_id, {'id':root_id,'coordinates':transformer['coordinates'],'virtual':False})
    edges, snap_errors = [], []
    # Preserve original polyline vertices. Match only nearby poles; never bridge disconnected islands.
    def node(c):
        pid = min(poles, key=lambda p:distance(c,poles[p]['coordinates']))
        dist = distance(c,poles[pid]['coordinates'])
        if dist <= 5: return pid
        pid = f'GIS-{len(poles)}'
        poles[pid] = {'id':pid,'coordinates':c,'virtual':True}
        snap_errors.append({'node':pid,'nearest_pole_m':round(dist,2)})
        return pid
    for g in geometries:
        for a,b in zip(g['coordinates'],g['coordinates'][1:]):
            u,v=node(a),node(b)
            if u!=v: edges.append(dict(g, a=u,b=v,length_m=distance(a,b),coordinates=[a,b],id=len(edges)))
    adj=defaultdict(list)
    for e in edges:
        adj[e['a']].append((e['b'],e));adj[e['b']].append((e['a'],e))
    seen={root_id};queue=deque([root_id]);feeders={root_id:'Transformer'}
    while queue:
        u=queue.popleft()
        for v,e in adj[u]:
            if v in seen:continue
            seen.add(v);feeders[v]=f'Branch {e["id"]+1}' if u==root_id else feeders[u];queue.append(v)
    for p in poles.values(): p['feeder']=feeders.get(p['id'],'Disconnected');p['connected']=p['id'] in seen
    customers=pd.read_excel(ROOT/'data/DATA BZ0109.xls',dtype={'ACCOUNT_NO':str,'POLE':str})
    solar=pd.read_excel(ROOT/'data/SOLAR REPORT on Poles (1).xlsx',sheet_name='Solar Data V2',dtype={'ACCOUNT_NO':str,'POLE':str})
    solar=solar[solar.TRANSFORMER_CODE=='BZ0109']
    # Reconcile only unique case/whitespace/repeated-slash equivalents automatically.
    # Later missing numbered continuations are aggregated at the last mapped pole as authorized estimates. Other fuzzy/parent candidates remain unresolved.
    named_poles=[p for p in poles if not poles[p]['virtual']]
    match_report=[]
    for kind,frame in [('customer',customers),('solar',solar)]:
        frame['POLE_ORIGINAL']=frame.POLE.copy()
        frame['REJECTED']=frame.POLE.map(lambda p:normalize(p) in REJECTED_REFERENCES)
        matches={ref:reconcile(ref,named_poles) for ref in frame.POLE.fillna('missing').unique()}
        for ref,match in matches.items():
            if match['method']=='exact':continue
            match_report.append(dict(match,kind=kind,accounts=int((frame.POLE.fillna('missing')==ref).sum())))
        frame['POLE']=frame.POLE.map(lambda ref:matches.get(ref,{}).get('resolved') or ref)
    readings=pd.read_excel(ROOT/'data/BZ0109LP.xlsx',sheet_name=0)
    readings=readings[readings.CUSTOMER_REF=='024/BZ0109'].copy()
    readings['datetime']=pd.to_datetime(readings.DATE.astype(str)+' '+readings.TIME.astype(str),errors='coerce')
    readings=readings.dropna(subset=['datetime']).sort_values('datetime').drop_duplicates('datetime',keep='last')
    records=[]
    for _,r in readings.iterrows():
        volts=[float(r[f'PHASE_{p}_INST._VOLTAGE (V)']) for p in 'ABC']
        if not all(math.isfinite(v) and 150<v<300 for v in volts):continue
        records.append({'time':r.datetime.isoformat(),'volts':volts,'currents':[float(r[f'PHASE_{p}_INST._CURRENT (A)']) for p in 'ABC'], 'import_kw':float(r['AVG._IMPORT_KW (kW)']), 'export_kw':float(r['AVG._EXPORT_KW (kW)'])})
    unmatched=customers[~customers.POLE.isin(poles)]
    unreachable=customers[customers.POLE.isin([p for p in poles if p not in seen])]
    for p in poles.values():
        s=solar[solar.POLE==p['id']];p['solar_kw']=float(pd.to_numeric(s.INV_CAPACITY,errors='coerce').fillna(0).sum());p['pv_kw']=float(pd.to_numeric(s.CAPACITY,errors='coerce').fillna(0).sum());p['customers']=int((customers.POLE==p['id']).sum())
    audit={'rejected_customers':int(customers.REJECTED.sum()),'rejected_solar':int(solar.REJECTED.sum()),'unresolved_customers':int((~customers.POLE.isin(poles) & ~customers.REJECTED).sum()),'unresolved_solar':int((~solar.POLE.isin(poles) & ~solar.REJECTED).sum()),'customers':len(customers),'matched_customers':len(customers)-len(unmatched),'unmatched_customers':len(unmatched),'disconnected_customers':len(unreachable),'solar_accounts':len(solar),'unmatched_solar':int((~solar.POLE.isin(poles)).sum()),'connected_poles':sum(p['connected'] and not p['virtual'] for p in poles.values()),'named_poles':sum(not p['virtual'] for p in poles.values()),'virtual_nodes':len(snap_errors),'intervals':len(records),'conductor_codes':sorted(set(g['conductor'] for g in geometries)), 'unmatched_poles':sorted(set(unmatched.POLE.fillna('missing'))),'snap_tolerance_m':5,'discarded_meter_intervals':len(readings)-len(records),'estimated_customers':sum(m['accounts'] for m in match_report if m['kind']=='customer' and m['method'].startswith('estimated_')),'estimated_solar':sum(m['accounts'] for m in match_report if m['kind']=='solar' and m['method'].startswith('estimated_')),'normalized_customers':sum(m['accounts'] for m in match_report if m['kind']=='customer' and m['method']=='separator_normalization'),'normalized_solar':sum(m['accounts'] for m in match_report if m['kind']=='solar' and m['method']=='separator_normalization')}
    return dict(poles=list(poles.values()),edges=edges,root=root_id,transformer=transformer,readings=records,audit=audit,pole_matches=match_report),customers,solar

DATA,CUSTOMERS,SOLAR=import_data()

def irradiance(time):
    # Clear-day synthetic Colombo irradiance, not weather or measured historical irradiance.
    t=pd.Timestamp(time);hour=t.hour+t.minute/60
    return max(0,math.sin(math.pi*(hour-6)/12))*1000 if 6<=hour<=18 else 0

def simulate(index=0, r=0.443,x=0.08,pf=0.95,solar_fraction=1,load_model=3,phase_case='balanced',neutral_r=.641):
    if not 0<=index<len(DATA['readings']):raise ValueError('Invalid reading index')
    if not (0.01<=r<=5 and 0<=x<=2 and .8<=pf<=1 and 0<=solar_fraction<=1 and load_model in [1,3,5] and phase_case in ['balanced','round_robin','skewed','all_a'] and .01<=neutral_r<=5):raise ValueError('Invalid model parameters')
    reading=DATA['readings'][index]
    sun=irradiance(reading['time'])/1000*solar_fraction
    # Clip each inverter individually; clipping aggregate capacity would be incorrect.
    pv_at_pole=defaultdict(float)
    for _,sr in SOLAR.iterrows():
        if not sr.REJECTED and sr.POLE in {p['id'] for p in DATA['poles']}:
            pv_at_pole[sr.POLE]+=min(float(sr.CAPACITY)*sun,float(sr.INV_CAPACITY))
    ctx=dss.NewContext();cmd=ctx.Text.Command
    poles={p['id']:p for p in DATA['poles']};bus={p:f'b{i}' for i,p in enumerate(poles)};root=bus[DATA['root']]
    cmds=[]
    def run(c):cmds.append(c);cmd(c)
    run('set defaultbasefrequency=50')
    run(f'new circuit.BZ0109 bus1={root} basekv=0.4 pu=1 phases=3 frequency=50')
    run('disable vsource.source')
    for i,v in enumerate(reading['volts']):run(f'new vsource.phase{i} phases=1 bus1={root}.{i+1} bus2={root}.4 basekv={v/1000} pu=1 angle={-120*i} frequency=50 r1=0.00001 x1=0.00001 r0=0.00001 x0=0.00001')
    run(f'new reactor.neutral_ground phases=1 bus1={root}.4 bus2={root}.0 r=0.00001 x=0.00001')
    # Primitive 4-wire matrix: approximate self impedances; mutual terms unverified.
    run(f'new linecode.lv70neutral50 nphases=4 units=km rmatrix=[{r} | 0 {r} | 0 0 {r} | 0 0 0 {neutral_r}] xmatrix=[{x} | 0 {x} | 0 0 {x} | 0 0 0 {x}] cmatrix=[0 | 0 0 | 0 0 0 | 0 0 0 0]')
    for e in DATA['edges']:
        if not poles[e['a']]['connected']:continue
        run(f'new line.l{e["id"]} bus1={bus[e["a"]]}.1.2.3.4 bus2={bus[e["b"]]}.1.2.3.4 phases=4 length={e["length_m"]/1000} units=km linecode=lv70neutral50')
    # Monthly consumption only provides allocation weights, not interval demand or phase identity.
    month_cols=list(CUSTOMERS.columns[4:16]);weights=CUSTOMERS[month_cols].apply(pd.to_numeric,errors='coerce').clip(lower=0).mean(axis=1).fillna(0)
    total=float(weights.sum())
    pv_total=sum(pv_at_pole.values())
    gross=max(0,reading['import_kw']-reading['export_kw']+pv_total)
    excluded_kw=0
    assignments={};phase_totals=defaultdict(lambda:[0.,0.,0.])
    order=sorted(range(len(CUSTOMERS)),key=lambda i:-float(weights.iloc[i])) if phase_case=='balanced' else range(len(CUSTOMERS))
    for i in order:
        c=CUSTOMERS.iloc[i]
        if c.REJECTED:continue
        feeder=poles.get(c.POLE,{}).get('feeder','unmatched')
        phase=(min(range(3),key=lambda k:phase_totals[feeder][k])+1) if phase_case=='balanced' else (i%3+1 if phase_case=='round_robin' else (1 if phase_case=='all_a' or i%10<7 else 2 if i%10<9 else 3))
        assignments[str(c.ACCOUNT_NO)]=phase
        if c.SERVICE_TYPE_CODE=='TP':
            for k in range(3):phase_totals[feeder][k]+=float(weights.iloc[i])/3
        else:phase_totals[feeder][phase-1]+=float(weights.iloc[i])
    for i,(_,c) in enumerate(CUSTOMERS.iterrows()):
        kw=gross*float(weights.iloc[i])/total if total else 0
        if c.REJECTED or c.POLE not in poles or not poles[c.POLE]['connected']:excluded_kw+=kw;continue
        three=c.SERVICE_TYPE_CODE=='TP';phase=assignments[str(c.ACCOUNT_NO)]
        b=bus[c.POLE]+('.1.2.3.4' if three else f'.{phase}.4')
        for m in ([1,5] if load_model==3 else [load_model]):
            power=kw/2 if load_model==3 else kw
            run(f'new load.c{i}m{m} bus1={b} phases={3 if three else 1} conn=wye kv={0.4 if three else 0.23094} kw={power} pf={pf} model={m} vminpu=0.1 vmaxpu=2')
    service_types={str(c.ACCOUNT_NO):c.SERVICE_TYPE_CODE for _,c in CUSTOMERS.iterrows()}
    for i,(_,sr) in enumerate(SOLAR.iterrows()):
        if sr.REJECTED or sr.POLE not in poles or not poles[sr.POLE]['connected']:continue
        power=min(float(sr.CAPACITY)*sun,float(sr.INV_CAPACITY))
        if power<=0:continue
        three=service_types.get(str(sr.ACCOUNT_NO),'TP')=='TP'
        phase=assignments.get(str(sr.ACCOUNT_NO),i%3+1)
        b=bus[sr.POLE]+('.1.2.3.4' if three else f'.{phase}.4')
        run(f'new generator.pv{i} bus1={b} phases={3 if three else 1} conn=wye kv={0.4 if three else 0.23094} kw={power} pf=1 model=1 vminpu=0.1 vmaxpu=2')
    run('set algorithm=normal maxiterations=1000');run('solve')
    if not ctx.Solution.Converged():
        # Retry Newton from the normal solver's current voltage iterate.
        run('set algorithm=newton');run('solve')
    if not ctx.Solution.Converged():
        # Continuation solves the same final case, without changing tolerance.
        # Fine steps avoid the cold-start basin seen with restored branch loads.
        generators={}
        for name in ctx.Generators.AllNames():
            if name.lower()=='none':continue
            ctx.Generators.Name(name);generators[name]=ctx.Generators.kW()
        for step in range(101):
            fraction=step/100
            run(f'set algorithm=normal loadmult={fraction}')
            for name,power in generators.items():run(f'edit generator.{name} kw={power*fraction}')
            run('solve')

    converged=ctx.Solution.Converged();out=[]
    for p in poles.values():
        result=dict(p,volts=None,vuf=None,magnitude_imbalance=None,solar_output_kw=pv_at_pole[p['id']],neutral_voltage=None)
        if p['connected'] and converged:
            ctx.Circuit.SetActiveBus(bus[p['id']]);raw=ctx.Bus.Voltages();nodes=ctx.Bus.Nodes();phasors={n:complex(raw[2*i],raw[2*i+1]) for i,n in enumerate(nodes)}
            if all(n in phasors for n in [1,2,3]):
                neutral=phasors.get(4,0j);result['neutral_voltage']=abs(neutral)
                va,vb,vc=[phasors[n]-neutral for n in [1,2,3]];a=complex(-.5,math.sqrt(3)/2);v1=(va+a*vb+a*a*vc)/3;v2=(va+a*a*vb+a*vc)/3
                v=list(map(abs,[va,vb,vc]));mean=sum(v)/3
                result.update(volts=v,vuf=100*abs(v2)/abs(v1) if abs(v1)>1 else None,magnitude_imbalance=100*max(abs(t-mean) for t in v)/mean if mean else None)
        out.append(result)
    source_kw=-sum(ctx.Circuit.TotalPower()[::2]);loss_kw=ctx.Circuit.Losses()[0]/1000
    source_currents=[]
    for i in range(3):
        ctx.Circuit.SetActiveElement(f'vsource.phase{i}');source_currents.append(ctx.CktElement.CurrentsMagAng()[0])
    return {'phase_case':phase_case,'irradiance_w_m2':sun*1000,'pv_output_kw':sum(pv_at_pole[p['id']] for p in poles.values() if p['connected']),'modeled_currents':source_currents,'measured_currents':reading['currents'],'converged':bool(converged),'time':reading['time'],'poles':out,'source_kw':source_kw,'loss_kw':loss_kw,'measured_net_kw':reading['import_kw']-reading['export_kw'],'excluded_load_kw':excluded_kw,'dss':'\n'.join(cmds),'assumptions':['Exploratory LV-terminal model. 250 kVA and tap position 2 are metadata: transformer ratio, tap step and impedance are missing.',
        'Assumed 70 mm² aluminium phase R=.443 Ω/km and 50 mm² aluminium neutral R=.641 Ω/km at 20°C. Edit impedance for actual material/temperature. Primitive mutual impedance and geometry are unverified.',
        'Explicit neutral connected along every modeled span, grounded only at transformer. Customer protective earth is separate and is not bonded into this model.',
        f'Phase scenario: {phase_case}. Balanced=greedy demand weighting per inferred branch; round_robin=equal customer counts; skewed=70/20/10 customer counts; all_a=single-phase demand concentrated on A. These are scenarios, not guaranteed extrema.',
        'Three-phase customers and their PV are balanced. Single-phase PV follows the assumed phase of the matching customer account; inverter phase is inferred from customer service type, not verified hardware.',
        'Missing continuation poles use the last mapped sequence pole; other missing branch/service poles use the deepest mapped named parent. Unique punctuation equivalents are estimated attachments. All estimates preserve original references, per user instruction. Their additional spans and downstream voltage drops are omitted; results belong to the mapped attachment pole.',
        'Monthly kWh supplies demand weights; gross demand uses measured net kW plus modeled PV. Mixed load means 50% constant power and 50% constant current per customer at nominal voltage. No loss/per-phase calibration.',
        'Feeders must start separately at transformer; GIS currently infers two root branches. Endpoint matching at 5 m is provisional and disconnected nodes remain unsolved.',
        'Measured phase voltage magnitudes with assumed 120-degree phase angles; VUF is modeled, not measured.',
        'Synthetic Colombo clear-day irradiance: sunrise 06:00, sunset 18:00, peak 1000 W/m². PV AC estimate = PV capacity × irradiance/1000 × scenario multiplier, clipped individually at inverter capacity. No temperature/weather/efficiency model.']}
