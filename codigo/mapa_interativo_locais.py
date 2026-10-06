"""Mapa interativo (HTML) dos locais de votação do RN (ou de um município), com o % de cada candidato.

- Passe o mouse num local para ver o % de todos os candidatos; clique para fixar no painel lateral.
- "Colorir por": cor do candidato vencedor em cada local, ou o % de um candidato escolhido.
- Alterna entre Governador e Presidente.
- No mapa do estado, o filtro "Município" (ou um clique no contorno) aproxima e mostra o total do município.

Lê votos_local_votacao.csv e locais_votacao.csv (baixar_locais_votacao_rn.py) e
candidatos_municipio.csv (baixar_eleicao_rn.py). Gera um único .html que abre no navegador
(precisa de internet para o mapa de fundo e a biblioteca Leaflet).

Uso:
    python3 mapa_interativo_locais.py                        # RN inteiro
    python3 mapa_interativo_locais.py --municipio MOSSORÓ    # só um município
    python3 mapa_interativo_locais.py --index      # também salva o index.html do site (raiz do repositório)
"""
import argparse
import base64
import html as html_lib
import json
import mimetypes
import unicodedata
from pathlib import Path

import pandas as pd

from config import CARGOS, DADOS, RAMPAS, carregar_malha

# Identidade do projeto. A logo é procurada em identidade/logo.(png|svg|jpg|jpeg|webp)
# e embutida no HTML (o arquivo continua único). Pode ser sobrescrita por --logo, --autoria, --link.
IDENTIDADE = DADOS.parent / 'identidade'
AUTORIA = 'Larissa Brito'
LINK_AUTORIA = 'https://www.linkedin.com/in/larissa-martins-2b93671a8/'

# Cores dos candidatos sem cor de partido definida, distribuídas por ordem de votação
# (os mais votados ficam com as cores mais distintas entre si). Cores já usadas por partidos
# do cargo (vermelho/azul/verde) são puladas.
CORES_EXTRAS = [
    ('laranja', '#E8662E'), ('aqua', '#1BAF7A'), ('amarelo', '#E0A100'), ('magenta', '#D65A8E'),
    ('violeta', '#5B4BB7'), ('verde', '#5E9E2E'), ('marrom', '#8D5A2B'), ('petroleo', '#0F6E6E'),
    ('oliva', '#8A8A1E'), ('vinho', '#8E2A55'), ('ardosia', '#5B6B7C'), ('ceu', '#3FA7DE'),
]


def misturar(cor, alvo, t):
    a = [int(cor[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(alvo[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(x + (y - x) * t):02X}' for x, y in zip(a, b))


def rampa_de(cor):
    """5 tons do claro ao escuro, com a cor cheia no índice 3 (mesma convenção de RAMPAS)."""
    return [misturar(cor, '#FFFFFF', 0.75), misturar(cor, '#FFFFFF', 0.5), misturar(cor, '#FFFFFF', 0.25),
            cor, misturar(cor, '#000000', 0.35)]


PARTICULAS = {'de', 'da', 'do', 'das', 'dos', 'e'}


def nome_municipio(nome):
    """'SÃO GONÇALO DO AMARANTE' -> 'São Gonçalo do Amarante'."""
    palavras = nome.title().split()
    return ' '.join(p.lower() if i and p.lower() in PARTICULAS else p for i, p in enumerate(palavras))


def malha_simplificada(ids_ibge):
    """Contornos dos municípios (IBGE) com coordenadas arredondadas, para desenhar no mapa."""
    def arredondar(c):
        return [round(c[0], 4), round(c[1], 4)] if isinstance(c[0], (int, float)) else [arredondar(x) for x in c]

    malha = carregar_malha()  # baixa da API do IBGE na primeira vez
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'id': ids_ibge[f['properties']['codarea']]},
         'geometry': {'type': f['geometry']['type'], 'coordinates': arredondar(f['geometry']['coordinates'])}}
        for f in malha['features'] if f['properties']['codarea'] in ids_ibge]}


