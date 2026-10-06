"""Votos por local de votação (escola/colégio eleitoral) no RN, a partir dos Dados Abertos do TSE.

O TSE publica a votação por seção (urna). Este script soma as seções de cada local e junta
nome, endereço, bairro e coordenadas do cadastro de locais de votação.

Fontes (cdn.tse.jus.br/estatistica/sead/odsele):
    votacao_secao_<ano>_RN.zip           Governador, Senador, Deputados (por seção)
    votacao_secao_<ano>_BR.zip           Presidente (por seção, país todo; filtramos o RN)
    eleitorado_local_votacao_<ano>.zip   cadastro dos locais (nome, endereço, lat/lon, eleitores)

Atenção: na votação, NR_LOCAL_VOTACAO é o local ORIGINAL da seção. Seções remanejadas
(ex.: escola em reforma) votaram em outro local; por isso o local vem do cadastro, cruzando
por município + zona + seção.

Uso:
    python3 baixar_locais_votacao_rn.py
    python3 baixar_locais_votacao_rn.py --atualizar   # baixa os zips de novo

Saída (dados/<ano>/turno_<n>/):
    locais_votacao.csv          um local por linha: nome, endereço, bairro, lat/lon, seções, eleitores
    votos_local_votacao.csv     votos por local x cargo x votável (candidato, legenda, branco, nulo)
"""
import argparse
import shutil
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

UF = 'RN'
CDN = 'https://cdn.tse.jus.br/estatistica/sead/odsele'
DADOS = Path(__file__).resolve().parents[1] / 'dados'
COLUNAS_VOTACAO = ['NR_TURNO', 'SG_UF', 'CD_MUNICIPIO', 'NM_MUNICIPIO', 'NR_ZONA', 'NR_SECAO',
                   'CD_CARGO', 'DS_CARGO', 'NR_VOTAVEL', 'NM_VOTAVEL', 'SQ_CANDIDATO', 'QT_VOTOS']
CHAVE_SECAO = ['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO']
CHAVE_LOCAL = ['CD_MUNICIPIO', 'NR_ZONA', 'NR_LOCAL_VOTACAO']


def baixar(url, destino, atualizar):
    if destino.exists() and not atualizar:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix('.parcial')
    for tentativa in range(3):
        try:
            print(f'Baixando {url}')
            req = Request(url, headers={'User-Agent': 'ObservatorioPotiguar/1.0', 'Cache-Control': 'no-cache'})
            with urlopen(req, timeout=120) as resposta, temporario.open('wb') as arquivo:
                shutil.copyfileobj(resposta, arquivo, length=1 << 20)
            temporario.replace(destino)
            return destino
        except (HTTPError, URLError, TimeoutError) as erro:
            if isinstance(erro, HTTPError) and erro.code == 404:
                raise RuntimeError(f'{url} ainda não foi publicado pelo TSE.') from erro
            if tentativa == 2:
                raise
            time.sleep(5 * (tentativa + 1))


def ler_csv(zip_path, nome, filtro=None, **kwargs):
    """Lê um CSV de dentro do zip. Com filtro, lê em blocos e aplica o filtro em cada um (arquivos grandes)."""
    with zipfile.ZipFile(zip_path) as z:
        with z.open(nome) as arquivo:
            if filtro is None:
                return pd.read_csv(arquivo, sep=';', encoding='latin-1', dtype=str, **kwargs)
            blocos = pd.read_csv(arquivo, sep=';', encoding='latin-1', dtype=str, chunksize=1_000_000, **kwargs)
            return pd.concat([filtro(bloco) for bloco in blocos], ignore_index=True)


def ler_votacao(pasta_zips, ano, atualizar):
    estadual = baixar(f'{CDN}/votacao_secao/votacao_secao_{ano}_{UF}.zip',
                      pasta_zips / f'votacao_secao_{ano}_{UF}.zip', atualizar)
    federal = baixar(f'{CDN}/votacao_secao/votacao_secao_{ano}_BR.zip',
                     pasta_zips / f'votacao_secao_{ano}_BR.zip', atualizar)
    partes = [ler_csv(estadual, f'votacao_secao_{ano}_{UF}.csv', usecols=COLUNAS_VOTACAO)]
    print('Filtrando o RN no arquivo nacional de Presidente (pode levar alguns minutos)...')
    partes.append(ler_csv(federal, f'votacao_secao_{ano}_BR.csv', usecols=COLUNAS_VOTACAO,
                          filtro=lambda bloco: bloco[bloco['SG_UF'] == UF]))
    votos = pd.concat(partes, ignore_index=True)
    votos['QT_VOTOS'] = votos['QT_VOTOS'].astype(int)
    return votos


