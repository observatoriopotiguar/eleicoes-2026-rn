"""Mapas do RN com o candidato mais votado em cada município, para Presidente e Governador.

Gera dois mapas por cargo:
    mapa_<cargo>_rn.png         cor do partido vencedor (demais partidos em cinza)
    mapa_<cargo>_margem_rn.png  mesma cor, mais escura quanto maior a vantagem sobre o 2º colocado

Cores: Presidente — PT vermelho, PL azul. Governador — PT vermelho, UNIÃO azul, PL verde.

Lê candidatos_municipio.csv gerado por baixar_eleicao_rn.py; a malha municipal vem da API do IBGE.

Uso:
    python3 grafico_mapas_rn.py                       # presidente e governador
    python3 grafico_mapas_rn.py --cargo governador
    python3 grafico_mapas_rn.py --turno 2
"""
import argparse
import gzip
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.collections import PatchCollection
from matplotlib.patches import Patch, Polygon

DADOS = Path(__file__).resolve().parents[1] / 'dados'
URL_MALHA = ('https://servicodados.ibge.gov.br/api/v3/malhas/estados/24'
             '?intrarregiao=municipio&formato=application/vnd.geo%2Bjson&qualidade=intermediaria')
COR_OUTROS = '#A6A6A6'
FUNDO = '#FFFFFF'

# Faixas de vantagem do 1º sobre o 2º colocado, em pontos percentuais dos votos válidos.
FAIXAS = [(0, 10), (10, 20), (20, 40), (40, 60), (60, 100)]
# Cada cor tem uma rampa, do claro (disputa apertada) ao escuro (vitória folgada).
# O índice 3 é a cor cheia usada no mapa só de vencedor.
# O verde é amarelado de propósito: o verde escuro se confunde com o vermelho para daltônicos.
RAMPAS = {
    'vermelho': ['#F5C6C0', '#EC9187', '#DA5446', '#C62828', '#7A0F0F'],
    'azul': ['#C9D6EE', '#93AEDD', '#5A83C6', '#1F4E9C', '#0F2D61'],
    'verde': ['#DCEBCB', '#B5D493', '#89BA5E', '#5E9E2E', '#3A6619'],
}
CARGOS = {
    'presidente': {'id': 1, 'nome': 'Presidente', 'cores': {'PT': 'vermelho', 'PL': 'azul'}},
    'governador': {'id': 3, 'nome': 'Governador', 'cores': {'PT': 'vermelho', 'UNIÃO': 'azul', 'PL': 'verde'}},
}
# Municípios sempre rotulados. Também são rotulados os vencidos por partidos que ganharam
# em poucos municípios (até RARO), que se perderiam no mapa.
DESTAQUES = {'2408102': 'Natal', '2408003': 'Mossoró'}
RARO = 5


def carregar_malha():
    caminho = DADOS / 'malha_rn_municipios.geojson'
    if not caminho.exists():
        req = Request(URL_MALHA, headers={'User-Agent': 'ObservatorioPotiguar/1.0'})
        with urlopen(req, timeout=60) as resposta:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            conteudo = resposta.read()
            if conteudo[:2] == b'\x1f\x8b':  # a API do IBGE às vezes responde em gzip
                conteudo = gzip.decompress(conteudo)
            caminho.write_bytes(conteudo)
    return json.loads(caminho.read_text(encoding='utf-8'))


def aneis_externos(geometria):
    if geometria['type'] == 'Polygon':
        return [geometria['coordinates'][0]]
    return [poligono[0] for poligono in geometria['coordinates']]


def area(anel):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(anel, anel[1:] + anel[:1]))) / 2


def vencedores(turno, id_cargo, cores):
    """Uma linha por município: candidato mais votado e vantagem (p.p.) sobre o 2º colocado."""
    df = pd.read_csv(DADOS / '2026' / f'turno_{turno}' / 'candidatos_municipio.csv',
                     dtype={'id_municipio_ibge': str})
    cargo = df[df['id_cargo'] == id_cargo].sort_values('votos', ascending=False)
    primeiro = cargo.groupby('id_municipio_ibge').nth(0).set_index('id_municipio_ibge')
    segundo = cargo.groupby('id_municipio_ibge').nth(1).set_index('id_municipio_ibge')
    venc = primeiro.copy()
    venc['margem'] = primeiro['percentual'] - segundo['percentual'].reindex(primeiro.index).fillna(0)
    venc['grupo'] = venc['sigla_partido'].where(venc['sigla_partido'].isin(cores), 'Outros')
    return venc


