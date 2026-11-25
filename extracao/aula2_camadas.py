"""
AULA 2 - Extracao em CAMADAS (funciona nos modelos A, B, C e D)

Ideia central: cada modelo guarda os dados em lugares diferentes.
Entao o extrator tenta, em ordem:
  1) o atributo na propria barra
  2) o atributo no TIPO da barra
  3) a geometria (raio do disco, posicao no mundo)

Rode com o botao Run. Precisa de: pip install ifcopenshell numpy
"""
import json
from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as E

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "modelos"

CONF = ifcopenshell.geom.settings()
CONF.set("use-world-coords", True)       # a geometria sai ja posicionada no mundo


# ---------------------------------------------------------------- achar as barras
def achar_armaduras(modelo):
    """Devolve lista de (elemento, motivo). Nao basta by_type('IfcReinforcingBar')!"""
    achados = {}
    for b in modelo.by_type("IfcReinforcingBar"):
        achados[b.id()] = (b, "instancia de IfcReinforcingBar")
    for e in modelo.by_type("IfcElement"):               # inclui proxies, vigas, etc.
        if e.id() in achados:
            continue
        t = E.get_type(e)
        if t is not None and t.is_a("IfcReinforcingBarType"):
            achados[e.id()] = (e, "tipado por IfcReinforcingBarType")
    return list(achados.values())


# ---------------------------------------------------------------- geometria
def item_solido(e):
    """Primeiro item da geometria; se for mapeado, segue ate a forma original."""
    item = e.Representation.Representations[0].Items[0]
    if item.is_a("IfcMappedItem"):
        item = item.MappingSource.MappedRepresentation.Items[0]
    return item


def caixa_mundo(e):
    """Caixa envolvente (min, max) em mm, no sistema do mundo."""
    v = np.array(ifcopenshell.geom.create_shape(CONF, e).geometry.verts).reshape(-1, 3) * 1000
    return v.min(axis=0), v.max(axis=0)


# ---------------------------------------------------------------- dados por camadas
def diametro(e):
    d = getattr(e, "NominalDiameter", None)
    if d:
        return d, "atributo da barra"
    t = E.get_type(e)
    if t is not None and getattr(t, "NominalDiameter", None):
        return t.NominalDiameter, "atributo do tipo"
    it = item_solido(e)
    if it.is_a("IfcSweptDiskSolid"):
        return 2 * it.Radius, "geometria (2 x raio do disco)"
    return None, "nao encontrado"


def eh_estribo(e, extensao_eixo, comp_viga):
    pre = getattr(e, "PredefinedType", None)
    t = E.get_type(e)
    if pre in (None, "NOTDEFINED") and t is not None:
        pre = getattr(t, "PredefinedType", None)
    if pre in ("LIGATURE", "STIRRUP", "SHEAR", "RING"):
        return True, "PredefinedType"
    if pre == "MAIN":
        return False, "PredefinedType"
    # sem informacao: estribo e curto ao longo da viga
    return extensao_eixo < 0.1 * comp_viga, "geometria (extensao no eixo)"


# ---------------------------------------------------------------- um modelo inteiro
def analisar(caminho):
    modelo = ifcopenshell.open(str(caminho))
    gt = json.load(open(str(caminho).replace(".ifc", "_gabarito.json"), encoding="utf-8"))

    # eixo e comprimento da viga: a maior dimensao da caixa da viga de concreto
    vmin, vmax = caixa_mundo(modelo.by_type("IfcBeam")[0])
    ext = vmax - vmin
    eixo = int(np.argmax(ext))
    comp_viga = ext[eixo]

    armaduras = achar_armaduras(modelo)
    estribos, diams, fontes_d, fontes_e = [], [], set(), set()
    for e, _ in armaduras:
        bmin, bmax = caixa_mundo(e)
        est, fonte_e = eh_estribo(e, bmax[eixo] - bmin[eixo], comp_viga)
        fontes_e.add(fonte_e)
        if est:
            d, fonte_d = diametro(e)
            estribos.append((bmin[eixo] + bmax[eixo]) / 2)   # centro da caixa no eixo da viga
            diams.append(d)
            fontes_d.add(fonte_d)

    estribos.sort()
    esp = sorted({round(b - a) for a, b in zip(estribos, estribos[1:])})
    r = gt["resumo"]
    ok = (len(armaduras) == r["total_barras"] and len(estribos) == r["n_estribos"]
          and esp == [round(x) for x in r["espacamentos_distintos_mm"]]
          and set(diams) == {r["diametro_estribo_mm"]})

    print(f"\n=== {caminho.name}")
    print(f"  eixo da viga: {'XYZ'[eixo]} | comprimento: {comp_viga:.0f} mm")
    print(f"  armaduras achadas: {len(armaduras)} (gabarito {r['total_barras']}) | via: {sorted({m for _, m in armaduras})}")
    print(f"  estribos: {len(estribos)} (gabarito {r['n_estribos']}) | classificados por: {sorted(fontes_e)}")
    print(f"  diametro dos estribos: {sorted(set(diams))} (gabarito {r['diametro_estribo_mm']}) | fonte: {sorted(fontes_d)}")
    print(f"  espacamentos: {esp} (gabarito {[round(x) for x in r['espacamentos_distintos_mm']]})")
    print("  RESULTADO:", "OK, bate com o gabarito" if ok else "DIVERGE")
    return ok


if __name__ == "__main__":
    resultados = [analisar(p) for p in sorted(PASTA.glob("*.ifc"))]
    print(f"\n{sum(resultados)}/{len(resultados)} modelos batem com o gabarito")

    # --- extra: por que 'posicao' precisa de uma convencao (modelo D)
    d = PASTA / "viga_D_buildingsmart_estribos.ifc"
    if d.exists():
        m = ifcopenshell.open(str(d))
        p = m.by_type("IfcBuildingElementProxy")[0]
        origem_y = p.Representation.Representations[0].Items[0].MappingTarget.LocalOrigin.Coordinates[1]
        bmin, bmax = caixa_mundo(p)
        print(f"\nModelo D, 1o estribo: origem do mapeamento y = {origem_y:.1f} mm | "
              f"centro da caixa y = {(bmin[1] + bmax[1]) / 2:.1f} mm (diferenca {(bmin[1] + bmax[1]) / 2 - origem_y:.1f} mm)")
        print("-> o ESPACAMENTO nao muda, mas a posicao absoluta depende da convencao escolhida.")