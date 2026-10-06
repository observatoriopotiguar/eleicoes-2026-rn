"""Mapa de um município com um ponto por local de votação, colorido pela vantagem do 1º colocado.

Cor = partido do mais votado no local (mesmas cores dos mapas estaduais), mais escura quanto maior
a vantagem sobre o 2º; tamanho = votos válidos no local. Painel da esquerda: município inteiro;
da direita: zoom na área urbana (locais fora da "ZONA RURAL").

Lê votos_local_votacao.csv e locais_votacao.csv gerados por baixar_locais_votacao_rn.py.

Uso:
    python3 grafico_locais_votacao.py                         # Mossoró, governador
    python3 grafico_locais_votacao.py --cargo presidente
    python3 grafico_locais_votacao.py --municipio NATAL
"""
import argparse
import math
import unicodedata

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.collections import PatchCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon, Rectangle

from grafico_mapas_rn import CARGOS, COR_OUTROS, DADOS, FUNDO, RAMPAS, aneis_externos, carregar_malha, fmt

# Faixas mais finas que as do mapa estadual: entre locais de um mesmo município a variação é menor.
FAIXAS = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 100)]


def carregar(turno, municipio, id_cargo):
    pasta = DADOS / '2026' / f'turno_{turno}'
    tipos = {'id_municipio_tse': str, 'zona': str, 'numero_local': str}
    votos = pd.read_csv(pasta / 'votos_local_votacao.csv', dtype=tipos)
    locais = pd.read_csv(pasta / 'locais_votacao.csv', dtype=tipos)
    votos = votos[(votos['municipio'] == municipio) & (votos['id_cargo'] == id_cargo)
                  & votos['tipo_voto'].isin(['nominal', 'legenda'])]
    if votos.empty:
        raise SystemExit(f'Sem votos para {municipio}. Use o nome como no TSE, ex.: MOSSORÓ, NATAL.')
    chave = ['zona', 'numero_local']
    ordenado = votos[votos['tipo_voto'] == 'nominal'].sort_values('votos', ascending=False)
    primeiro = ordenado.groupby(chave).nth(0).set_index(chave)
    segundo = ordenado.groupby(chave).nth(1).set_index(chave)
    resumo = primeiro[['nome_urna', 'sigla_partido', 'percentual', 'votos_validos_local']].copy()
    resumo['margem'] = primeiro['percentual'] - segundo['percentual'].reindex(primeiro.index).fillna(0)
    locais = locais[locais['municipio'] == municipio].set_index(chave)
    return resumo.join(locais[['nome_local', 'bairro', 'latitude', 'longitude', 'id_municipio_tse']]).reset_index()


