#!/usr/bin/env python3
"""
process_cnj.py
==============
Consulta o DataJud (API pública do CNJ) para obter os maiores litigantes
de cada tribunal e gera litigantes.json e delta.json.

Fonte: https://api-publica.datajud.cnj.jus.br
Chave pública: publicada pelo CNJ em datajud-wiki.cnj.jus.br/api-publica/acesso
"""

import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

# ── CONFIGURAÇÃO ──────────────────────────────────────────────────────────────

# Chave pública do DataJud (sem cadastro). CNJ pode atualizá-la — verifique em:
# https://datajud-wiki.cnj.jus.br/api-publica/acesso
API_KEY  = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
BASE_URL = "https://api-publica.datajud.cnj.jus.br"

# Tribunais consultados — cobertura de ~90% do volume nacional
# Adicione ou remova conforme interesse
TRIBUNAIS = [
    # Justiça Estadual (maiores)
    ("api_publica_tjsp", "Justiça Estadual"),
    ("api_publica_tjrj", "Justiça Estadual"),
    ("api_publica_tjmg", "Justiça Estadual"),
    ("api_publica_tjrs", "Justiça Estadual"),
    ("api_publica_tjpr", "Justiça Estadual"),
    ("api_publica_tjba", "Justiça Estadual"),
    ("api_publica_tjsc", "Justiça Estadual"),
    ("api_publica_tjce", "Justiça Estadual"),
    ("api_publica_tjpe", "Justiça Estadual"),
    ("api_publica_tjgo", "Justiça Estadual"),
    # Justiça Federal
    ("api_publica_trf1", "Justiça Federal"),
    ("api_publica_trf2", "Justiça Federal"),
    ("api_publica_trf3", "Justiça Federal"),
    ("api_publica_trf4", "Justiça Federal"),
    # Justiça do Trabalho (maiores)
    ("api_publica_trt2", "Justiça do Trabalho"),
    ("api_publica_trt3", "Justiça do Trabalho"),
    ("api_publica_trt4", "Justiça do Trabalho"),
    ("api_publica_trt9", "Justiça do Trabalho"),
    ("api_publica_trt15", "Justiça do Trabalho"),
    # Tribunais Superiores
    ("api_publica_stj", "Superior Tribunal de Justiça"),
]

TOP_POR_TRIBUNAL = 30   # quantos litigantes pegar por tribunal
TOP_FINAL        = 200  # quantos litigantes no resultado final
DEFAULT_FIT      = 55
ANO_REFERENCIA   = datetime.now(timezone.utc).year  # ano corrente para "novos"

OUT_DIR          = os.path.join(os.path.dirname(__file__), "..")
FIT_FILE         = os.path.join(OUT_DIR, "fit_overrides.json")

# ── MAPEAMENTO SEGMENTO ───────────────────────────────────────────────────────

import unicodedata

def norm(s):
    s = str(s).upper().strip()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