def ler_locais(pasta_zips, ano, atualizar):
    zip_path = baixar(f'{CDN}/eleitorado_locais_votacao/eleitorado_local_votacao_{ano}.zip',
                      pasta_zips / f'eleitorado_local_votacao_{ano}.zip', atualizar)
    return ler_csv(zip_path, f'eleitorado_local_votacao_{ano}_{UF}.csv')


def tabela_locais(cadastro):
    cadastro = cadastro.copy()
    cadastro['QT_ELEITOR_SECAO'] = cadastro['QT_ELEITOR_SECAO'].astype(int)
    for coord in ('NR_LATITUDE', 'NR_LONGITUDE'):
        valor = pd.to_numeric(cadastro[coord].str.replace(',', '.', regex=False), errors='coerce')
        cadastro[coord] = valor.where(valor != -1)  # -1 = sem coordenada
    locais = cadastro.groupby(CHAVE_LOCAL, as_index=False).agg(
        municipio=('NM_MUNICIPIO', 'first'),
        nome_local=('NM_LOCAL_VOTACAO', 'first'),
        tipo_local=('DS_TIPO_LOCAL', 'first'),
        endereco=('DS_ENDERECO', 'first'),
        bairro=('NM_BAIRRO', 'first'),
        cep=('NR_CEP', 'first'),
        latitude=('NR_LATITUDE', 'first'),
        longitude=('NR_LONGITUDE', 'first'),
        secoes=('NR_SECAO', 'nunique'),
        eleitores=('QT_ELEITOR_SECAO', 'sum'),
    )
    return locais.rename(columns={'CD_MUNICIPIO': 'id_municipio_tse', 'NR_ZONA': 'zona',
                                  'NR_LOCAL_VOTACAO': 'numero_local'})


