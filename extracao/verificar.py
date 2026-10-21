import json, sys, numpy as np
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.element as E
from pathlib import Path

pasta = Path(r"C:\Users\robso\PIBIC\pibic-ifc-python\modelos")

st = ifcopenshell.geom.settings()
try: st.set("use-world-coords", True)
except Exception as e: print("settings:", e)

for ifc in sorted(pasta.glob("*.ifc")):
    m = ifcopenshell.open(str(ifc)); gt = json.load(open(str(ifc).replace(".ifc","_gabarito.json")))
    bars = m.by_type("IfcReinforcingBar")
    falhas = 0; xs_est = []; diam_geo = []
    for b in bars:
        try:
            sh = ifcopenshell.geom.create_shape(st, b)
            v = np.array(sh.geometry.verts).reshape(-1,3)*1000.0
            if b.Name and "Estribo" in b.Name or (b.PredefinedType in (None,"NOTDEFINED") and (v[:,0].max()-v[:,0].min())<30):
                xs_est.append(round((v[:,0].max()+v[:,0].min())/2,1))
        except Exception as e:
            falhas += 1; print("  falha geom:", b.Name, str(e)[:80])
    attrs = sum(1 for b in bars if b.NominalDiameter)
    print(f"{ifc.name}: {len(bars)} barras no IFC (gabarito {gt['resumo']['total_barras']}), "
          f"falhas de geometria={falhas}, com NominalDiameter={attrs}, beams={len(m.by_type('IfcBeam'))}")
    xs_est.sort()
    esp = sorted(set(round(b-a,0) for a,b in zip(xs_est, xs_est[1:])))
    print(f"   estribos detectados pela geometria: {len(xs_est)} (gabarito {gt['resumo']['n_estribos']}), espacamentos={esp}")
    if attrs:
        soma = sum(b.BarLength for b in bars); print(f"   soma BarLength={soma/1000:.3f} m  vs gabarito {gt['resumo']['comprimento_total_aco_m']} m")