SEG_MAP = [
    # (fragmento_no_nome, segmento, sub)
    ("BANCO ",         "Financeiro E Investimentos", "Bancos"),
    ("BANCARIO",       "Financeiro E Investimentos", "Bancos"),
    ("FINANCEIRA",     "Financeiro E Investimentos", "Bancos"),
    ("FINANCIAMENTO",  "Financeiro E Investimentos", "Bancos"),
    ("CREDITO",        "Financeiro E Investimentos", "Bancos"),
    ("CAIXA ECONOMIC", "Financeiro E Investimentos", "Bancos"),
    ("BRADESCO",       "Financeiro E Investimentos", "Bancos"),
    ("ITAU",           "Financeiro E Investimentos", "Bancos"),
    ("SANTANDER",      "Financeiro E Investimentos", "Bancos"),
    ("NUBANK",         "Financeiro E Investimentos", "Bancos"),
    ("NU PAGAMENTOS",  "Financeiro E Investimentos", "Bancos"),
    ("INTER ",         "Financeiro E Investimentos", "Bancos"),
    ("SEGURO",         "Financeiro E Investimentos", "Seguradoras"),
    ("SEGUROS",        "Financeiro E Investimentos", "Seguradoras"),
    ("SEGURADORA",     "Financeiro E Investimentos", "Seguradoras"),
    ("PREVIDENCIA",    "Financeiro E Investimentos", "Seguradoras"),
    ("PLANO DE SAUDE", "Financeiro E Investimentos", "Seguradoras"),
    ("UNIMED",         "Saúde E Ciências Da Vida",   "Operadoras De Plano De Saúde"),
    ("HAPVIDA",        "Saúde E Ciências Da Vida",   "Operadoras De Plano De Saúde"),
    ("INTERMEDICA",    "Saúde E Ciências Da Vida",   "Operadoras De Plano De Saúde"),
    ("AMIL",           "Saúde E Ciências Da Vida",   "Operadoras De Plano De Saúde"),
    ("HOSPITAL",       "Saúde E Ciências Da Vida",   "Operadoras De Plano De Saúde"),
    ("TELEFONIC",      "Tecnologia E Inovação",       "Telecomunicações"),
    ("CLARO",          "Tecnologia E Inovação",       "Telecomunicações"),
    ("TIM ",           "Tecnologia E Inovação",       "Telecomunicações"),
    ("OI ",            "Tecnologia E Inovação",       "Telecomunicações"),
    ("TELECOM",        "Tecnologia E Inovação",       "Telecomunicações"),
    ("TECNOLOGIA",     "Tecnologia E Inovação",       "Plataformas Digitais"),
    ("FACEBOOK",       "Tecnologia E Inovação",       "Plataformas Digitais"),
    ("GOOGLE",         "Tecnologia E Inovação",       "Plataformas Digitais"),
    ("UBER",           "Tecnologia E Inovação",       "Plataformas Digitais"),
    ("MERCADO LIVRE",  "Varejo E E-Commerce",         "Plataformas De Comércio Eletrônico"),
    ("MAGAZINE",       "Varejo E E-Commerce",         "Plataformas De Comércio Eletrônico"),
    ("AMERICANAS",     "Varejo E E-Commerce",         "Plataformas De Comércio Eletrônico"),
    ("ENERGIA",        "Energia E Infraestrutura",    "Concessionárias De Serviços Públicos"),
    ("ELETRICA",       "Energia E Infraestrutura",    "Concessionárias De Serviços Públicos"),
    ("ELETRICIDADE",   "Energia E Infraestrutura",    "Concessionárias De Serviços Públicos"),
    ("ENEL",           "Energia E Infraestrutura",    "Concessionárias De Serviços Públicos"),
    ("CEMIG",          "Energia E Infraestrutura",    "Concessionárias De Serviços Públicos"),
    ("COPEL",          "Energia E Infraestrutura",    "Concessionárias De Serviços Públicos"),
    ("LIGHT ",         "Energia E Infraestrutura",    "Concessionárias De Serviços Públicos"),
    ("SANEAMENTO",     "Energia E Infraestrutura",    "Concessionárias De Serviços Públicos"),
    ("SABESP",         "Energia E Infraestrutura",    "Concessionárias De Serviços Públicos"),
    ("AEREA",          "Energia E Infraestrutura",    "Logística E Transportes"),
    ("LINHAS AEREAS",  "Energia E Infraestrutura",    "Logística E Transportes"),
    ("AVIACAO",        "Energia E Infraestrutura",    "Logística E Transportes"),
    ("AZUL ",          "Energia E Infraestrutura",    "Logística E Transportes"),
    ("LATAM",          "Energia E Infraestrutura",    "Logística E Transportes"),
    ("GOL ",           "Energia E Infraestrutura",    "Logística E Transportes"),
    ("CORREIOS",       "Energia E Infraestrutura",    "Logística E Transportes"),
    ("EDUCACAO",       "Educação",                    "Ensino Superior"),
    ("UNIVERSIDADE",   "Educação",                    "Ensino Superior"),
    ("FACULDADE",      "Educação",                    "Ensino Superior"),
    ("MINERACAO",      "Indústria E Manufatura",      "Empresas De Transformação"),
    ("MINERADORA",     "Indústria E Manufatura",      "Empresas De Transformação"),
    ("PETROLEO",       "Indústria E Manufatura",      "Empresas De Transformação"),
    ("PETROBRAS",      "Indústria E Manufatura",      "Empresas De Transformação"),
    ("VALE ",          "Indústria E Manufatura",      "Empresas De Transformação"),
    ("CONSTRUCAO",     "Imobiliário E Construção Civil", "Construtoras"),
    ("CONSTRUTORA",    "Imobiliário E Construção Civil", "Construtoras"),
    ("INCORPORADORA",  "Imobiliário E Construção Civil", "Construtoras"),
    ("FEDERAL",        "Setor Público E Terceiro Setor", "Administração Pública"),
    ("MUNICIPAL",      "Setor Público E Terceiro Setor", "Administração Pública"),
    ("PREFEITURA",     "Setor Público E Terceiro Setor", "Administração Pública"),
    ("ESTADO DE",      "Setor Público E Terceiro Setor", "Administração Pública"),
    ("INSS",           "Setor Público E Terceiro Setor", "Administração Pública"),
    ("PGFN",           "Setor Público E Terceiro Setor", "Administração Pública"),
    ("ASSOCIACAO",     "Serviços Profissionais",      "Empresas De Serviços"),
    ("COOPERATIVA",    "Serviços Profissionais",      "Empresas De Serviços"),
    ("SERASA",         "Serviços Profissionais",      "Empresas De Serviços"),
    ("RECOVERY",       "Serviços Profissionais",      "Empresas De Serviços"),
]