def tabela_votos(votos, cadastro, locais, candidatos):
    # Local onde a seção realmente votou (cadastro), não o original informado na votação.
    secao_local = cadastro[CHAVE_SECAO + ['NR_LOCAL_VOTACAO']].drop_duplicates(CHAVE_SECAO)
    votos = votos.merge(secao_local, on=CHAVE_SECAO, how='left', validate='many_to_one')
    sem_local = votos['NR_LOCAL_VOTACAO'].isna().sum()
    if sem_local:
        print(f'Atenção: {sem_local} linhas de votação sem local no cadastro (ficam como local vazio).')

    por_local = (votos.groupby(['NR_TURNO', *CHAVE_LOCAL, 'CD_CARGO', 'DS_CARGO', 'NR_VOTAVEL',
                                'NM_VOTAVEL', 'SQ_CANDIDATO'], as_index=False, dropna=False)['QT_VOTOS'].sum()
                      .rename(columns={'NR_TURNO': 'turno', 'CD_MUNICIPIO': 'id_municipio_tse', 'NR_ZONA': 'zona',
                                       'NR_LOCAL_VOTACAO': 'numero_local', 'CD_CARGO': 'id_cargo',
                                       'DS_CARGO': 'cargo', 'NR_VOTAVEL': 'numero_votavel',
                                       'NM_VOTAVEL': 'nome_votavel', 'SQ_CANDIDATO': 'sequencial_candidato',
                                       'QT_VOTOS': 'votos'}))

    # Sequencial negativo (-1, -3...) ou #NULO# = voto no número do partido (legenda).
    por_local['tipo_voto'] = 'nominal'
    sem_candidato = por_local['sequencial_candidato'].str.startswith('-') | (por_local['sequencial_candidato'] == '#NULO#')
    por_local.loc[sem_candidato, 'tipo_voto'] = 'legenda'
    por_local.loc[por_local['numero_votavel'] == '95', 'tipo_voto'] = 'branco'
    por_local.loc[por_local['numero_votavel'] == '96', 'tipo_voto'] = 'nulo'
    por_local.loc[por_local['tipo_voto'] != 'nominal', 'sequencial_candidato'] = None

    # Nome de urna e partido vêm dos resultados da API (baixar_eleicao_rn.py), quando disponíveis.
    if candidatos is not None:
        # Votos anulados (não entram nos válidos): candidato que está na urna mas não no resultado
        # oficial (candidatura indeferida) ou que aparece nele como "Anulado sub judice".
        validos_api = set(candidatos.loc[candidatos['destinacao_votos'].str.startswith('Válido'),
                                         'sequencial_candidato'])
        anulados = (por_local['tipo_voto'] == 'nominal') & ~por_local['sequencial_candidato'].isin(validos_api)
        por_local.loc[anulados, 'tipo_voto'] = 'anulado'
        cand = candidatos[['sequencial_candidato', 'nome_urna', 'sigla_partido']].drop_duplicates('sequencial_candidato')
        por_local = por_local.merge(cand, on='sequencial_candidato', how='left')
        partidos = (candidatos[['numero_partido', 'sigla_partido']].drop_duplicates('numero_partido')
                    .rename(columns={'numero_partido': 'numero_votavel', 'sigla_partido': 'sigla_legenda'}))
        por_local = por_local.merge(partidos, on='numero_votavel', how='left')
        legenda = por_local['tipo_voto'] == 'legenda'
        por_local.loc[legenda, 'sigla_partido'] = por_local.loc[legenda, 'sigla_legenda']
        por_local = por_local.drop(columns='sigla_legenda')

    validos = por_local['tipo_voto'].isin(['nominal', 'legenda'])
    total_validos = (por_local[validos].groupby(['id_municipio_tse', 'zona', 'numero_local', 'id_cargo'])['votos']
                     .sum().rename('votos_validos_local'))
    por_local = por_local.join(total_validos, on=['id_municipio_tse', 'zona', 'numero_local', 'id_cargo'])
    por_local['percentual'] = (100 * por_local['votos'] / por_local['votos_validos_local']).where(validos)

    por_local = por_local.merge(locais[['id_municipio_tse', 'zona', 'numero_local', 'municipio', 'nome_local', 'bairro']],
                                on=['id_municipio_tse', 'zona', 'numero_local'], how='left')
    colunas = ['turno', 'id_municipio_tse', 'municipio', 'zona', 'numero_local', 'nome_local', 'bairro',
               'id_cargo', 'cargo', 'tipo_voto', 'numero_votavel', 'nome_votavel', 'nome_urna', 'sigla_partido',
               'sequencial_candidato', 'votos', 'votos_validos_local', 'percentual']
    por_local = por_local[[c for c in colunas if c in por_local]]
    for coluna in ('turno', 'id_cargo'):
        por_local[coluna] = por_local[coluna].astype(int)
    return por_local.sort_values(['municipio', 'zona', 'numero_local', 'id_cargo', 'votos'],
                                 ascending=[True, True, True, True, False]).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--ano', type=int, default=2026)
    parser.add_argument('--turno', choices=['1', '2'], default='1')
    parser.add_argument('--atualizar', action='store_true', help='Baixa os zips de novo')
    args = parser.parse_args()
    pasta_zips = DADOS / 'dados_abertos'
    pasta = DADOS / str(args.ano) / f'turno_{args.turno}'
    pasta.mkdir(parents=True, exist_ok=True)

    votos = ler_votacao(pasta_zips, args.ano, args.atualizar)
    votos = votos[votos['NR_TURNO'] == args.turno]
    if votos.empty:
        raise RuntimeError(f'Votação por seção do {args.turno}º turno ainda não publicada.')
    cadastro = ler_locais(pasta_zips, args.ano, args.atualizar)
    cadastro = cadastro[cadastro['NR_TURNO'] == args.turno]

    arquivo_candidatos = pasta / 'candidatos_municipio.csv'
    candidatos = (pd.read_csv(arquivo_candidatos, dtype=str) if arquivo_candidatos.exists() else None)
    if candidatos is None:
        print('Aviso: candidatos_municipio.csv não encontrado; tabela sai sem nome de urna/partido. '
              'Rode baixar_eleicao_rn.py antes para completá-la.')

    locais = tabela_locais(cadastro)
    votos_local = tabela_votos(votos, cadastro, locais, candidatos)
    # Mantém só locais que tiveram votação (o cadastro inclui alguns sem seção principal).
    usados = votos_local[['id_municipio_tse', 'zona', 'numero_local']].drop_duplicates()
    locais = locais.merge(usados, on=['id_municipio_tse', 'zona', 'numero_local'])

    locais.to_csv(pasta / 'locais_votacao.csv', index=False, encoding='utf-8-sig')
    votos_local.to_csv(pasta / 'votos_local_votacao.csv', index=False, encoding='utf-8-sig')
    print(f'locais_votacao: {len(locais)} locais em {locais["id_municipio_tse"].nunique()} municípios')
    print(f'votos_local_votacao: {len(votos_local)} linhas')
    print(f'Pasta: {pasta.resolve()}')


if __name__ == '__main__':
    main()