def faixa(margem):
    return next(i for i, (_, fim) in enumerate(FAIXAS) if margem < fim or fim == FAIXAS[-1][1])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--turno', choices=['1', '2'], default='1')
    parser.add_argument('--cargo', choices=list(CARGOS), default='governador')
    parser.add_argument('--municipio', default='MOSSORÓ')
    args = parser.parse_args()
    cargo = CARGOS[args.cargo]
    cores = cargo['cores']

    df = carregar(args.turno, args.municipio, cargo['id'])
    sem_coord = df['latitude'].isna().sum()
    df = df.dropna(subset=['latitude', 'longitude'])
    df['faixa'] = df['margem'].map(faixa)
    df['cor'] = [RAMPAS[cores[p]][f] if p in cores else COR_OUTROS for p, f in zip(df['sigla_partido'], df['faixa'])]
    maximo = df['votos_validos_local'].max()
    df['tamanho'] = 12 + 330 * df['votos_validos_local'] / maximo  # área do ponto ∝ votos válidos
    df = df.sort_values('votos_validos_local', ascending=False)  # pontos grandes por baixo

    # Contorno do município (malha IBGE); o código IBGE vem do cadastro de candidatos/município.
    malha = carregar_malha()
    pasta = DADOS / '2026' / f'turno_{args.turno}'
    mun = pd.read_csv(pasta / 'candidatos_municipio.csv', dtype=str)
    cd_ibge = mun.loc[mun['municipio'] == args.municipio, 'id_municipio_ibge'].iat[0]
    feature = next(f for f in malha['features'] if f['properties']['codarea'] == cd_ibge)

    urbano = df[df['bairro'].str.upper() != 'ZONA RURAL']
    fig, (ax_mun, ax_urb) = plt.subplots(1, 2, figsize=(14, 7.6), facecolor=FUNDO,
                                         gridspec_kw={'width_ratios': [1, 1.35]})
    aspecto = 1 / math.cos(math.radians(df['latitude'].mean()))
    for ax in (ax_mun, ax_urb):
        contorno = [Polygon(anel, closed=True) for anel in aneis_externos(feature['geometry'])]
        ax.add_collection(PatchCollection(contorno, facecolor='#F2F2F0', edgecolor='#BBBBBB', linewidth=0.8))
        ax.scatter(df['longitude'], df['latitude'], s=df['tamanho'], c=df['cor'],
                   edgecolor=FUNDO, linewidth=0.8, zorder=3)
        ax.set_aspect(aspecto)
        ax.axis('off')
    ax_mun.autoscale_view()

    # Zoom urbano: ignora os 4% de pontos mais afastados de cada lado (bairros periféricos isolados
    # achatariam o centro); retângulo no painel do município mostra a área ampliada.
    folga = 0.006
    x0, x1 = urbano['longitude'].quantile([0.04, 0.96]) + [-folga, folga]
    y0, y1 = urbano['latitude'].quantile([0.04, 0.96]) + [-folga, folga]
    ax_urb.set_xlim(x0, x1)
    ax_urb.set_ylim(y0, y1)
    ax_mun.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor='#555555',
                               linewidth=0.8, linestyle='--', zorder=4))
    ax_mun.set_title('Município inteiro', loc='left', fontsize=11, color='#333333')
    ax_urb.set_title('Área urbana', loc='left', fontsize=11, color='#333333')

    # Nome dos bairros com mais locais, no centro dos seus pontos, para orientar a leitura.
    bairros = urbano.groupby('bairro').agg(x=('longitude', 'mean'), y=('latitude', 'mean'), n=('nome_local', 'size'))
    for nome, b in bairros[bairros['n'] >= 4].iterrows():
        ax_urb.text(b['x'], b['y'], nome.title(), fontsize=8, color='#444444', ha='center', va='center',
                    zorder=5, bbox={'boxstyle': 'round,pad=0.15', 'facecolor': FUNDO, 'edgecolor': 'none', 'alpha': 0.7})

    # Legenda: cores por faixa (só as presentes) + tamanhos de referência.
    nome_partido = df.groupby('sigla_partido')['nome_urna'].agg(lambda s: s.mode().iat[0].title())
    itens = []
    for partido in df['sigla_partido'].value_counts().index:
        for i, (ini, fim) in enumerate(FAIXAS):
            n = int(((df['sigla_partido'] == partido) & (df['faixa'] == i)).sum())
            if n:
                texto = f'+{ini} a {fim}' if fim < 100 else f'+{ini} ou mais'
                cor = RAMPAS[cores[partido]][i] if partido in cores else COR_OUTROS
                itens.append(Patch(facecolor=cor, edgecolor='none',
                                   label=f"{nome_partido[partido]} ({partido}) {texto} p.p. — {n} locais"))
    referencias = [round(maximo, -3) // 4, round(maximo, -3) // 2, round(maximo, -3)]
    for v in referencias:
        itens.append(Line2D([], [], marker='o', linestyle='none', markerfacecolor='#BBBBBB', markeredgecolor='none',
                            markersize=math.sqrt(12 + 330 * v / maximo),
                            label=f"{int(v):,} votos válidos".replace(',', '.')))
    leg = fig.legend(handles=itens, title='Vantagem do 1º sobre o 2º colocado no local (pontos percentuais)',
                     loc='upper left', bbox_to_anchor=(0.01, 0.06), ncol=2, frameon=False, fontsize=9.5,
                     title_fontsize=10, labelcolor='#333333', alignment='left', columnspacing=2.5)
    leg.get_title().set_color('#333333')

    total_mun = mun[(mun['municipio'] == args.municipio) & (mun['id_cargo'] == str(cargo['id']))].copy()
    total_mun['votos'] = total_mun['votos'].astype(int)
    total_mun = total_mun.sort_values('votos', ascending=False)
    p1, p2 = total_mun.iloc[0], total_mun.iloc[1]
    margem_total = float(p1['percentual']) - float(p2['percentual'])
    fig.suptitle(f"{cargo['nome']} em {args.municipio.title()} por local de votação — {args.turno}º turno 2026",
                 x=0.01, y=0.99, ha='left', fontsize=15, color='#1A1A1A')
    fig.text(0.01, 0.935, f"{len(df)} locais · {p1['nome_urna'].title()} venceu no município por "
                          f"{fmt(margem_total)} p.p. sobre {p2['nome_urna'].title()}",
             fontsize=10.5, color='#555555')
    nota = f' {sem_coord} local(is) sem coordenada fora do mapa.' if sem_coord else ''
    fig.text(0.01, -0.13, 'Fonte: TSE — votação por seção e cadastro de locais de votação (Dados Abertos); '
                          f'malha municipal IBGE.{nota}', fontsize=8.5, color='#666666')
    fig.subplots_adjust(left=0.01, right=0.99, top=0.9, bottom=0.08, wspace=0.04)

    nome_arquivo = unicodedata.normalize('NFKD', args.municipio.lower()).encode('ascii', 'ignore').decode()
    nome_arquivo = nome_arquivo.replace(' ', '_')
    saida = pasta / f'locais_{nome_arquivo}_{args.cargo}.png'
    fig.savefig(saida, dpi=200, bbox_inches='tight', facecolor=FUNDO)
    print(f'Salvo: {saida}')
    print(df['faixa'].value_counts().sort_index().to_string())


if __name__ == '__main__':
    main()