def faixa(margem):
    return next(i for i, (_, fim) in enumerate(FAIXAS) if margem < fim or fim == FAIXAS[-1][1])


def desenhar(malha, cor_de, rotulos, legenda, titulo_legenda, titulo, data, saida, ncol=1):
    """cor_de: código IBGE -> cor. rotulos: código IBGE -> texto."""
    fig, ax = plt.subplots(figsize=(11, 6.6), facecolor=FUNDO)
    patches, cores, pontos = [], [], []
    for feature in malha['features']:
        codigo = feature['properties']['codarea']
        aneis = aneis_externos(feature['geometry'])
        for anel in aneis:
            patches.append(Polygon(anel, closed=True))
            cores.append(cor_de.get(codigo, '#EEEEEE'))
        if codigo in rotulos:
            maior = max(aneis, key=area)
            x = sum(p[0] for p in maior) / len(maior)
            y = sum(p[1] for p in maior) / len(maior)
            pontos.append((x, y, rotulos[codigo]))

    ax.add_collection(PatchCollection(patches, facecolor=cores, edgecolor=FUNDO, linewidth=0.5))
    ax.autoscale_view()

    # Empurra cada rótulo para fora do estado, na direção oposta ao centro do mapa;
    # rótulos vizinhos no mesmo lado são espaçados na vertical para não se sobreporem.
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    usados = []
    for x, y, texto in sorted(pontos, key=lambda p: -p[1]):
        dx, dy = x - cx, y - cy
        norma = math.hypot(dx, dy) or 1
        ox, oy = 45 * dx / norma, 45 * dy / norma
        while any(abs(ox - ux) < 120 and abs(oy - uy) < 34 and abs(x - xx) < 0.6
                  for ux, uy, xx in usados):
            oy -= 34
        usados.append((ox, oy, x))
        ax.annotate(texto, (x, y), xytext=(ox, oy), textcoords='offset points',
                    ha='left' if ox > 10 else 'right' if ox < -10 else 'center',
                    va='bottom' if oy > 10 else 'top' if oy < -10 else 'center',
                    fontsize=9, color='#333333', linespacing=1.3,
                    arrowprops={'arrowstyle': '-', 'color': '#555555', 'linewidth': 0.7})

    ax.set_aspect(1 / math.cos(math.radians(-5.8)))  # corrige a distorção lat/lon na latitude do RN
    ax.axis('off')
    # Legenda abaixo do mapa, para não cobrir municípios; fonte logo abaixo da legenda.
    leg = ax.legend(handles=legenda, title=titulo_legenda, loc='upper left', bbox_to_anchor=(0, 0),
                    ncol=ncol, columnspacing=2.5,
                    frameon=False, fontsize=10, labelcolor='#333333', handlelength=1.2, handleheight=1.2,
                    title_fontsize=10, alignment='left')
    leg.get_title().set_color('#333333')
    ax.set_title(titulo, loc='left', fontsize=15, color='#1A1A1A', pad=14)
    fig.canvas.draw()
    base_legenda = ax.transAxes.inverted().transform(leg.get_window_extent())[0][1]
    ax.text(0, base_legenda - 0.03, f'Fonte: TSE (resultados oficiais, {data}); malha municipal IBGE.',
            transform=ax.transAxes, fontsize=8.5, color='#666666', va='top')
    fig.savefig(saida, dpi=200, bbox_inches='tight', facecolor=FUNDO)
    plt.close(fig)
    print(f'Salvo: {saida}')


def municipios(n):
    return f"{n} município{'s' if n != 1 else ''}"


def fmt(margem):
    return f'{margem:+.1f}'.replace('.', ',')


