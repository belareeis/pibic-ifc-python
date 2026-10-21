"""
Gerador parametrico de modelos IFC4 de vigas de concreto armado (IfcBeam + IfcReinforcingBar)
com gabarito (ground truth) em JSON.

Unidades: mm Eixo X = comprimento da viga; secao transversal no plano YZ,
centrada na origem.

"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.api.context
import ifcopenshell.api.aggregate
import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.material
import ifcopenshell.api.spatial

AREA = lambda d: math.pi * d * d / 4.0           # mm2
PESO = lambda d, L: AREA(d) * L * 7.85e-6        # kg (aco 7850 kg/m3)


# geometria de barras (diretriz = IfcIndexedPolyCurve, secao = disco circular)
class Path3D:
    """Caminho 3D com segmentos de reta e arcos de 90 graus; guarda o comprimento analitico."""

    def __init__(self, p0):
        self.pts = [tuple(float(c) for c in p0)]
        self.segs = []
        self.length = 0.0

    def line(self, p):
        a = len(self.pts)  # indice (base 1) do ultimo ponto
        p = tuple(float(c) for c in p)
        self.length += math.dist(self.pts[-1], p)
        self.pts.append(p)
        self.segs.append(("L", a, a + 1))

    def arc(self, mid, end, radius):
        a = len(self.pts)
        self.pts += [tuple(float(c) for c in mid), tuple(float(c) for c in end)]
        self.segs.append(("A", a, a + 1, a + 2))
        self.length += radius * math.pi / 2.0

    def to_ifc(self, f):
        pl = f.createIfcCartesianPointList3D(CoordList=self.pts)
        segs = []
        for s in self.segs:
            if s[0] == "L":
                segs.append(f.createIfcLineIndex(s[1:]))
            else:
                segs.append(f.createIfcArcIndex(s[1:]))
        return f.createIfcIndexedPolyCurve(Points=pl, Segments=segs, SelfIntersect=False)


def caminho_reto(x0, x1, y, z):
    p = Path3D((x0, y, z))
    p.line((x1, y, z))
    return p


def caminho_estribo(x, yL, yR, zB, zT, r, d):
    """Estribo retangular fechado com cantos arredondados (raio de eixo r), sem ganchos.
    Abre-se uma folga de 1*d na aresta superior para o caminho nao se autotocar."""
    s = 0.70710678
    p = Path3D((x, yL + r + 2 * d, zT))
    p.line((x, yR - r, zT))
    # canto superior direito
    c = (yR - r, zT - r)
    p.arc((x, c[0] + r * s, c[1] + r * s), (x, yR, zT - r), r)
    p.line((x, yR, zB + r))
    # canto inferior direito
    c = (yR - r, zB + r)
    p.arc((x, c[0] + r * s, c[1] - r * s), (x, yR - r, zB), r)
    p.line((x, yL + r, zB))
    # canto inferior esquerdo
    c = (yL + r, zB + r)
    p.arc((x, c[0] - r * s, c[1] - r * s), (x, yL, zB + r), r)
    p.line((x, yL, zT - r))
    # canto superior esquerdo
    c = (yL + r, zT - r)
    p.arc((x, c[0] - r * s, c[1] + r * s), (x, yL + r, zT), r)
    p.line((x, yL + r + d, zT))
    return p


# definindo os modleos
def posicoes_estribos(L, primeiro, zona_ext, esp_ext, esp_meio):
    """Estribos adensados nas pontas (zona_ext, esp_ext) e esp_meio no vao central."""
    esq = []
    x = primeiro
    while x <= primeiro + zona_ext + 1e-6:
        esq.append(x)
        x += esp_ext
    meio = []
    x = esq[-1] + esp_meio
    limite = L - esq[-1] - esp_meio
    while x <= limite + 1e-6:
        meio.append(x)
        x += esp_meio
    dir_ = [L - v for v in reversed(esq)]
    return esq + meio + dir_


def posicoes_uniformes(L, primeiro, esp):
    xs, x = [], primeiro
    while x <= L - primeiro + 1e-6:
        xs.append(x)
        x += esp
    return xs


MODELOS = {
    # A: estribos uniformes, atributos completos
    "viga_A_estribos_uniformes": dict(
        L=4000, w=200, h=400, cobrimento=25,
        estribo=dict(d=5.0, aco="CA-60", xs=lambda L: posicoes_uniformes(L, 50, 150)),
        grupos=[
            dict(papel="SUP_CONTINUA", n=2, d=8.0, aco="CA-50", camada="topo", x0=30, x1=lambda L: L - 30),
            dict(papel="INF_PRINCIPAL", n=3, d=12.5, aco="CA-50", camada="base", x0=30, x1=lambda L: L - 30),
        ],
        atributos=True,
    ),
    # B: estribos adensados nas pontas + reforcos (parecido com a foto)
    "viga_B_estribos_adensados": dict(
        L=3100, w=200, h=400, cobrimento=25,
        estribo=dict(d=5.0, aco="CA-60", xs=lambda L: posicoes_estribos(L, 50, 400, 80, 200)),
        grupos=[
            dict(papel="SUP_CONTINUA", n=2, d=10.0, aco="CA-50", camada="topo", x0=30, x1=lambda L: L - 30),
            dict(papel="SUP_APOIO_ESQ", n=2, d=12.5, aco="CA-50", camada="topo2", x0=30, x1=lambda L: 830),
            dict(papel="SUP_APOIO_DIR", n=2, d=12.5, aco="CA-50", camada="topo2", x0=lambda L: L - 830, x1=lambda L: L - 30),
            dict(papel="INF_PRINCIPAL", n=3, d=16.0, aco="CA-50", camada="base", x0=30, x1=lambda L: L - 30),
            dict(papel="INF_REFORCO", n=2, d=12.5, aco="CA-50", camada="base2", x0=lambda L: L / 2 - 1000, x1=lambda L: L / 2 + 1000),
        ],
        atributos=True,
    ),
    # C: secao maior, SEM atributos (so geometria) -> caso dificil para a extracao
    "viga_C_somente_geometria": dict(
        L=5100, w=250, h=500, cobrimento=30,
        estribo=dict(d=8.0, aco="CA-50", xs=lambda L: posicoes_estribos(L, 50, 600, 100, 200)),
        grupos=[
            dict(papel="SUP_CONTINUA", n=2, d=12.5, aco="CA-50", camada="topo", x0=30, x1=lambda L: L - 30),
            dict(papel="INF_PRINCIPAL", n=2, d=20.0, aco="CA-50", camada="base", x0=30, x1=lambda L: L - 30),
            dict(papel="INF_PRINCIPAL", n=2, d=16.0, aco="CA-50", camada="base2", x0=30, x1=lambda L: L - 30),
        ],
        atributos=False,
    ),
}


def val(v, L):
    return v(L) if callable(v) else v


# construindo o IFC
def gerar(nome, cfg, pasta):
    f = ifcopenshell.api.project.create_file(version="IFC4")
    proj = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name=nome)
    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "MILLIMETERS"})
    ctx = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)

    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Terreno")
    bld = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Edificio")
    sto = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Pavimento 1")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=proj)
    ifcopenshell.api.aggregate.assign_object(f, products=[bld], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[sto], relating_object=bld)

    L, w, h, cob = cfg["L"], cfg["w"], cfg["h"], cfg["cobrimento"]
    I = np.eye(4)

    # viga 
    beam = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBeam", name="V1", predefined_type="BEAM")
    perfil = f.createIfcRectangleProfileDef(
        "AREA", f"{w}x{h}", f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0))), float(w), float(h))
    pos = f.createIfcAxis2Placement3D(
        f.createIfcCartesianPoint((0.0, 0.0, 0.0)),
        f.createIfcDirection((1.0, 0.0, 0.0)), f.createIfcDirection((0.0, 1.0, 0.0)))
    solido = f.createIfcExtrudedAreaSolid(perfil, pos, f.createIfcDirection((0.0, 0.0, 1.0)), float(L))
    rep = f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solido])
    ifcopenshell.api.geometry.assign_representation(f, product=beam, representation=rep)
    ifcopenshell.api.geometry.edit_object_placement(f, product=beam, matrix=I)

    # conjunto da armadura
    conj = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcElementAssembly", name="Armadura V1", predefined_type="REINFORCEMENT_UNIT")
    ifcopenshell.api.geometry.edit_object_placement(f, product=conj, matrix=I)

    materiais = {}

    def criar_barra(path, d, aco, papel_ifc, nome_barra):
        bar = ifcopenshell.api.root.create_entity(
            f, ifc_class="IfcReinforcingBar", name=nome_barra if cfg["atributos"] else "Barra",
            predefined_type=papel_ifc if cfg["atributos"] else "NOTDEFINED")
        if cfg["atributos"]:
            bar.NominalDiameter = float(d)
            bar.CrossSectionArea = AREA(d)
            bar.BarLength = round(path.length, 3)
            bar.SteelGrade = aco
            bar.BarSurface = "TEXTURED"
            qto = ifcopenshell.api.pset.add_qto(f, product=bar, name="Qto_ReinforcingElementBaseQuantities")
            ifcopenshell.api.pset.edit_qto(f, qto=qto, properties={
                "Count": 1, "Length": round(path.length, 3), "Weight": round(PESO(d, path.length), 4)})
        solid = f.createIfcSweptDiskSolid(path.to_ifc(f), d / 2.0)
        r = f.createIfcShapeRepresentation(body, "Body", "AdvancedSweptSolid", [solid])
        ifcopenshell.api.geometry.assign_representation(f, product=bar, representation=r)
        ifcopenshell.api.geometry.edit_object_placement(f, product=bar, matrix=I)
        if cfg["atributos"]:
            if aco not in materiais:
                materiais[aco] = ifcopenshell.api.material.add_material(f, name=aco, category="steel")
            ifcopenshell.api.material.assign_material(f, products=[bar], material=materiais[aco])
        return bar

    barras, gt_barras = [], []
    est = cfg["estribo"]
    d_e = est["d"]

    # estribos
    yL, yR = -w / 2 + cob + d_e / 2, w / 2 - cob - d_e / 2
    zB, zT = -h / 2 + cob + d_e / 2, h / 2 - cob - d_e / 2
    xs = est["xs"](L)
    for i, x in enumerate(xs, 1):
        p = caminho_estribo(x, yL, yR, zB, zT, 3 * d_e, d_e)
        b = criar_barra(p, d_e, est["aco"], "LIGATURE", f"Estribo E{i:02d} d{d_e}")
        barras.append(b)
        gt_barras.append(dict(
            global_id=b.GlobalId, papel="ESTRIBO", diametro_mm=d_e, aco=est["aco"],
            comprimento_mm=round(p.length, 3), x_mm=x, quantidade=1))

    # longitudinais
    cam_z = {}
    d_top = None
    for g in cfg["grupos"]:
        d = g["d"]
        z_topo = h / 2 - cob - d_e - d / 2
        z_base = -h / 2 + cob + d_e + d / 2
        if g["camada"] == "topo":
            z, d_top = z_topo, d
        elif g["camada"] == "topo2":
            z = z_topo - (d_top or 10.0) / 2 - 25 - d / 2
        elif g["camada"] == "base":
            z = z_base
            cam_z["base"] = (z, d)
        else:  # base2
            z0, d0 = cam_z["base"]
            z = z0 + d0 / 2 + 25 + d / 2
        y_ext = w / 2 - cob - d_e - d / 2
        ys = [-y_ext + k * (2 * y_ext) / (g["n"] - 1) for k in range(g["n"])]
        x0, x1 = val(g["x0"], L), val(g["x1"], L)
        for k, y in enumerate(ys, 1):
            p = caminho_reto(x0, x1, y, z)
            b = criar_barra(p, d, g["aco"], "MAIN", f"{g['papel']} {k} d{d}")
            barras.append(b)
            gt_barras.append(dict(
                global_id=b.GlobalId, papel=g["papel"], diametro_mm=d, aco=g["aco"],
                comprimento_mm=round(p.length, 3), x_inicio_mm=x0, x_fim_mm=x1,
                y_mm=round(y, 3), z_mm=round(z, 3), quantidade=1))

    ifcopenshell.api.aggregate.assign_object(f, products=barras, relating_object=conj)
    ifcopenshell.api.spatial.assign_container(f, products=[beam, conj], relating_structure=sto)

    # gabarito
    espacamentos = [round(b - a, 3) for a, b in zip(xs, xs[1:])]
    gt = dict(
        modelo=nome, unidades="mm",
        viga=dict(comprimento=L, largura=w, altura=h, cobrimento=cob),
        resumo=dict(
            total_barras=len(gt_barras),
            n_estribos=len(xs),
            n_longitudinais=len(gt_barras) - len(xs),
            diametro_estribo_mm=d_e,
            espacamentos_distintos_mm=sorted(set(espacamentos)),
            comprimento_total_aco_m=round(sum(b["comprimento_mm"] for b in gt_barras) / 1000, 3),
            peso_total_kg=round(sum(PESO(b["diametro_mm"], b["comprimento_mm"]) for b in gt_barras), 2),
        ),
        estribos_x_mm=xs,
        estribos_espacamentos_mm=espacamentos,
        barras=gt_barras,
        observacoes=[
            "Estribos sem ganchos de 135 graus (simplificacao).",
            "Comprimentos calculados analiticamente ao longo do eixo da barra (retas + arcos).",
        ] + ([] if cfg["atributos"] else [
            "Este modelo NAO tem NominalDiameter/BarLength/psets: so a geometria (raio do disco) carrega os dados."]),
    )
    pasta.mkdir(parents=True, exist_ok=True)
    f.write(str(pasta / f"{nome}.ifc"))
    (pasta / f"{nome}_gabarito.json").write_text(json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")
    return gt


if __name__ == "__main__":
    saida = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "modelos"
    for nome, cfg in MODELOS.items():
        gt = gerar(nome, cfg, saida)
        r = gt["resumo"]
        print(f"{nome}: {r['total_barras']} barras ({r['n_estribos']} estribos, "
              f"{r['n_longitudinais']} longitudinais), espacamentos {r['espacamentos_distintos_mm']} mm")