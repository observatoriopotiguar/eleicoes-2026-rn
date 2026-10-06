# Eleições 2026 no RN: resultados por local de votação

Mapa interativo do Observatório Potiguar com o resultado do 1º turno de 2026 em cada local de votação
do Rio Grande do Norte (1.564 locais em 167 municípios), para Presidente e Governador.

**Site:** https://observatoriopotiguar.github.io/eleicoes-2026-rn/

No mapa é possível ver o candidato mais votado em cada local, filtrar por município, passar o mouse
num local para ver o percentual de todos os candidatos e colorir o mapa pelo desempenho de um candidato.

## Estrutura

```
index.html        o site (gerado por codigo/mapa_interativo_locais.py --index)
codigo/           scripts em Python
identidade/       logo do Observatório (embutida no site)
dados/            dados baixados e tabelas geradas; fora do git, refeitos pelos scripts
```

## Como gerar o site do zero

Requer Python 3.9+.

```bash
pip install -r requirements.txt
cd codigo

python3 baixar_eleicao_rn.py          # 1. resultados por município e zona (API de resultados do TSE)
python3 baixar_locais_votacao_rn.py   # 2. votos por local de votação (Dados Abertos do TSE, ~150 MB)
python3 mapa_interativo_locais.py --index   # 3. gera o mapa e atualiza o index.html
```

A ordem importa: o passo 2 usa os nomes de urna e partidos baixados no passo 1. Os arquivos ficam em
`dados/2026/turno_1/`. Para o 2º turno, use `--turno 2` nos três comandos.

Para publicar uma nova versão, basta fazer commit e push do `index.html`; o GitHub Pages atualiza o site
em um ou dois minutos.

### Scripts

| Script | O que faz |
|---|---|
| `baixar_eleicao_rn.py` | Baixa os JSONs oficiais de resultado de todos os municípios do RN e monta `candidatos_municipio.csv`, `candidatos_zona.csv`, `resumo_municipio.csv` e `resumo_zona.csv` |
| `baixar_locais_votacao_rn.py` | Soma a votação por seção em cada local de votação e junta nome, endereço e coordenadas: `locais_votacao.csv` e `votos_local_votacao.csv` |
| `mapa_interativo_locais.py` | Gera o mapa interativo (HTML único). `--municipio MOSSORÓ` gera o mapa de um só município |
| `grafico_mapas_rn.py` | Mapas estáticos (PNG) do vencedor em cada município, para Presidente e Governador. Também guarda as cores dos partidos usadas em todos os gráficos |
| `grafico_locais_votacao.py` | Mapa estático (PNG) dos locais de votação de um município |
| `grafico_mossoro_zonas.py` | Gráfico de Mossoró por zona eleitoral |

## Fontes

- Resultados: [TSE, divulgação de resultados](https://resultados.tse.jus.br) (arquivos oficiais por município e zona).
- Votação por seção e cadastro de locais de votação: [Portal de Dados Abertos do TSE](https://dadosabertos.tse.jus.br).
- Malha municipal: [API de malhas do IBGE](https://servicodados.ibge.gov.br/api/docs/malhas).
- Mapa de fundo: Esri, HERE, Garmin, © OpenStreetMap.

Os percentuais são calculados sobre os votos válidos de cada local. Um local sem coordenadas no cadastro
do TSE (Escola Municipal Profª Maria da Paz Moreira, em Canguaretama) não aparece no mapa, mas seus votos
entram no total do município.

## Autoria

Feito por [Larissa Brito](https://www.linkedin.com/in/larissa-martins-2b93671a8/) para o Observatório Potiguar.
Encontrou algum erro? Abra uma [issue](https://github.com/observatoriopotiguar/eleicoes-2026-rn/issues).
