"""Caminhos, cores dos partidos e malha municipal do RN, compartilhados pelos scripts."""
import gzip
import json
from pathlib import Path
from urllib.request import Request, urlopen

DADOS = Path(__file__).resolve().parents[1] / 'dados'
URL_MALHA = ('https://servicodados.ibge.gov.br/api/v3/malhas/estados/24'
             '?intrarregiao=municipio&formato=application/vnd.geo%2Bjson&qualidade=intermediaria')

# Cada cor tem uma rampa, do claro ao escuro. O índice 3 é a cor cheia (vencedor no local).
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


def carregar_malha():
    """Malha dos municípios do RN (GeoJSON do IBGE); baixa na primeira vez e guarda em dados/."""
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