def montar_dados(turno, municipio=None):
    """Sem município: o RN inteiro, com um seletor de município na página."""
    pasta = DADOS / '2026' / f'turno_{turno}'
    tipos = {'id_municipio_tse': str, 'id_municipio_ibge': str, 'zona': str, 'numero_local': str,
             'sequencial_candidato': str}
    votos = pd.read_csv(pasta / 'votos_local_votacao.csv', dtype=tipos)
    locais = pd.read_csv(pasta / 'locais_votacao.csv', dtype=tipos)
    mun = pd.read_csv(pasta / 'candidatos_municipio.csv', dtype=tipos)
    if municipio:
        votos = votos[votos['municipio'] == municipio]
        if votos.empty:
            raise SystemExit(f'Sem votos para {municipio}. Use o nome como no TSE, ex.: MOSSORÓ, NATAL.')
        locais = locais[locais['municipio'] == municipio]
        mun = mun[mun['municipio'] == municipio]
    sem_coordenada = locais[locais['latitude'].isna() | locais['longitude'].isna()]
    if not sem_coordenada.empty:
        print(f'Aviso: {len(sem_coordenada)} local(is) sem coordenada ficam fora do mapa: '
              + ', '.join(sem_coordenada['nome_local'] + ' (' + sem_coordenada['municipio'] + ')'))
    locais = locais.dropna(subset=['latitude', 'longitude'])
    mun = mun[mun['destinacao_votos'].str.startswith('Válido')]

    ids = mun[['id_municipio_tse', 'id_municipio_ibge', 'municipio']].drop_duplicates('id_municipio_tse')
    nome = nome_municipio(municipio) if municipio else 'Rio Grande do Norte'
    dados = {'abrangencia': nome, 'onde': f'em {nome}' if municipio else 'no Rio Grande do Norte',
             'turno': turno, 'cargos': {}, 'locais': [],
             'municipios': {r.id_municipio_tse: {'nome': nome_municipio(r.municipio), 'cargos': {}}
                            for r in ids.sort_values('municipio').itertuples()},
             'malha': None if municipio else malha_simplificada(dict(zip(ids['id_municipio_ibge'],
                                                                         ids['id_municipio_tse'])))}
    por_local = {}
    for chave, cargo in CARGOS.items():
        nominais = votos[(votos['id_cargo'] == cargo['id']) & (votos['tipo_voto'] == 'nominal')]
        do_cargo = mun[mun['id_cargo'] == cargo['id']]
        total = (do_cargo.groupby(['sequencial_candidato', 'nome_urna', 'sigla_partido'], as_index=False)['votos']
                 .sum().sort_values('votos', ascending=False))
        candidatos = []
        extras = iter(cor for nome, cor in CORES_EXTRAS if nome not in cargo['cores'].values())
        for _, c in total.iterrows():
            partido = c['sigla_partido']
            if partido in cargo['cores']:
                rampa = RAMPAS[cargo['cores'][partido]]
            else:
                rampa = rampa_de(next(extras))
            candidatos.append({'id': c['sequencial_candidato'], 'nome': c['nome_urna'].title(),
                               'partido': partido, 'rampa': rampa, 'votos': int(c['votos'])})
        dados['cargos'][chave] = {'nome': cargo['nome'], 'candidatos': candidatos,
                                  'validos': int(total['votos'].sum())}
        # Totais de cada município (painel "Total" quando um município está selecionado).
        for id_mun, grupo in do_cargo.groupby('id_municipio_tse'):
            dados['municipios'][id_mun]['cargos'][chave] = {
                'validos': int(grupo['votos'].sum()),
                'votos': {s: int(v) for s, v in zip(grupo['sequencial_candidato'], grupo['votos'])},
            }
        for (id_mun, zona, numero), grupo in nominais.groupby(['id_municipio_tse', 'zona', 'numero_local']):
            por_local.setdefault((id_mun, zona, numero), {})[chave] = {
                'validos': int(grupo['votos_validos_local'].iat[0]),
                'votos': {s: int(v) for s, v in zip(grupo['sequencial_candidato'], grupo['votos'])},
            }

    for _, l in locais.iterrows():
        cargos = por_local.get((l['id_municipio_tse'], l['zona'], l['numero_local']))
        if not cargos:
            continue
        dados['locais'].append({
            'nome': l['nome_local'].title(), 'bairro': str(l['bairro']).title(), 'zona': str(int(l['zona'])),
            'mun': l['id_municipio_tse'],
            'endereco': str(l['endereco']).title(), 'lat': round(l['latitude'], 6), 'lon': round(l['longitude'], 6),
            'eleitores': int(l['eleitores']), 'cargos': cargos,
        })
    return dados