def inferir_segmento(nome):
    n = norm(nome)
    for frag, seg, sub in SEG_MAP:
        if frag in n:
            return seg, sub
    return "Não Classificado", "Outros"

# ── DATAJUD API ───────────────────────────────────────────────────────────────

HEADERS = {
    "Authorization": f"APIKey {API_KEY}",
    "Content-Type": "application/json",
}

def datajud_post(alias, payload, tentativas=3):
    url  = f"{BASE_URL}/{alias}/_search"
    data = json.dumps(payload).encode()
    for t in range(tentativas):
        req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:200]
            if e.code == 429:
                time.sleep(5 * (t + 1))
                continue
            print(f"    HTTP {e.code} em {alias}: {msg}")
            return None
        except Exception as e:
            print(f"    Erro em {alias}: {e}")
            if t < tentativas - 1:
                time.sleep(3)
    return None

def buscar_top_litigantes(alias, ramo):
    """
    Retorna lista de {nome, novos, pendentes} para um tribunal.
    Tenta aggregation; se não suportado, usa search + contagem.
    """
    # --- Tentativa 1: aggregation nested (mais eficiente) ---
    payload_agg = {
        "size": 0,
        "aggs": {
            "partes": {
                "nested": {"path": "partes"},
                "aggs": {
                    "passivo": {
                        "filter": {"term": {"partes.tipo.keyword": "Passivo"}},
                        "aggs": {
                            "top": {
                                "terms": {
                                    "field": "partes.nome.keyword",
                                    "size": TOP_POR_TRIBUNAL,
                                    "min_doc_count": 5
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    res = datajud_post(alias, payload_agg)
    buckets = None
    if res:
        try:
            buckets = res["aggregations"]["partes"]["passivo"]["top"]["buckets"]
        except (KeyError, TypeError):
            pass

    # --- Tentativa 2: aggregation flat (sem nested) ---
    if buckets is None:
        payload_flat = {
            "size": 0,
            "aggs": {
                "top_partes": {
                    "terms": {
                        "field": "partes.nome.keyword",
                        "size": TOP_POR_TRIBUNAL,
                        "min_doc_count": 5
                    }
                }
            }
        }
        res2 = datajud_post(alias, payload_flat)
        if res2:
            try:
                buckets = res2["aggregations"]["top_partes"]["buckets"]
            except (KeyError, TypeError):
                pass

    if not buckets:
        print(f"    ⚠ {alias}: aggregation não suportada, pulando.")
        return []

    # Conta processos novos no ano corrente para cada parte
    novos_map = {}
    for b in buckets[:20]:  # limita para não sobrecarregar a API
        nome = b["key"]
        total_pendentes = b["doc_count"]

        # Query para novos no ano corrente
        payload_novos = {
            "size": 0,
            "query": {
                "bool": {
                    "must": [
                        {"nested": {
                            "path": "partes",
                            "query": {"term": {"partes.nome.keyword": nome}}
                        }},
                        {"range": {
                            "dataAjuizamento": {
                                "gte": f"{ANO_REFERENCIA}-01-01",
                                "lte": f"{ANO_REFERENCIA}-12-31"
                            }
                        }}
                    ]
                }
            }
        }
        res_n = datajud_post(alias, payload_novos)
        novos = 0
        if res_n:
            try:
                novos = res_n["hits"]["total"]["value"]
            except (KeyError, TypeError):
                pass

        novos_map[nome] = {"pendentes": total_pendentes, "novos": novos}
        time.sleep(0.15)  # respeita rate limit

    return [
        {"nome": b["key"], **novos_map.get(b["key"], {"pendentes": b["doc_count"], "novos": 0})}
        for b in buckets
        if b["key"] in novos_map
    ]

# ── PROCESSAMENTO PRINCIPAL ───────────────────────────────────────────────────

def carregar_fit_overrides():
    if os.path.exists(FIT_FILE):
        with open(FIT_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith("_")}
    return {}

def carregar_dados_anteriores():
    caminho = os.path.join(OUT_DIR, "litigantes.json")
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
            return {l["nome"]: l for l in d.get("ALL_LITIGANTES", [])}
    return {}

def salvar(obj, nome):
    caminho = os.path.join(OUT_DIR, nome)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"  Salvo: {caminho}")

def main():
    print("=" * 55)
    print("b/luz — Atualização DataJud")
    print("=" * 55)

    fit_overrides   = carregar_fit_overrides()
    dados_anteriores = carregar_dados_anteriores()

    # Agrega resultados por nome de parte (todos os tribunais)
    agregado = {}  # nome → {pendentes, novos, ramo, ramos_count}

    total_tribunais = len(TRIBUNAIS)
    for i, (alias, ramo) in enumerate(TRIBUNAIS, 1):
        print(f"\n[{i}/{total_tribunais}] {alias} ({ramo})")
        resultados = buscar_top_litigantes(alias, ramo)
        print(f"    {len(resultados)} litigantes encontrados")

        for r in resultados:
            nome = r["nome"].strip().title()
            if nome not in agregado:
                agregado[nome] = {"pendentes": 0, "novos": 0, "ramo": ramo, "_count": 0}
            agregado[nome]["pendentes"] += r["pendentes"]
            agregado[nome]["novos"]     += r["novos"]
            agregado[nome]["_count"]    += 1
            # Ramo com mais ocorrências vence
            if r.get("novos", 0) > agregado[nome].get("_max_novos", 0):
                agregado[nome]["ramo"] = ramo
                agregado[nome]["_max_novos"] = r["novos"]

        time.sleep(0.5)  # pausa entre tribunais

    print(f"\n{len(agregado)} litigantes únicos agregados.")

    if len(agregado) == 0:
        print("\n⚠  Nenhum dado retornado. Possíveis causas:")
        print("   1. A chave da API do DataJud mudou.")
        print("      Verifique em: https://datajud-wiki.cnj.jus.br/api-publica/acesso")
        print("      Atualize API_KEY na linha 18 deste arquivo.")
        print("   2. O DataJud está temporariamente fora do ar.")
        print("   Mantendo dados anteriores sem alteração.")
        sys.exit(0)

    # Ordena e limita
    lista = sorted(agregado.values(), key=lambda x: x["pendentes"], reverse=True)
    lista_final = []

    for l in lista[:TOP_FINAL]:
        # Adiciona nome de volta (estava só na chave)
        pass

    # Reconstroi com nome
    lista_com_nome = []
    for nome, dados in sorted(agregado.items(), key=lambda x: -x[1]["pendentes"])[:TOP_FINAL]:
        seg, sub = inferir_segmento(nome)
        fit = fit_overrides.get(nome, DEFAULT_FIT)

        anterior = dados_anteriores.get(nome)
        delta = dados["pendentes"] - anterior["pendentes"] if anterior else dados["novos"]

        dados.pop("_count", None)
        dados.pop("_max_novos", None)

        lista_com_nome.append({
            "nome": nome,
            "seg": seg,
            "sub": sub,
            "ramo": dados["ramo"],
            "novos": dados["novos"],
            "pendentes": dados["pendentes"],
            "delta": delta,
            "fit": fit,
        })

    # Agrega segmentos e ramos
    seg_agg  = {}
    ramo_agg = {}
    for l in lista_com_nome:
        seg_agg[l["seg"]]   = seg_agg.get(l["seg"], 0)   + l["novos"]
        ramo_agg[l["ramo"]] = ramo_agg.get(l["ramo"], 0) + l["novos"]

    segmentos = [{"n": k, "v": v} for k, v in sorted(seg_agg.items(),  key=lambda x: -x[1])]
    ramos     = [{"n": k, "v": v} for k, v in sorted(ramo_agg.items(), key=lambda x: -x[1])]

    # Delta
    nomes_atuais    = {l["nome"] for l in lista_com_nome}
    nomes_anteriores = set(dados_anteriores.keys())
    delta_data = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "novos_entrantes": [l for l in lista_com_nome if l["nome"] not in nomes_anteriores][:10],
        "saidas": [{"nome": n} for n in nomes_anteriores if n not in nomes_atuais][:10],
        "maiores_variacoes": sorted(lista_com_nome, key=lambda x: abs(x["delta"]), reverse=True)[:10],
    }

    saida = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "total": len(lista_com_nome),
        "ALL_LITIGANTES": lista_com_nome,
        "segmentosBR": segmentos,
        "ramos": ramos,
    }

    print("\nSalvando arquivos...")
    salvar(saida, "litigantes.json")
    salvar(delta_data, "delta.json")

    # Cria/atualiza fit_overrides
    overrides_atuais = {l["nome"]: l["fit"] for l in lista_com_nome}
    overrides_atuais.update(fit_overrides)  # preserva overrides manuais
    overrides_atuais["_instrucoes"] = "Edite os valores de fit (0-100). São preservados a cada atualização."
    salvar(overrides_atuais, "fit_overrides.json")

    print(f"\n✅ Concluído: {len(lista_com_nome)} litigantes | "
          f"{len(delta_data['novos_entrantes'])} novos | "
          f"{len(delta_data['saidas'])} saídas")

if __name__ == "__main__":
    main()
