"""Baixa resultados oficiais do TSE para todos os municípios do RN, por município e por zona,
e monta DataFrames (pandas) prontos para análise.

Uso:
    python3 baixar_eleicao_rn.py
    python3 baixar_eleicao_rn.py --turno 2
    python3 baixar_eleicao_rn.py --atualizar      # baixa de novo arquivos já salvos
    python3 baixar_eleicao_rn.py --so-tratar      # só remonta as tabelas a partir dos JSONs salvos

Saída (padrão: dados/<ano>/turno_<n>/):
    json/                         JSONs originais do TSE (leiaute EA20)
    candidatos_municipio.csv      votos por candidato em cada município
    candidatos_zona.csv           votos por candidato em cada município+zona
    resumo_municipio.csv          eleitorado, comparecimento, abstenção, brancos, nulos...
    resumo_zona.csv               idem, por município+zona

Em notebook:
    from baixar_eleicao_rn import montar_dataframes
    dfs = montar_dataframes(Path('.../dados/2026/turno_1'))
    dfs['candidatos_zona'].head()
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

BASE = 'https://resultados.tse.jus.br'
AMBIENTE = 'oficial'
UF = 'rn'
CARGOS = {'1', '3', '5', '6', '7'}  # Presidente, Governador, Senador, Dep. Federal, Dep. Estadual
SAIDA_PADRAO = Path(__file__).resolve().parents[1] / 'dados'


def baixar_json(url):
    for tentativa in range(3):
        try:
            req = Request(url, headers={'User-Agent': 'DownloadResultadosTSE/1.0',
                                        'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
            with urlopen(req, timeout=60) as resposta:
                return json.loads(resposta.read().decode('utf-8-sig'))
        except HTTPError as erro:
            # 304 sem requisição condicional é falha esporádica da CDN do TSE: tenta de novo.
            if erro.code not in (304, 429, 500, 502, 503, 504) or tentativa == 2:
                raise
        except (URLError, TimeoutError):
            if tentativa == 2:
                raise
        time.sleep(2 * (tentativa + 1))


def salvar(dados, caminho):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf-8')


def diretorio(config, tipo, ciclo, eleicao):
    modelo = next(a['dir'] for a in config['arq'] if a['tp'] == tipo)
    for chave, valor in {'base': BASE, 'ambiente': AMBIENTE,
                         'ciclo': ciclo, 'cd_eleicao': str(eleicao), 'uf': UF}.items():
        modelo = modelo.replace(f'<{chave}>', valor)
    if '<' in modelo:
        raise ValueError(f'Tokens não resolvidos: {modelo}')
    return modelo.rstrip('/')


def selecionar_eleicoes(config, ano, turno):
    """Códigos de eleição e ciclo vêm do EA11, sem fixar IDs de eleições."""
    selecionadas = []
    for pleito in config['pl']:
        if pleito['c'] != f'ele{ano}':
            continue
        for eleicao in pleito['e']:
            if str(eleicao['t']) != turno or 'Ordinária' not in eleicao['nm']:
                continue
            cargos = {}
            for abrangencia in eleicao.get('abr', []):
                if abrangencia['cd'].lower() in ('br', UF):
                    for cargo in abrangencia.get('cp', []):
                        if str(cargo['cd']) in CARGOS:
                            cargos[str(cargo['cd'])] = cargo['ds']
            if cargos:
                selecionadas.append((pleito, eleicao, cargos))
    if not selecionadas:
        raise RuntimeError('Nenhuma eleição disponível para ano/turno. Consulte ele-c.json; '
                           'o turno pode ainda não estar publicado.')
    return selecionadas


def listar_downloads(config, selecionadas, pasta):
    """Monta a lista (url, destino) de todos os arquivos município e município+zona do RN."""
    tarefas = []
    for pleito, eleicao, cargos in selecionadas:
        codigo = str(eleicao['cd'])
        nome_config = f'mun-e{int(codigo):06d}-cm.json'
        municipios = baixar_json(f"{diretorio(config, 'cm', pleito['c'], codigo)}/{nome_config}")
        salvar(municipios, pasta / 'config' / nome_config)
        lista = next(a['mu'] for a in municipios['abr'] if a['cd'].lower() == UF)
        print(f"{eleicao['nm']}: {len(lista)} municípios, cargos {', '.join(cargos.values())}")
        url_base = diretorio(config, 'u', pleito['c'], codigo)
        for municipio in lista:
            cd_municipio = str(municipio['cd']).zfill(5)  # Código TSE, não IBGE.
            for cargo in cargos:
                for zona in [None] + municipio.get('z', []):
                    parte_zona = f'-z{int(zona):04d}' if zona is not None else ''
                    arquivo = f'{UF}{cd_municipio}{parte_zona}-c{int(cargo):04d}-e{int(codigo):06d}-u.json'
                    tarefas.append((f'{url_base}/{arquivo}', pasta / 'json' / arquivo))
    return tarefas


def baixar_todos(tarefas, atualizar, workers):
    pendentes = [(url, destino) for url, destino in tarefas if atualizar or not destino.exists()]
    print(f'{len(tarefas)} arquivos no total; {len(pendentes)} para baixar.')
    falhas = []

    def baixar(url, destino):
        salvar(baixar_json(url), destino)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futuros = {executor.submit(baixar, url, destino): url for url, destino in pendentes}
        for i, futuro in enumerate(as_completed(futuros), 1):
            try:
                futuro.result()
            except (HTTPError, URLError, TimeoutError, ValueError) as erro:
                falhas.append((futuros[futuro], str(erro)))
                print(f'  Falha: {futuros[futuro]}: {erro}')
            if i % 100 == 0 or i == len(pendentes):
                print(f'  {i}/{len(pendentes)}')
    return falhas


def numero(serie):
    """Converte textos do TSE ('1.234' não ocorre; decimais vêm com vírgula) para número."""
    return pd.to_numeric(serie.astype('string').str.replace(',', '.', regex=False), errors='coerce')


def montar_dataframes(pasta):
    """Lê os JSONs salvos em <pasta>/json e devolve um dict de DataFrames."""
    pasta = Path(pasta)
    municipios = {}
    for arquivo in sorted((pasta / 'config').glob('mun-e*-cm.json')):
        dados = json.loads(arquivo.read_text(encoding='utf-8'))
        for abrangencia in dados['abr']:
            if abrangencia['cd'].lower() == UF:
                for m in abrangencia['mu']:
                    municipios[str(m['cd']).zfill(5)] = (m['nm'], m.get('cdi'))

    candidatos = {'municipio': [], 'zona': []}
    resumos = {'municipio': [], 'zona': []}
    arquivos = sorted((pasta / 'json').glob('*-u.json'))
    if not arquivos:
        raise FileNotFoundError(f'Nenhum JSON encontrado em {(pasta / "json").resolve()}')

    for arquivo in arquivos:
        dados = json.loads(arquivo.read_text(encoding='utf-8'))
        # Nome do arquivo: rn<mun>[-z<zona>]-c<cargo>-e<eleicao>-u.json
        partes = arquivo.name.split('-')
        cd_municipio = partes[0][len(UF):]
        zona = partes[1][1:] if partes[1].startswith('z') else None
        nivel = 'zona' if zona else 'municipio'
        nome_municipio, cd_ibge = municipios.get(cd_municipio, (None, None))

        base = {
            'turno': dados['t'],
            'id_eleicao': dados['ele'],
            'sigla_uf': UF.upper(),
            'id_municipio_tse': cd_municipio,
            'id_municipio_ibge': cd_ibge,
            'municipio': nome_municipio,
        }
        if zona:
            base['zona'] = zona
        base['data_hora_totalizacao'] = f"{dados.get('dt', '')} {dados.get('ht', '')}".strip()

        for cargo in dados['carg']:
            base_cargo = {**base, 'id_cargo': cargo['cd'], 'cargo': cargo['nmn']}
            for grupo in cargo.get('agr', []):
                for partido in grupo.get('par', []):
                    for candidato in partido.get('cand', []):
                        candidatos[nivel].append({
                            **base_cargo,
                            'numero': candidato['n'],
                            'sequencial_candidato': candidato['sqcand'],
                            'nome': candidato['nm'],
                            'nome_urna': candidato['nmu'],
                            'sigla_partido': partido['sg'],
                            'numero_partido': partido['n'],
                            'coligacao_federacao': grupo.get('nm'),
                            'votos': candidato.get('vap'),
                            'percentual': candidato.get('pvapn'),
                            'situacao': candidato.get('st'),
                            'destinacao_votos': candidato.get('dvt'),
                        })

            e, v, s = dados.get('e', {}), dados.get('v', {}), dados.get('s', {})
            resumos[nivel].append({
                **base_cargo,
                'secoes_totalizadas': s.get('st'),
                'secoes_total': s.get('ts'),
                'eleitores': e.get('te'),
                'comparecimento': e.get('c'),
                'abstencao': e.get('a'),
                'votos_validos': v.get('vv'),
                'votos_nominais': v.get('vnom'),
                'votos_legenda': v.get('vl'),
                'votos_brancos': v.get('vb'),
                'votos_nulos': v.get('tvn'),
                'percentual_comparecimento': e.get('pcn'),
                'percentual_abstencao': e.get('pan'),
            })

    inteiros = ['turno', 'votos', 'secoes_totalizadas', 'secoes_total', 'eleitores', 'comparecimento',
                'abstencao', 'votos_validos', 'votos_nominais', 'votos_legenda', 'votos_brancos', 'votos_nulos']
    decimais = ['percentual', 'percentual_comparecimento', 'percentual_abstencao']
    dfs = {}
    for nome, linhas in [('candidatos_municipio', candidatos['municipio']),
                         ('candidatos_zona', candidatos['zona']),
                         ('resumo_municipio', resumos['municipio']),
                         ('resumo_zona', resumos['zona'])]:
        df = pd.DataFrame(linhas)
        if df.empty:
            dfs[nome] = df
            continue
        for coluna in inteiros:
            if coluna in df:
                df[coluna] = numero(df[coluna]).astype('Int64')
        for coluna in decimais:
            if coluna in df:
                df[coluna] = numero(df[coluna])
        ordem = ['municipio'] + (['zona'] if 'zona' in df else []) + ['id_cargo']
        if 'votos' in df:
            df = df.sort_values(ordem + ['votos'], ascending=[True] * len(ordem) + [False])
        else:
            df = df.sort_values(ordem)
        dfs[nome] = df.reset_index(drop=True)
    return dfs


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--ano', type=int, default=2026)
    parser.add_argument('--turno', choices=['1', '2'], default='1')
    parser.add_argument('--saida', type=Path, default=SAIDA_PADRAO)
    parser.add_argument('--atualizar', action='store_true', help='Baixa de novo arquivos que já existem')
    parser.add_argument('--so-tratar', action='store_true', help='Não baixa nada; só monta as tabelas')
    parser.add_argument('--workers', type=int, default=8, help='Downloads simultâneos (padrão: 8)')
    args = parser.parse_args()
    pasta = args.saida / str(args.ano) / f'turno_{args.turno}'

    falhas = []
    if not args.so_tratar:
        config = baixar_json(f'{BASE}/{AMBIENTE}/comum/config/ele-c.json')
        salvar(config, pasta / 'config' / 'ele-c.json')
        selecionadas = selecionar_eleicoes(config, args.ano, args.turno)
        tarefas = listar_downloads(config, selecionadas, pasta)
        falhas = baixar_todos(tarefas, args.atualizar, args.workers)
        salvar([{'url': url, 'erro': erro} for url, erro in falhas], pasta / 'falhas.json')

    dfs = montar_dataframes(pasta)
    for nome, df in dfs.items():
        df.to_csv(pasta / f'{nome}.csv', index=False, encoding='utf-8-sig')
        print(f'{nome}: {len(df)} linhas')
    print(f'Pasta: {pasta.resolve()}')
    if falhas:
        print(f'Atenção: {len(falhas)} arquivos falharam (ver falhas.json). Rode de novo para tentar só eles.')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
