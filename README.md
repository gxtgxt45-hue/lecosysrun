# LECO Network Lab — BZ0109

An exploratory OpenDSS LV analysis application for the Kandana Church transformer. The interface provides a geographic pole network, phase voltage and unbalance coloring, inferred feeder filters, solar connection markers, selectable meter timestamps and playback, four phase scenarios and comparison, pole inspection, and CSV/OpenDSS exports. The map uses the supplied geographic coordinates without sending customer data to a map provider; street imagery is not included.

## Run

Use the existing checkout; each cloud task is already isolated. Do not create a worktree unless explicitly requested.

Requires Python 3.12 on Linux. From `/workspace/lecosysrun`:

```sh
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest -v
.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Place these original files in `data/` (already copied in this prepared environment):

- `BZ0109kmz.zip`
- `DATA BZ0109.xls`
- `BZ0109LP.xlsx`
- `SOLAR REPORT on Poles (1).xlsx`

Raw customer spreadsheets, installed packages and generated outputs are ignored by Git. They must be retained in the prepared environment snapshot or supplied independently when cloning this source. No uploaded document instructions are executed. Do not commit the raw customer records inadvertently.

`GET /api/network` reports imported topology and data quality. `GET /api/run` solves one interval. `GET /api/export?format=csv` exports results; `format=dss` exports the actual commands. `GET /api/day` runs all available intervals on the selected day and exports every named pole. Endpoints accept `index`, `r`, `x`, `pf`, `solar_fraction`, `load_model` (1 = constant power, 5 = constant current, 3 = 50/50 mixture), `phase_case` (`balanced`, `round_robin`, `skewed`, `all_a`), and `neutral_r`. These are global scenario parameters, not customer-specific classifications. `GET /api/compare` runs all four phase cases at the chosen timestamp. Runs do not modify the spreadsheets.

## What is verified

The imported dataset contains 571 customer records, 140 unique named poles (139 connected), 21 solar accounts and 2,824 usable transformer intervals between June 12 and July 11, 2026. 565 customers and 20 solar accounts are attached to named GIS poles: 416 exact customer matches, 12 customer separator corrections and 137 estimated customer attachments. Six unresolved customers and one unresolved solar account are excluded, rather than silently assigned to another pole. The data audit lists all unmatched pole references. There are two virtual geometry vertices and two inferred root branches; these are not confirmed operational feeder IDs. Endpoint matching uses a 5 m tolerance and does not bridge islands.

Tests verify the measured terminal voltage boundary, retained-load/PV/loss power balance, disconnected poles, constant-current behavior, phase scenarios, explicit neutral displacement, individual inverter clipping, night-time PV shutdown, parameter rejection and current-interval/full-day exports. June 12 has 94 usable readings, not 96; missing/invalid readings are not interpolated.

## Electrical limits

This is an LV terminal model, not yet a validated full distribution-transformer model. Each phase uses its measured transformer voltage magnitude with an assumed 120-degree angular separation, at 50 Hz. The 250 kVA transformer rating is metadata: HV supply, transformer winding connection, taps and impedance are not yet simulated.

Monthly customer kWh supplies relative demand weights. Gross demand is estimated from measured net transformer kW plus scenario PV output; it is not a measured customer load profile. Unmatched customer allocation is excluded, and the app displays the resulting measured-versus-modeled demand gap. Do not interpret convergence as calibration.

Single-phase customer phase assignments have four options: greedy balancing of monthly demand weights by inferred feeder, round-robin customer counts, 70/20/10 customer counts, and all single-phase customers on A. These are scenario candidates, not mathematically proven best/worst bounds. Actual solar phases remain unknown. PV uses the matching customer service type: single-phase inverter injection follows the scenario phase of its account; three-phase PV and loads are balanced. Inverter wiring is inferred, not verified. The default load is 50% constant power + 50% constant current per customer, with PF 0.95. A constant-current component consumes power proportional to modeled voltage, so gross allocation at nominal voltage does not imply exact measured terminal power.

Per the user's supplied sizes, phase conductors are modeled as 70 mm² and the neutral as 50 mm². Aluminium at 20°C is assumed (Rphase=.443 Ω/km, Rneutral=.641 Ω/km); confirm material and temperature. A four-conductor primitive diagonal impedance matrix uses X=.08 Ω/km with zero mutual terms, pending conductor geometry or verified matrices. GIS conductor codes are preserved but not translated into differing electrical properties. The neutral is explicit, grounded at the transformer only; customer protective earth is separate. Individual service drops are not modeled. Neutral displacement is visible in the pole inspector and four-case comparison.

The 250 kVA rating and tap position 2 are recorded as user-supplied metadata. Position 2 cannot determine ratio without rated voltages, tap direction/step and nameplate impedance. The measured LV boundary remains the source until these are supplied.

Colombo PV output uses a synthetic clear-day irradiance curve: zero outside 06:00–18:00, sinusoidal daylight peaking at 1000 W/m² at noon, in assumed Sri Lanka meter local time. For each solar account, `output = min(PV_capacity × irradiance / 1000 × multiplier, inverter_capacity)`. The multiplier defaults to 1. All estimated AC generation is injected at the matched pole. This omits weather, orientation, shading, temperature and conversion losses, and is not a historical PV reconstruction. Clipping is performed per inverter, not on aggregated pole capacity.

VUF is `100 × |negative-sequence voltage| / |positive-sequence voltage|`, derived from modeled complex phase voltages. Magnitude imbalance is the maximum deviation from average phase magnitude divided by that average. Neither is a measurement of actual phase angles. Map thresholds are illustrative (230 V nominal), not a declaration of LECO compliance limits.

## Inputs needed for an accurate model

1. Confirmed customer-to-pole references, including the unmatched references; service-drop lengths and conductors.
2. Customer and inverter A/B/C assignments, three-phase connection details, customer load model (constant power/current/ZIP) and PF or kvar.
3. GIS conductor code dictionary for LVB240–LVB245 and LVB343: phase and neutral sizes/material, R/X or primitive impedance matrices, arrangement and ratings; earthing locations/resistance.
4. Confirmed feeder topology, normally open switches/ties, energized phases, and meter-to-feeder mapping. GIS `LV_A`, `LV_B`, `LV_FDR_ID` are blank.
5. Transformer nameplate: HV/LV rated voltage, vector group, % impedance and losses, tap setting, neutral/earthing and upstream source strength.
6. Customer/feeder interval profiles if available; actual PV output or irradiance/temperature, inverter phase, PF/Volt-VAR controls and commissioning dates.
7. Confirmation of meter timestamp timezone, phase-current signs/definitions, measurement placement, and phase active/reactive power or voltage angles if available.

These inputs are needed before trusting pole voltage or unbalance estimates for operational decisions. The additional customer/feeder meter records in the workbook are retained in the original input, but only transformer meter `024/BZ0109` is currently used; interpreting and assigning the other channels requires confirmed mapping and channel definitions.

## Pole-reference reconciliation

Original references remain in POLE_ORIGINAL and input spreadsheets are unchanged. Unique case/whitespace/repeated-slash equivalents are normalized. Per the user's instruction, missing downstream loads and PV are aggregated at mapped attachment poles using these labeled estimates:

- Missing later poles in a contiguous numbered run attach to its last mapped member, including slash-numbered runs: N4/N5 → N3; P/G//5 and //6 → P/G//4.
- Missing branch/service references attach to the deepest unambiguous mapped named parent: AR48U/K/B → AR48U/K; AR48M//B3A → AR48M//B3.
- Unique punctuation-insensitive equivalent references attach to that mapped pole. Colliding equivalents are not automatically selected.

The report records original name, attachment, account count and method. The interface and /api/pole-matches.csv expose the review. Original missing poles remain distinct identities; no fabricated coordinates or spans are added. Voltages belong to the mapped attachment and omit the missing downstream voltage drop. These estimates are not verified locations or geographic nearest-neighbor measurements. Other fuzzy matches stay unresolved, particularly across different root branches.

Six unresolved customers reference 0 (one), AR48G (one), AR48H//E2 (two), AR48H/E (one), and AR48UT-1/1 (one). The remaining solar reference is AR48H//E2. They require a confirmed connection or correction; they are not discarded from the source files.

Restoring estimated loads requires more solver iterations for some timestamps. Runs use the normal solver with up to 1,000 iterations, then retry Newton from its voltage iterate only if necessary. If that fails, a 1% continuation ramp solves progressively from zero demand/PV back to the exact full demand/PV, keeping the convergence tolerance unchanged. Failure still yields converged=false and no pole voltage result. Inverter injection uses the scenario active power at fixed PF, without voltage-based tripping controls. Full-day exports preserve convergence status.

## Current user exclusions

The user has rejected the remaining references for now: 0, AR48G, AR48H//E2, AR48H/E and AR48UT-1/1. This excludes six customers and the one solar account at AR48H//E2. They are labeled rejected_by_user rather than awaiting matching. Original spreadsheets and records remain available; the policy is reversible in REJECTED_REFERENCES. No circuit load or PV generator is created for these records. Current active scope is 565 customers and 20 solar accounts; there are no pending unresolved records outside this explicit rejection set. Demand allocated to the excluded records is retained only as the excluded-demand diagnostic and is not silently redistributed onto other customers. Transformer meter readings still represent the full measured network.