def mapas_do_cargo(chave, turno, malha):
    cargo = CARGOS[chave]
    cores = cargo['cores']
    venc = vencedores(turno, cargo['id'], cores)
    pasta = DADOS / '2026' / f'turno_{turno}'
    data = venc['data_hora_totalizacao'].iloc[0]
    contagem = venc['grupo'].value_counts()
    # Partidos na ordem de municípios vencidos; "Outros" sempre por último.
    grupos = [g for g in contagem.index if g != 'Outros'] + (['Outros'] if 'Outros' in contagem else [])
    nomes = venc.groupby('grupo')['nome_urna'].agg(lambda s: s.mode().iat[0].title())
    nome_grupo = {g: (f'{nomes[g]} ({g})' if g in cores else 'Outros partidos') for g in grupos}

    def cor_cheia(grupo):
        return RAMPAS[cores[grupo]][3] if grupo in cores else COR_OUTROS

    raros = {g for g in grupos if contagem[g] <= RARO}
    destacar = [c for c, l in venc.iterrows() if l['grupo'] in raros or c in DESTAQUES]

    # Mapa 1: só o vencedor.
    legenda = [Patch(facecolor=cor_cheia(g), edgecolor='none',
                     label=f'{nome_grupo[g]} — {municipios(int(contagem[g]))}') for g in grupos]
    rotulos = {c: f"{venc.at[c, 'municipio'].title()}\n{venc.at[c, 'nome_urna'].title()}" for c in destacar}
    desenhar(malha, {c: cor_cheia(g) for c, g in venc['grupo'].items()}, rotulos, legenda, None,
             f"Mais votado para {cargo['nome']} por município — RN, {turno}º turno 2026", data,
             pasta / f'mapa_{chave}_rn.png')

    # Mapa 2: vencedor + tamanho da vantagem sobre o 2º colocado. Uma coluna da legenda por partido.
    venc['faixa'] = venc['margem'].map(faixa)
    cor_de = {c: RAMPAS[cores[l['grupo']]][l['faixa']] if l['grupo'] in cores else COR_OUTROS
              for c, l in venc.iterrows()}
    colunas = []
    for g in grupos:
        if g == 'Outros':
            colunas.append([Patch(facecolor=COR_OUTROS, edgecolor='none',
                                  label=f'Outros partidos — {municipios(int(contagem[g]))}')])
            continue
        coluna = []
        for i, (ini, fim) in enumerate(FAIXAS):
            n = int(((venc['grupo'] == g) & (venc['faixa'] == i)).sum())
            if n:
                faixa_txt = f'+{ini} a {fim}' if fim < 100 else f'+{ini} ou mais'
                # Rótulo curto (sigla): com 3 partidos, o nome completo alarga a legenda e encolhe o mapa.
                coluna.append(Patch(facecolor=RAMPAS[cores[g]][i], edgecolor='none',
                                    label=f'{g} {faixa_txt} — {municipios(n)}'))
        colunas.append(coluna)
    # Completa as colunas com itens invisíveis para cada partido ficar na sua coluna.
    altura = max(len(c) for c in colunas)
    legenda = [item for c in colunas
               for item in c + [Patch(facecolor='none', edgecolor='none', label='')] * (altura - len(c))]
    rotulos = {c: f"{venc.at[c, 'municipio'].title()}\n{venc.at[c, 'sigla_partido']} {fmt(venc.at[c, 'margem'])} p.p."
               for c in destacar}
    desenhar(malha, cor_de, rotulos, legenda,
             'Vantagem do 1º sobre o 2º colocado\n(pontos percentuais dos votos válidos)',
             f"Margem de vitória para {cargo['nome']} por município — RN, {turno}º turno 2026", data,
             pasta / f'mapa_{chave}_margem_rn.png', ncol=len(colunas))
    print(contagem.to_string())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--turno', choices=['1', '2'], default='1')
    parser.add_argument('--cargo', choices=list(CARGOS), help='Padrão: todos')
    args = parser.parse_args()
    malha = carregar_malha()
    for chave in [args.cargo] if args.cargo else CARGOS:
        mapas_do_cargo(chave, args.turno, malha)


if __name__ == '__main__':
    main()
