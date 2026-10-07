import unittest, io, csv
from model import DATA, CUSTOMERS, SOLAR, simulate, irradiance
from app import export, day, pole_matches
from pole_matching import reconcile

class ModelChecks(unittest.TestCase):
    def test_measured_boundary_and_power_balance(self):
        result=simulate(0,load_model=1)
        self.assertTrue(result['converged'])
        root=next(p for p in result['poles'] if p['id']==DATA['root'])
        for actual,expected in zip(root['volts'],DATA['readings'][0]['volts']):
            self.assertAlmostEqual(actual,expected,delta=.02)
        # Distribution loss must reconcile retained gross load and retained PV.
        connected_pv=result['pv_output_kw']
        all_pv=sum(p['solar_output_kw'] for p in result['poles'])
        gross=max(0,result['measured_net_kw']+all_pv)
        expected=gross-result['excluded_load_kw']-connected_pv+result['loss_kw']
        self.assertAlmostEqual(result['source_kw'],expected,delta=.01)
        self.assertGreater(result['loss_kw'],0)
        for p in result['poles']:
            if not p['connected']:self.assertIsNone(p['volts'])
    def test_parameter_validation(self):
        for kwargs in [{'index':-1},{'index':len(DATA['readings'])},{'r':-1},{'pf':0},{'load_model':2}]:
            with self.assertRaises(ValueError):simulate(**kwargs)
    def test_current_model_and_solar_sensitivity(self):
        no_pv=simulate(1000,solar_fraction=0,load_model=5)
        pv=simulate(1000,solar_fraction=1,load_model=5)
        self.assertTrue(no_pv['converged'] and pv['converged'])
        self.assertNotEqual(no_pv['poles'][0]['volts'],pv['poles'][0]['volts'])
    def test_phase_cases_and_neutral(self):
        cases=[simulate(1000,phase_case=c) for c in ['balanced','round_robin','skewed','all_a']]
        self.assertTrue(all(c['converged'] for c in cases))
        self.assertGreater(max(p['neutral_voltage'] or 0 for p in cases[-1]['poles']),max(p['neutral_voltage'] or 0 for p in cases[0]['poles']))
        root=next(p for p in cases[-1]['poles'] if p['id']==DATA['root'])
        self.assertLess(root['neutral_voltage'],.02)
    def test_daylight_and_individual_inverter_clipping(self):
        self.assertEqual(irradiance('2026-06-12T00:00:00'),0)
        self.assertAlmostEqual(irradiance('2026-06-12T12:00:00'),1000)
        noon=next(i for i,r in enumerate(DATA['readings']) if r['time']=='2026-06-12T12:00:00')
        result=simulate(noon,solar_fraction=1)
        connected={p['id'] for p in DATA['poles'] if p['connected']}
        expected=sum(min(float(r.CAPACITY),float(r.INV_CAPACITY)) for _,r in SOLAR.iterrows() if r.POLE in connected)
        self.assertAlmostEqual(result['pv_output_kw'],expected)
        self.assertEqual(simulate(0)['pv_output_kw'],0)
    def test_pole_reconciliation(self):
        self.assertEqual(reconcile(' ar48m/c ',['AR48M//C'])['resolved'],'AR48M//C')
        self.assertEqual(reconcile('AR48U/N5',['AR48U/N','AR48U/N3'])['resolved'],'AR48U/N')
        self.assertIsNone(reconcile('AR48U/P/G///1',['AR48U/P/G/1','AR48U/P/G//1'])['resolved'])
        self.assertEqual(reconcile('AR48U/N5',['AR48U/N1','AR48U/N2','AR48U/N3'])['resolved'],'AR48U/N3')
        self.assertEqual(reconcile('AR48U/N4',['AR48U/N1','AR48U/N2','AR48U/N3'])['method'],'estimated_continuation_attachment')
        self.assertIsNone(reconcile('AR48U/N5',['AR48U/M1','AR48U/M2'])['resolved'])
        self.assertEqual(DATA['audit']['estimated_customers'],137)
        self.assertEqual(reconcile('AR48U/K/B',['AR48U/K','AR48U/B'])['resolved'],'AR48U/K')
        self.assertEqual(reconcile('AR48M//B3A',['AR48M//B3','AR48M//B'])['resolved'],'AR48M//B3')
        self.assertEqual(reconcile('AR48U/P/G//6',['AR48U/P/G//1','AR48U/P/G//2','AR48U/P/G//3','AR48U/P/G//4'])['resolved'],'AR48U/P/G//4')
        self.assertIsNone(reconcile('AR48H/E',['AR48M//E'])['resolved'])
        self.assertIsNone(reconcile('0',['AR48T'])['resolved'])
        self.assertEqual(DATA['audit']['normalized_customers'],12)
        self.assertEqual(DATA['audit']['unmatched_customers'],6)
        self.assertEqual(DATA['audit']['unmatched_solar'],1)
        self.assertIn('name_similarity_scores',pole_matches().body.decode())
    def test_user_rejections(self):
        self.assertEqual(int(CUSTOMERS.REJECTED.sum()),6)
        self.assertEqual(int(SOLAR.REJECTED.sum()),1)
        self.assertEqual(DATA['audit']['unresolved_customers'],0)
        self.assertEqual(reconcile('AR48H//E2',['AR48H//E2'])['method'],'rejected_by_user')
        result=simulate(0)
        for i,(_,c) in enumerate(CUSTOMERS.iterrows()):
            if c.REJECTED:self.assertNotIn(f'new load.c{i}m',result['dss'])
    def test_exports(self):
        response=export(format='csv')
        rows=list(csv.DictReader(io.StringIO(response.body.decode())))
        self.assertEqual(len(rows),len(DATA['poles']))
        self.assertIn('set defaultbasefrequency=50',export(format='dss').body.decode())
        result=day(index=0)
        rows=list(csv.DictReader(io.StringIO(result.body.decode())))
        expected={r['time'] for r in DATA['readings'] if r['time'].startswith(DATA['readings'][0]['time'][:10])}
        self.assertEqual({r['time'] for r in rows},expected)
        self.assertEqual({r['converged'] for r in rows},{'True'})

if __name__=='__main__':unittest.main()