HTML = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Locais de votação — __MUNICIPIO__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;600&display=swap">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  :root {
    --fonte: "EB Garamond", Garamond, "Times New Roman", serif;  /* fonte de toda a página */
    --bg: #ffffff; --surface: #f7f7f5; --border: #e2e2de; --ink: #1a1a1a; --ink-2: #4a4a4a;
    --ink-3: #767676; --accent: #1a1a1a; --bar-bg: #ececea;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #161616; --surface: #1f1f1f; --border: #333; --ink: #f0f0f0; --ink-2: #c8c8c8;
      --ink-3: #9a9a9a; --accent: #f0f0f0; --bar-bg: #2c2c2c;
    }
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 17px/1.45 var(--fonte); }
  .wrap { max-width: 1680px; margin: 0 auto; padding: 20px 16px 40px; }
  h1 { font-size: 28px; margin: 0 0 4px; font-weight: 600; }
  /* Logo primeiro, à esquerda (início da leitura), e o título logo ao lado, alinhado à esquerda. */
  .topo { display: flex; gap: 16px; align-items: center; margin-bottom: 16px; }
  .topo .sub { margin: 0; }
  .logo { width: 72px; height: 72px; flex: none; border-radius: 12px; }
  @media (max-width: 560px) { .logo { width: 52px; height: 52px; } }
  .autoria { color: var(--ink-2); font-size: 16px; margin-top: 6px; }
  .autoria a { color: inherit; display: inline-flex; align-items: center; gap: 5px; vertical-align: middle; }
  .autoria .icone { flex: none; }
  .sub { color: var(--ink-2); margin: 0 0 16px; white-space: pre-line; }  /* "\n" vira quebra de linha */
  .controls { display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: center; margin-bottom: 12px; }
  .seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .seg button { border: 0; background: var(--bg); color: var(--ink-2); padding: 7px 14px; font: inherit; cursor: pointer; }
  .seg button + button { border-left: 1px solid var(--border); }
  .seg button[aria-pressed="true"] { background: var(--accent); color: var(--bg); }
  label.sel { display: inline-flex; gap: 8px; align-items: center; color: var(--ink-2); }
  select { font: inherit; padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px;
           background: var(--bg); color: var(--ink); max-width: 100%; }
  .main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; }
  @media (max-width: 860px) { .main { grid-template-columns: 1fr; } }
  /* Mapa ocupa quase toda a altura da janela (mínimo 620px). */
  #mapa { height: max(620px, calc(100vh - 190px)); border-radius: 10px; border: 1px solid var(--border);
          background: var(--surface); }
  @media (max-width: 860px) { #mapa { height: 72vh; } }
  #mapa:fullscreen { height: 100vh; border-radius: 0; border: 0; }
  .btn-cheia { background: var(--bg); color: var(--ink); border: 1px solid var(--border); border-radius: 6px;
               padding: 6px 10px; font: 15px var(--fonte); cursor: pointer; }
  .btn-cheia:hover { background: var(--surface); }
  /* Coluna lateral: painel de resultados e, logo abaixo, fonte e autoria. */
  /* Coluna lateral com a altura do mapa: painel em cima, fonte e autoria no pé (texto à esquerda). */
  .lateral { display: flex; flex-direction: column; gap: 14px; }
  .rodape { margin-top: auto; text-align: left; }
  .rodape .fonte { margin-top: 0; }
  .painel { border: 1px solid var(--border); border-radius: 10px; padding: 14px; background: var(--surface); }
  .painel h2 { font-size: 20px; margin: 0 0 2px; }
  .painel .meta { color: var(--ink-3); font-size: 15px; margin-bottom: 10px; }
  .painel .dica { color: var(--ink-3); font-size: 15px; margin-top: 10px; }
  .painel button.voltar { border: 0; background: none; color: var(--ink-2); padding: 0; font: inherit;
                          font-size: 15px; text-decoration: underline; cursor: pointer; margin-top: 8px; }
  .linha { display: grid; grid-template-columns: 10px minmax(0, 1fr) 62px; gap: 4px 8px; align-items: center;
           margin: 5px 0; }
  .linha .sw { width: 10px; height: 10px; border-radius: 2px; }
  .linha .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .linha .nm small { color: var(--ink-3); }
  .linha .pc { text-align: right; font-variant-numeric: tabular-nums; }
  .linha .bar { grid-column: 2 / 4; height: 5px; background: var(--bar-bg); border-radius: 3px; overflow: hidden; }
  .linha .bar i { display: block; height: 100%; border-radius: 3px; }
  .legenda { background: var(--bg); color: var(--ink); padding: 8px 10px; border-radius: 8px;
             border: 1px solid var(--border); font: 15px/1.4 var(--fonte); max-width: 300px; }
  .legenda b { display: block; font-weight: 600; margin-bottom: 4px; }
  .legenda div { display: flex; gap: 6px; align-items: center; }
  .legenda span.sw { width: 12px; height: 12px; border-radius: 50%; flex: none; }
  .legenda .escala { display: flex; width: 270px; height: 14px; border-radius: 3px; overflow: hidden; margin-top: 4px; }
  .legenda .escala-marcas { display: flex; justify-content: space-between; width: 270px; margin-top: 2px;
                           font-size: 12.5px; color: var(--ink); }
  .legenda .tit-tamanho { margin-top: 10px; }
  .legenda .tamanhos { display: flex; gap: 10px; align-items: flex-end; color: var(--ink); }
  .legenda .tamanhos .ref { display: flex; flex-direction: column; align-items: center; font-size: 12.5px; }
  .legenda .tit-tamanho { color: var(--ink); font-weight: 400; }
  .legenda .escala-rotulos { display: flex; justify-content: space-between; width: 270px; margin-top: 3px;
                             font-size: 13px; color: var(--ink); line-height: 1.2; }
  .legenda .escala-rotulos span:last-child { text-align: right; }
  .leaflet-tooltip.tt { background: var(--bg); color: var(--ink); border: 1px solid var(--border);
                        box-shadow: 0 4px 14px rgba(0,0,0,.15); border-radius: 8px; padding: 10px 12px; width: 330px;
                        white-space: normal; font: 16px/1.4 var(--fonte); }
  .tt h3 { font-size: 18px; margin: 0 0 2px; }
  .tt .meta { color: var(--ink-3); font-size: 14.5px; margin-bottom: 6px; }
  .fonte { color: var(--ink-3); font-size: 14.5px; margin-top: 14px; }
  .fonte.contato { margin-top: 4px; }
</style>
</head>
<body>
<div class="wrap">
  <header class="topo">
    __LOGO__
    <div>
      <h1 id="titulo"></h1>
      <p class="sub" id="subtitulo"></p>
    </div>
  </header>
  <div class="controls">
    <div class="seg" id="cargos" role="group" aria-label="Cargo"></div>
    <label class="sel">Colorir por <select id="colorir"></select></label>
    <label class="sel" id="filtro-municipio" hidden>Município <select id="municipio"></select></label>
  </div>
  <div class="main">
    <div id="mapa" role="region" aria-label="Mapa dos locais de votação"></div>
    <div class="lateral">
      <aside class="painel" id="painel" aria-live="polite"></aside>
      <div class="rodape">
        <p class="fonte">Percentuais sobre os votos válidos de cada local.
          Fonte: TSE — votação por seção e cadastro de locais de votação (Dados Abertos), __TURNO__º turno 2026.</p>
        __AUTORIA__
        <p class="fonte contato">Caso você encontre algum erro ou dado desatualizado, entre em contato comigo.</p>
      </div>
    </div>
  </div>
</div>
<script>
const D = __DADOS__;
let cargo = Object.keys(D.cargos)[0];  // abre no primeiro cargo (Presidente)
let modo = 'vencedor';          // 'vencedor' (cor do mais votado no local) ou id do candidato
let fixado = null;              // local clicado
let mun = null;                 // município selecionado (id TSE); null = todos
const variosMunicipios = Object.keys(D.municipios).length > 1;

const fmtPct = v => v.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%';
const fmtInt = v => v.toLocaleString('pt-BR');
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function resultado(local) {
  // Candidatos do cargo com votos e % no local, do mais para o menos votado.
  const c = local.cargos[cargo];
  if (!c) return null;
  const lista = D.cargos[cargo].candidatos.map(k => {
    const votos = c.votos[k.id] || 0;
    return { ...k, votos, pct: c.validos ? 100 * votos / c.validos : 0 };
  }).sort((a, b) => b.votos - a.votos);
  return { validos: c.validos, lista, margem: lista[0].pct - (lista[1] ? lista[1].pct : 0) };
}

function faixasCandidato(id) {
  // 5 faixas de largura igual entre o menor e o maior % do candidato nos locais.
  const pcts = D.locais.map(l => resultado(l)).filter(Boolean).map(r => r.lista.find(c => c.id === id).pct);
  const min = Math.floor(Math.min(...pcts)), max = Math.ceil(Math.max(...pcts));
  const passo = Math.max((max - min) / 5, 0.1);
  return Array.from({ length: 5 }, (_, i) => [min + i * passo, i === 4 ? max : min + (i + 1) * passo]);
}

function indiceFaixa(v, faixas) {
  const i = faixas.findIndex(([, fim]) => v < fim);
  return i === -1 ? faixas.length - 1 : i;
}

function vitorias() {
  // Candidatos que venceram em pelo menos um local, com o número de locais, do que mais venceu ao que menos.
  const n = {};
  for (const l of D.locais) {
    const r = resultado(l);
    if (r) n[r.lista[0].id] = (n[r.lista[0].id] || 0) + 1;
  }
  return D.cargos[cargo].candidatos.filter(c => n[c.id]).map(c => ({ ...c, locais: n[c.id] }))
    .sort((a, b) => b.locais - a.locais);
}

function corDoLocal(r, faixas) {
  if (modo === 'vencedor') return r.lista[0].rampa[3];
  const c = r.lista.find(c => c.id === modo);
  return c.rampa[indiceFaixa(c.pct, faixas)];
}

function linhasHTML(lista, maxLinhas) {
  const maior = lista[0].pct || 1;
  return lista.slice(0, maxLinhas).map(c => `
    <div class="linha">
      <span class="sw" style="background:${c.rampa[3]}"></span>
      <span class="nm">${esc(c.nome)} <small>${esc(c.partido)}</small></span>
      <span class="pc">${fmtPct(c.pct)}</span>
      <span class="bar"><i style="width:${(100 * c.pct / maior).toFixed(1)}%;background:${c.rampa[3]}"></i></span>
    </div>`).join('');
}

function detalheHTML(local, r, tag) {
  const cidade = variosMunicipios ? `${esc(D.municipios[local.mun].nome)} · ` : '';
  return `<${tag}>${esc(local.nome)}</${tag}>
    <div class="meta">${cidade}${esc(local.bairro)} · Zona ${esc(local.zona)} · ${fmtInt(r.validos)} votos válidos</div>
    ${linhasHTML(r.lista, 20)}`;
}

function escopo() {
  // Total do estado (ou do município único) ou do município selecionado no filtro.
  const cg = D.cargos[cargo];
  const m = mun ? D.municipios[mun] : null;
  const validos = m ? (m.cargos[cargo] || { validos: 0 }).validos : cg.validos;
  const votosDe = c => m ? ((m.cargos[cargo] || { votos: {} }).votos[c.id] || 0) : c.votos;
  const lista = cg.candidatos.map(c => ({ ...c, votos: votosDe(c), pct: validos ? 100 * votosDe(c) / validos : 0 }))
    .sort((a, b) => b.votos - a.votos);
  return {
    nome: m ? m.nome : D.abrangencia, onde: m ? `em ${m.nome}` : D.onde, validos, lista,
    locais: mun ? D.locais.filter(l => l.mun === mun) : D.locais,
  };
}

function totalHTML() {
  const e = escopo();
  return `<h2>${esc(e.nome)} (Total)</h2>
    <div class="meta">${esc(D.cargos[cargo].nome)} · ${fmtInt(e.validos)} votos válidos · ${fmtInt(e.locais.length)} locais</div>
    ${linhasHTML(e.lista, 20)}
    <div class="dica">Passe o mouse no mapa para ver os percentuais.</div>`;
}

function atualizarPainel() {
  const painel = document.getElementById('painel');
  if (fixado) {
    const r = resultado(fixado);
    const voltar = mun || !variosMunicipios ? 'do município' : 'do estado';
    painel.innerHTML = detalheHTML(fixado, r, 'h2') +
      `<div class="meta" style="margin-top:8px">${esc(fixado.endereco)}</div>
       <button class="voltar" id="voltar">Voltar ao total ${voltar}</button>`;
    document.getElementById('voltar').onclick = () => { fixado = null; atualizarPainel(); };
  } else {
    painel.innerHTML = totalHTML();
  }
}

// ---------- mapa ----------
const escuro = matchMedia('(prefers-color-scheme: dark)').matches;
const mapa = L.map('mapa', { scrollWheelZoom: true });
// Mapa de fundo da Esri (cinza, sem chave de API). CARTO passou a exigir chave e o
// OpenStreetMap bloqueia páginas abertas direto do disco (file://), sem "Referer".
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas';
const tom = escuro ? 'Dark' : 'Light';
const atribuicao = 'Mapa: Esri, HERE, Garmin, © OpenStreetMap';
L.tileLayer(`${ESRI}/World_${tom}_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
            { attribution: atribuicao, maxZoom: 16 }).addTo(mapa);
L.tileLayer(`${ESRI}/World_${tom}_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
            { maxZoom: 16, pane: 'overlayPane' }).addTo(mapa);  // nomes de ruas e bairros
const maxValidos = Math.max(...D.locais.flatMap(l => Object.values(l.cargos).map(c => c.validos)));
// Com o zoom afastado (estado inteiro) os círculos encolhem, para os locais de Natal e Mossoró não
// virarem uma mancha só. A partir do zoom 12 (uma cidade) ficam no tamanho cheio.
const fatorZoom = () => Math.min(1, Math.max(0.3, Math.pow(2, (mapa.getZoom() - 12) / 2)));
const raio = v => Math.max(2.5, (4 + 18 * Math.sqrt(v / maxValidos)) * fatorZoom());

// Contornos dos municípios (só no mapa do estado). Clicar num município o seleciona.
const corBorda = escuro ? '#5a5a5a' : '#a8a8a2', corBordaSel = escuro ? '#f0f0f0' : '#1a1a1a';
mapa.createPane('municipios').style.zIndex = 350;  // abaixo dos círculos (overlayPane = 400)
const malha = D.malha ? L.geoJSON(D.malha, {
  pane: 'municipios',
  style: () => ({ color: corBorda, weight: 0.7, fill: true, fillOpacity: 0 }),
  onEachFeature: (f, camadaMun) => camadaMun.on('click', () => selecionarMunicipio(f.properties.id)),
}).addTo(mapa) : null;
function destacarMunicipio() {
  if (!malha) return;
  malha.eachLayer(p => {
    const sel = p.feature.properties.id === mun;
    p.setStyle({ color: sel ? corBordaSel : corBorda, weight: sel ? 2.2 : 0.7 });
    if (sel) p.bringToFront();
  });
}

const camada = L.layerGroup().addTo(mapa);
const legenda = L.control({ position: 'bottomleft' });
legenda.onAdd = () => L.DomUtil.create('div', 'legenda');
legenda.addTo(mapa);

// Botão de tela cheia (só o mapa; a caixinha ao passar o mouse continua funcionando).
const cheia = L.control({ position: 'topright' });
cheia.onAdd = () => {
  const b = L.DomUtil.create('button', 'btn-cheia');
  b.type = 'button';
  b.textContent = 'Tela cheia';
  L.DomEvent.disableClickPropagation(b);
  b.onclick = () => document.fullscreenElement ? document.exitFullscreen()
                                               : document.getElementById('mapa').requestFullscreen();
  document.addEventListener('fullscreenchange', () => {
    b.textContent = document.fullscreenElement ? 'Sair da tela cheia' : 'Tela cheia';
    setTimeout(() => mapa.invalidateSize(), 50);
  });
  return b;
};
if (document.fullscreenEnabled) cheia.addTo(mapa);

function desenharMapa() {
  camada.clearLayers();
  const faixas = modo === 'vencedor' ? null : faixasCandidato(modo);
  const itens = D.locais.map(l => ({ l, r: resultado(l) })).filter(x => x.r)
    .sort((a, b) => b.r.validos - a.r.validos);  // grandes por baixo
  for (const { l, r } of itens) {
    const m = L.circleMarker([l.lat, l.lon], {
      radius: raio(r.validos), fillColor: corDoLocal(r, faixas), fillOpacity: 0.92,
      color: escuro ? '#161616' : '#ffffff', weight: 1.5, validos: r.validos,
    });
    m.bindTooltip(() => detalheHTML(l, resultado(l), 'h3'), { className: 'tt', direction: 'auto', sticky: true });
    m.on('click', () => { fixado = l; atualizarPainel(); });
    m.on('mouseover', () => m.setStyle({ weight: 3, color: escuro ? '#f0f0f0' : '#1a1a1a' }));
    m.on('mouseout', () => m.setStyle({ weight: 1.5, color: escuro ? '#161616' : '#ffffff' }));
    m.addTo(camada);
  }
  // Legenda
  const box = document.querySelector('.legenda');
  if (modo === 'vencedor') {
    box.innerHTML = `<b>Mais votado no local</b>` + vitorias().map(c =>
      `<div><span class="sw" style="background:${c.rampa[3]}"></span>${esc(c.nome)} (${esc(c.partido)}) — ` +
      `${fmtInt(c.locais)} ${c.locais === 1 ? 'local' : 'locais'}</div>`).join('');
  } else {
    const c = D.cargos[cargo].candidatos.find(c => c.id === modo);
    box.innerHTML = `<b>% de ${esc(c.nome)} (${esc(c.partido)})</b>` + faixas.map(([a, b], i) =>
      `<div><span class="sw" style="background:${c.rampa[i]}"></span>${fmtPct(a)} a ${fmtPct(b)}</div>`).join('');
  }
  box.innerHTML += `<div id="legenda-tamanho">${legendaTamanho()}</div>`;
}

mapa.on('zoomend', () => {
  camada.eachLayer(m => m.setRadius(raio(m.options.validos)));
  const tamanho = document.getElementById('legenda-tamanho');
  if (tamanho) tamanho.innerHTML = legendaTamanho();
});

function legendaTamanho() {
  // 3 círculos de referência, no mesmo tamanho dos do mapa (valores redondos: ~1/12, 1/3 e 2/3 do máximo,
  // para a legenda ficar discreta).
  const passo = maxValidos > 4000 ? 500 : 100;
  const valores = [maxValidos / 12, maxValidos / 3, maxValidos * 2 / 3].map(v => Math.max(passo, Math.round(v / passo) * passo));
  const rMax = raio(valores[2]);
  const circulos = valores.map(v => {
    const r = raio(v);
    return `<span class="ref"><svg width="${2 * rMax + 2}" height="${2 * rMax + 2}" aria-hidden="true">
        <circle cx="${rMax + 1}" cy="${2 * rMax + 1 - r}" r="${r}" style="fill: var(--ink-3); fill-opacity: 0.45"/>
      </svg>${fmtInt(v)}</span>`;
  }).join('');
  return `<b class="tit-tamanho">Votos válidos</b><div class="tamanhos">${circulos}</div>`;
}

// ---------- controles ----------
function montarControles() {
  const seg = document.getElementById('cargos');
  seg.innerHTML = Object.entries(D.cargos).map(([k, c]) =>
    `<button type="button" data-k="${k}" aria-pressed="${k === cargo}">${esc(c.nome)}</button>`).join('');
  seg.querySelectorAll('button').forEach(b => b.onclick = () => {
    cargo = b.dataset.k; modo = 'vencedor'; montarControles(); render();
  });
  const sel = document.getElementById('colorir');
  sel.innerHTML = `<option value="vencedor">Vencedor no local</option>` +
    D.cargos[cargo].candidatos.map(c => `<option value="${c.id}">% de ${esc(c.nome)} (${esc(c.partido)})</option>`).join('');
  sel.value = modo;
  sel.onchange = () => { modo = sel.value; desenharMapa(); };
}

function montarFiltroMunicipio() {
  if (!variosMunicipios) return;
  document.getElementById('filtro-municipio').hidden = false;
  const sel = document.getElementById('municipio');
  sel.innerHTML = `<option value="">Todo o estado</option>` +
    Object.entries(D.municipios).map(([id, m]) => `<option value="${id}">${esc(m.nome)}</option>`).join('');
  sel.onchange = () => selecionarMunicipio(sel.value || null);
}

function enquadrar() {
  const pontos = escopo().locais.map(l => [l.lat, l.lon]);
  if (pontos.length) mapa.fitBounds(L.latLngBounds(pontos), { padding: [20, 20], maxZoom: 14 });
}

function selecionarMunicipio(id) {
  mun = id; fixado = null;
  document.getElementById('municipio').value = id || '';
  destacarMunicipio(); enquadrar(); render();
}

function render() {
  const e = escopo();
  document.getElementById('titulo').textContent = `${D.cargos[cargo].nome} ${e.onde} por local de votação`;
  const [a, b] = e.lista;
  document.getElementById('subtitulo').textContent =
    `${D.turno}º turno 2026 · ${fmtInt(e.locais.length)} locais de votação ${e.onde}\n` +
    `Total de votos: ${a.nome} ${fmtPct(a.pct)}, ${b.nome} ${fmtPct(b.pct)}`;
  desenharMapa(); atualizarPainel();
}

enquadrar();
montarControles();
montarFiltroMunicipio();
render();
</script>
</body>
</html>
'''


def logo_html(caminho, autoria):
    """<img> com a logo embutida em base64; vazio se não houver logo."""
    if caminho is None:
        caminho = next((c for ext in ('png', 'svg', 'jpg', 'jpeg', 'webp')
                        for c in [IDENTIDADE / f'logo.{ext}'] if c.exists()), None)
        if caminho is None:
            return ''
    if not caminho.exists():
        raise SystemExit(f'Logo não encontrada: {caminho}')
    tipo = mimetypes.guess_type(caminho.name)[0] or 'image/png'
    conteudo = base64.b64encode(caminho.read_bytes()).decode()
    alt = html_lib.escape(autoria or 'Logo do projeto')
    return f'<img class="logo" src="data:{tipo};base64,{conteudo}" alt="{alt}">'


def autoria_html(autoria, link):
    if not autoria:
        return ''
    texto = html_lib.escape(autoria)
    if link:
        icone = ICONE_LINKEDIN if 'linkedin.com' in link else ''
        texto = (f'<a href="{html_lib.escape(link)}" target="_blank" rel="noopener" '
                 f'aria-label="{texto} no LinkedIn">{icone}{texto}</a>')
    return f'<p class="autoria">Feito por: {texto}</p>'


# Ícone do LinkedIn (SVG inline), mostrado quando o link é do LinkedIn. Cinza: herda a cor do texto
# do rodapé (currentColor); o "in" usa a cor de fundo da página, então funciona no modo escuro.
ICONE_LINKEDIN = (
    '<svg class="icone" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">'
    '<rect width="24" height="24" rx="4" fill="currentColor"/>'
    '<path style="fill: var(--bg)" d="M7.1 9.3H4.7V19h2.4V9.3zM5.9 5.2a1.4 1.4 0 1 0 0 2.8 1.4 1.4 0 0 0 0-2.8zM19.3 13.7'
    'c0-2.6-.6-4.6-3.6-4.6-1.5 0-2.4.8-2.8 1.6h-.1V9.3h-2.3V19h2.4v-4.8c0-1.3.2-2.5 1.8-2.5 1.6 0 1.6 1.5 1.6 2.6'
    'V19h2.4l.6-5.3z"/></svg>'
)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--turno', choices=['1', '2'], default='1')
    parser.add_argument('--municipio', help='Só um município, como no TSE (ex.: MOSSORÓ). Padrão: o RN inteiro')
    parser.add_argument('--logo', type=Path, help='Imagem da logo (png, svg, jpg, webp)')
    parser.add_argument('--autoria', default=AUTORIA, help='Texto do "Feito por"')
    parser.add_argument('--link', default=LINK_AUTORIA, help='Link do "Feito por" (opcional)')
    parser.add_argument('--index', action='store_true',
                        help='Também salva uma cópia como index.html na raiz do repositório (site do GitHub Pages)')
    args = parser.parse_args()

    dados = montar_dados(args.turno, args.municipio)
    # "</" escapado para o JSON não fechar a tag <script> por engano.
    json_dados = json.dumps(dados, ensure_ascii=False).replace('</', '<\\/')
    html = (HTML.replace('__DADOS__', json_dados)
                .replace('__MUNICIPIO__', dados['abrangencia'])
                .replace('__TURNO__', args.turno)
                .replace('__LOGO__', logo_html(args.logo, args.autoria))
                .replace('__AUTORIA__', autoria_html(args.autoria, args.link)))
    nome = (unicodedata.normalize('NFKD', args.municipio.lower()).encode('ascii', 'ignore').decode().replace(' ', '_')
            if args.municipio else 'rn')
    saida = DADOS / '2026' / f'turno_{args.turno}' / f'mapa_interativo_{nome}.html'
    saida.write_text(html, encoding='utf-8')
    print(f'Salvo: {saida}  ({len(dados["locais"])} locais)')
    if args.index:
        index = DADOS.parent / 'index.html'
        index.write_text(html, encoding='utf-8')
        print(f'Salvo: {index}  (faça commit e push para atualizar o site)')


if __name__ == '__main__':
    main()
