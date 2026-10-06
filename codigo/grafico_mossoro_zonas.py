"""Gráfico de Mossoró por zona eleitoral: percentual dos votos válidos de cada candidato.

Um painel por zona e um para o total do município, com a vantagem do 1º sobre o 2º anotada.
Mesmas cores dos mapas (grafico_mapas_rn.py). Candidatos fora do top 3 vão para "Outros".

Uso:
    python3 grafico_mossoro_zonas.py                    # governador
    python3 grafico_mossoro_zonas.py --cargo presidente
"""
import argparse

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from grafico_mapas_rn import CARGOS, COR_OUTROS, DADOS, FUNDO, RAMPAS, fmt

MUNICIPIO_TSE = '17590'  # Mossoró
TOP = 3


def carregar(turno, id_cargo):
    pasta = DADOS / '2026' / f'turno_{turno}'
    tipos = {'id_municipio_tse': str, 'zona': str}
    zona = pd.read_csv(pasta / 'candidatos_zona.csv', dtype=tipos)
    mun = pd.read_csv(pasta / 'candidatos_municipio.csv', dtype=tipos)
    zona = zona[(zona['id_municipio_tse'] == MUNICIPIO_TSE) & (zona['id_cargo'] == id_cargo)]
    mun = mun[(mun['id_municipio_tse'] == MUNICIPIO_TSE) & (mun['id_cargo'] == id_cargo)]
    mun = mun.assign(zona='Total')
    validos = {
        **pd.read_csv(pasta / 'resumo_zona.csv', dtype=tipos)
            .query('id_municipio_tse == @MUNICIPIO_TSE and id_cargo == @id_cargo')
            .set_index('zona')['votos_validos'].to_dict(),
        'Total': pd.read_csv(pasta / 'resumo_municipio.csv', dtype=tipos)
            .query('id_municipio_tse == @MUNICIPIO_TSE and id_cargo == @id_cargo')['votos_validos'].iat[0],
    }
    return pd.concat([zona, mun]), validos


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--turno', choices=['1', '2'], default='1')
    parser.add_argument('--cargo', choices=list(CARGOS), default='governador')
    args = parser.parse_args()
    cargo = CARGOS[args.cargo]

    df, validos = carregar(args.turno, cargo['id'])
    # Ordem fixa dos candidatos (pelo total do município), igual em todos os painéis.
    ordem_total = df[df['zona'] == 'Total'].sort_values('votos', ascending=False)
    principais = ordem_total['sequencial_candidato'].head(TOP).tolist()
    rotulo = {r['sequencial_candidato']: f"{r['nome_urna'].title()} ({r['sigla_partido']})"
              for _, r in ordem_total.iterrows()}
    cor = {r['sequencial_candidato']: RAMPAS[cargo['cores'][r['sigla_partido']]][3]
           if r['sigla_partido'] in cargo['cores'] else COR_OUTROS for _, r in ordem_total.iterrows()}
    categorias = [rotulo[s] for s in principais] + ['Outros']
    cores = [cor[s] for s in principais] + [COR_OUTROS]

    areas = sorted(z for z in df['zona'].unique() if z != 'Total') + ['Total']
    fig, eixos = plt.subplots(1, len(areas), figsize=(4.2 * len(areas), 3.6), sharey=True, facecolor=FUNDO)
    xmax = df['percentual'].max() * 1.22
    for ax, area in zip(eixos, areas):
        parte = df[df['zona'] == area].sort_values('votos', ascending=False)
        pct = parte.set_index('sequencial_candidato')['percentual']
        valores = [pct.get(s, 0) for s in principais] + [pct.drop(principais, errors='ignore').sum()]
        y = range(len(categorias))
        ax.barh(y, valores, color=cores, height=0.62)
        for yi, v in zip(y, valores):
            ax.text(v + xmax * 0.015, yi, f'{v:.1f}%'.replace('.', ','), va='center',
                    fontsize=10, color='#333333')

        primeiro, segundo = parte.iloc[0], parte.iloc[1]
        titulo = 'Mossoró (total)' if area == 'Total' else f'Zona {int(area)}'
        ax.set_title(f'{titulo}\n', loc='left', fontsize=12.5, color='#1A1A1A', fontweight='bold')
        n_validos = f'{int(validos[area]):,}'.replace(',', '.')
        ax.text(0, 1.02, f"{primeiro['nome_urna'].title()} {fmt(primeiro['percentual'] - segundo['percentual'])} p.p."
                         f' · {n_validos} votos válidos',
                transform=ax.transAxes, fontsize=9.5, color='#555555')

        ax.set_xlim(0, xmax)
        ax.tick_params(length=0, labelsize=10, colors='#333333')
        ax.set_xticks([])
        for lado in ('top', 'right', 'bottom'):
            ax.spines[lado].set_visible(False)
        ax.spines['left'].set_color('#BBBBBB')
        ax.set_facecolor(FUNDO)
    eixos[0].set_yticks(range(len(categorias)), categorias)
    eixos[0].invert_yaxis()  # eixo y compartilhado: inverte uma vez para o 1º colocado ficar no topo

    data = df['data_hora_totalizacao'].iloc[0]
    fig.suptitle(f"{cargo['nome']} em Mossoró por zona eleitoral — {args.turno}º turno 2026",
                 x=0.01, ha='left', fontsize=15, color='#1A1A1A')
    fig.text(0.01, -0.02, f'Percentual dos votos válidos. Fonte: TSE (resultados oficiais, {data}).',
             fontsize=8.5, color='#666666')
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    saida = DADOS / '2026' / f'turno_{args.turno}' / f'mossoro_zonas_{args.cargo}.png'
    fig.savefig(saida, dpi=200, bbox_inches='tight', facecolor=FUNDO)
    print(f'Salvo: {saida}')


if __name__ == '__main__':
    main()
