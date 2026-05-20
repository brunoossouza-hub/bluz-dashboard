#!/usr/bin/env python3
"""
process_cnj.py
==============
Baixa o CSV do Painel dos Grandes Litigantes do CNJ,
transforma para o formato do dashboard b/luz e gera:
  - litigantes.json  (dados atuais)
  - delta.json       (novidades vs. versão anterior)

Executado pelo GitHub Actions semanalmente.
"""

import csv
import json
import os
import sys
import urllib.request
import io
from datetime import datetime

# ──────────────────────────────────────────────
# CONFIGURAÇÃO
# ──────────────────────────────────────────────

# URL de download do CSV do CNJ.
# Se o CNJ alterar o endereço, atualize aqui.
CNJ_URL = "http://justica-em-numeros.cnj.jus.br/painel-litigantes/download"

# Onde salvar os arquivos de saída (raiz do repositório)
OUT_DIR = os.path.join(os.path.dirname(__file__), "..")

# Arquivo com os valores de fit definidos manualmente pela b/luz.
# Se existir, os valores são preservados na atualização.
FIT_OVERRIDES_FILE = os.path.join(OUT_DIR, "fit_overrides.json")

# Número máximo de litigantes a manter em ALL_LITIGANTES
TOP_N = 200

# Pontuação de fit padrão para litigantes novos (sem override manual)
DEFAULT_FIT = 55

# Mapeamento de segmentos do CNJ → segmentos do dashboard
# Ajuste conforme os valores reais que aparecerem no CSV do CNJ.
# Para ver os valores reais: rode o script com --inspecionar
SEGMENTO_MAP = {
    "BANCOS": ("Financeiro E Investimentos", "Bancos"),
    "BANCO": ("Financeiro E Investimentos", "Bancos"),
    "FINANCEIRA": ("Financeiro E Investimentos", "Bancos"),
    "SEGURADORA": ("Financeiro E Investimentos", "Seguradoras"),
    "SEGURO": ("Financeiro E Investimentos", "Seguradoras"),
    "PLANO DE SAUDE": ("Financeiro E Investimentos", "Seguradoras"),
    "COOPERATIVA DE CREDITO": ("Financeiro E Investimentos", "Corretoras / Distribuidoras"),
    "ENERGIA": ("Energia E Infraestrutura", "Concessionárias De Serviços Públicos"),
    "ELETRICA": ("Energia E Infraestrutura", "Concessionárias De Serviços Públicos"),
    "SANEAMENTO": ("Energia E Infraestrutura", "Concessionárias De Serviços Públicos"),
    "TELECOMUNICACOES": ("Tecnologia E Inovação", "Telecomunicações"),
    "TELEFONICA": ("Tecnologia E Inovação", "Telecomunicações"),
    "TECNOLOGIA": ("Tecnologia E Inovação", "Plataformas Digitais"),
    "INTERNET": ("Tecnologia E Inovação", "Plataformas Digitais"),
    "AVIACAO": ("Energia E Infraestrutura", "Logística E Transportes"),
    "AEREA": ("Energia E Infraestrutura", "Logística E Transportes"),
    "TRANSPORTE": ("Energia E Infraestrutura", "Logística E Transportes"),
    "VAREJO": ("Varejo E E-Commerce", "Plataformas De Comércio Eletrônico"),
    "COMERCIO": ("Varejo E E-Commerce", "Plataformas De Comércio Eletrônico"),
    "SAUDE": ("Saúde E Ciências Da Vida", "Operadoras De Plano De Saúde"),
    "HOSPITAL": ("Saúde E Ciências Da Vida", "Operadoras De Plano De Saúde"),
    "EDUCACAO": ("Educação", "Ensino Superior"),
    "UNIVERSIDADE": ("Educação", "Ensino Superior"),
    "MINERACAO": ("Indústria E Manufatura", "Empresas De Transformação"),
    "PETROLEO": ("Indústria E Manufatura", "Empresas De Transformação"),
    "INDUSTRIA": ("Indústria E Manufatura", "Empresas De Transformação"),
    "CONSTRUCAO": ("Imobiliário E Construção Civil", "Construtoras"),
    "IMOBILIARIA": ("Imobiliário E Construção Civil", "Construtoras"),
    "AGRO": ("Agronegócio", "Agronegócio"),
    "FEDERAL": ("Setor Público E Terceiro Setor", "Administração Pública"),
    "MUNICIPAL": ("Setor Público E Terceiro Setor", "Administração Pública"),
    "ESTADUAL": ("Setor Público E Terceiro Setor", "Administração Pública"),
    "INSS": ("Setor Público E Terceiro Setor", "Administração Pública"),
    "ASSOCIACAO": ("Serviços Profissionais", "Empresas De Serviços"),
    "SINDICATO": ("Serviços Profissionais", "Empresas De Serviços"),
}

# Mapeamento de ramos da justiça (CNJ → dashboard)
RAMO_MAP = {
    "JUSTIÇA ESTADUAL": "Justiça Estadual",
    "JUSTIÇA DO TRABALHO": "Justiça do Trabalho",
    "JUSTIÇA FEDERAL": "Justiça Federal",
    "SUPERIOR TRIBUNAL DE JUSTIÇA": "Superior Tribunal de Justiça",
    "SUPREMO TRIBUNAL FEDERAL": "Supremo Tribunal Federal",
    "TRIBUNAL SUPERIOR DO TRABALHO": "Tribunal Superior do Trabalho",
    "JUSTIÇA MILITAR": "Justiça Militar",
    "JUSTIÇA ELEITORAL": "Justiça Eleitoral",
}


# ──────────────────────────────────────────────
# FUNÇÕES AUXILIARES
# ──────────────────────────────────────────────

def normalizar_texto(s):
    """Remove acentos e padroniza para maiúsculas."""
    import unicodedata
    if not s:
        return ""
    s = str(s).upper().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def inferir_segmento(nome):
    """Infere seg e sub a partir do nome do litigante."""
    nome_norm = normalizar_texto(nome)
    for chave, (seg, sub) in SEGMENTO_MAP.items():
        if chave in nome_norm:
            return seg, sub
    return "Não Classificado", "Outros"


def mapear_ramo(ramo_cnj):
    """Converte o ramo da justiça do formato CNJ para o formato do dashboard."""
    ramo_norm = normalizar_texto(ramo_cnj)
    for chave, valor in RAMO_MAP.items():
        if normalizar_texto(chave) in ramo_norm:
            return valor
    return ramo_cnj.title() if ramo_cnj else "Não Informado"


def carregar_fit_overrides():
    """Carrega valores de fit definidos manualmente."""
    if os.path.exists(FIT_OVERRIDES_FILE):
        with open(FIT_OVERRIDES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def carregar_dados_anteriores():
    """Carrega litigantes.json anterior para gerar o delta."""
    caminho = os.path.join(OUT_DIR, "litigantes.json")
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
            return {l["nome"]: l for l in dados.get("ALL_LITIGANTES", [])}
    return {}


# ──────────────────────────────────────────────
# DOWNLOAD DO CSV
# ──────────────────────────────────────────────

def baixar_csv():
    """Baixa o CSV do CNJ. Retorna conteúdo como string."""
    print(f"[1/4] Baixando CSV do CNJ: {CNJ_URL}")
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; bluz-dashboard/1.0)"
    }
    req = urllib.request.Request(CNJ_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            # Tenta decodificar em UTF-8, depois latin-1
            try:
                return raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                return raw.decode("latin-1")
    except Exception as e:
        print(f"  ERRO ao baixar CSV: {e}")
        print("  Verifique se a URL do CNJ está correta.")
        print("  Execute com --inspecionar para ver as colunas disponíveis.")
        sys.exit(1)


def inspecionar_csv(conteudo):
    """Modo diagnóstico: mostra as primeiras linhas e colunas do CSV."""
    reader = csv.DictReader(io.StringIO(conteudo), delimiter=";")
    print("\n=== COLUNAS ENCONTRADAS NO CSV DO CNJ ===")
    for i, row in enumerate(reader):
        if i == 0:
            for j, (col, val) in enumerate(row.items()):
                print(f"  [{j}] '{col}' → ex: '{val}'")
        if i >= 4:
            break
    print("\nAjuste as variáveis COL_* no script com os nomes corretos das colunas.")
    sys.exit(0)


# ──────────────────────────────────────────────
# PROCESSAMENTO
# ──────────────────────────────────────────────

# Nomes possíveis para cada coluna no CSV do CNJ.
# O script tenta cada alias em ordem até encontrar um que exista.
# Se o CNJ mudar os nomes das colunas, adicione os novos aliases aqui.
COL_NOME    = ["nome_parte", "Parte", "parte", "NOME_PARTE", "Nome"]
COL_POLO    = ["tipo_polo", "polo", "Polo", "POLO", "tipo_parte"]
COL_RAMO    = ["ramo_justica", "Ramo", "ramo", "RAMO_JUSTICA", "segmento_justica"]
COL_NOVOS   = ["casos_novos", "Casos Novos", "novos", "CASOS_NOVOS", "processos_novos"]
COL_PEND    = ["casos_pendentes", "Casos Pendentes", "pendentes", "CASOS_PENDENTES"]
COL_ANO     = ["ano", "Ano", "ANO", "ano_referencia"]


def resolver_coluna(row, aliases):
    """Retorna o valor da primeira coluna que existir no dicionário."""
    for alias in aliases:
        if alias in row:
            return row[alias]
    return None


def processar_csv(conteudo, fit_overrides, dados_anteriores):
    """Transforma o CSV do CNJ em lista de litigantes para o dashboard."""
    print("[2/4] Processando CSV...")

    # Tenta ponto-e-vírgula, depois vírgula como separador
    for sep in [";", ","]:
        reader = csv.DictReader(io.StringIO(conteudo), delimiter=sep)
        rows = list(reader)
        if len(rows) > 0 and len(rows[0]) > 2:
            break

    if not rows:
        print("  ERRO: CSV vazio ou mal formatado.")
        sys.exit(1)

    print(f"  {len(rows)} linhas encontradas no CSV.")

    # Agrega por nome (soma novos e pendentes de todos os tribunais/anos)
    agregado = {}
    for row in rows:
        nome = resolver_coluna(row, COL_NOME)
        if not nome or not nome.strip():
            continue

        nome = nome.strip().title()

        # Filtra apenas polo passivo (empresa sendo processada)
        polo = resolver_coluna(row, COL_POLO) or ""
        if polo and "ativo" in polo.lower() and "passivo" not in polo.lower():
            continue  # Ignora linhas onde a empresa é a autora

        ramo_raw = resolver_coluna(row, COL_RAMO) or ""
        novos_raw = resolver_coluna(row, COL_NOVOS) or "0"
        pend_raw  = resolver_coluna(row, COL_PEND)  or "0"

        # Limpa valores numéricos (remove pontos de milhar, etc.)
        try:
            novos = int(str(novos_raw).replace(".", "").replace(",", "").strip() or "0")
            pend  = int(str(pend_raw).replace(".", "").replace(",", "").strip() or "0")
        except ValueError:
            continue

        ramo = mapear_ramo(ramo_raw)

        if nome not in agregado:
            agregado[nome] = {
                "nome": nome,
                "ramo": ramo,
                "novos": 0,
                "pendentes": 0,
            }

        agregado[nome]["novos"]     += novos
        agregado[nome]["pendentes"] += pend
        # Usa o ramo com mais processos (simplificação)
        if novos > agregado[nome].get("_max_novos", 0):
            agregado[nome]["ramo"] = ramo
            agregado[nome]["_max_novos"] = novos

    print(f"  {len(agregado)} litigantes únicos após agregação.")

    # Ordena por pendentes desc, pega top N
    lista = sorted(agregado.values(), key=lambda x: x["pendentes"], reverse=True)[:TOP_N]

    # Enriquece com seg, sub, fit e delta
    resultado = []
    for l in lista:
        nome = l["nome"]
        seg, sub = inferir_segmento(nome)
        fit = fit_overrides.get(nome, DEFAULT_FIT)

        # Delta: comparação com dados anteriores
        anterior = dados_anteriores.get(nome)
        if anterior:
            delta = l["pendentes"] - anterior["pendentes"]
        else:
            delta = l["novos"]  # Novo entrante: delta = novos

        # Remove campo auxiliar
        l.pop("_max_novos", None)

        resultado.append({
            "nome": nome,
            "seg": seg,
            "sub": sub,
            "ramo": l["ramo"],
            "novos": l["novos"],
            "pendentes": l["pendentes"],
            "delta": delta,
            "fit": fit,
        })

    return resultado


# ──────────────────────────────────────────────
# GERAÇÃO DOS ARQUIVOS DE SAÍDA
# ──────────────────────────────────────────────

def gerar_agregados(litigantes):
    """Gera os agregados por segmento e ramo para os KPIs do dashboard."""
    seg_agg = {}
    ramo_agg = {}
    for l in litigantes:
        seg_agg[l["seg"]] = seg_agg.get(l["seg"], 0) + l["novos"]
        ramo_agg[l["ramo"]] = ramo_agg.get(l["ramo"], 0) + l["novos"]

    segmentos = [{"n": k, "v": v} for k, v in
                 sorted(seg_agg.items(), key=lambda x: -x[1])]
    ramos = [{"n": k, "v": v} for k, v in
             sorted(ramo_agg.items(), key=lambda x: -x[1])]
    return segmentos, ramos


def gerar_delta_json(litigantes, dados_anteriores):
    """Gera o arquivo delta.json com novidades e maiores variações."""
    nomes_atuais = {l["nome"] for l in litigantes}
    nomes_anteriores = set(dados_anteriores.keys())

    entrants = [l for l in litigantes if l["nome"] not in nomes_anteriores]
    exits    = [{"nome": n} for n in nomes_anteriores if n not in nomes_atuais]

    # Maiores variações absolutas de delta
    movers = sorted(litigantes, key=lambda x: abs(x["delta"]), reverse=True)[:10]

    return {
        "gerado_em": datetime.utcnow().isoformat() + "Z",
        "novos_entrantes": entrants[:10],
        "saidas": exits[:10],
        "maiores_variacoes": movers,
    }


def salvar_json(obj, nome_arquivo):
    caminho = os.path.join(OUT_DIR, nome_arquivo)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"  Salvo: {caminho}")


def gerar_fit_overrides_inicial(litigantes):
    """Cria fit_overrides.json inicial com os valores atuais do HTML."""
    caminho = FIT_OVERRIDES_FILE
    if os.path.exists(caminho):
        print(f"  fit_overrides.json já existe, pulando criação.")
        return
    overrides = {l["nome"]: l["fit"] for l in litigantes}
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(overrides, f, ensure_ascii=False, indent=2)
    print(f"  Criado fit_overrides.json com {len(overrides)} entradas.")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    modo_inspecionar = "--inspecionar" in sys.argv

    conteudo = baixar_csv()

    if modo_inspecionar:
        inspecionar_csv(conteudo)  # Encerra aqui

    fit_overrides = carregar_fit_overrides()
    dados_anteriores = carregar_dados_anteriores()

    litigantes = processar_csv(conteudo, fit_overrides, dados_anteriores)

    print(f"[3/4] Gerando arquivos JSON...")

    segmentos, ramos = gerar_agregados(litigantes)
    delta = gerar_delta_json(litigantes, dados_anteriores)

    saida = {
        "gerado_em": datetime.utcnow().isoformat() + "Z",
        "total": len(litigantes),
        "ALL_LITIGANTES": litigantes,
        "segmentosBR": segmentos,
        "ramos": ramos,
    }

    salvar_json(saida, "litigantes.json")
    salvar_json(delta, "delta.json")
    gerar_fit_overrides_inicial(litigantes)

    print(f"[4/4] Concluído. {len(litigantes)} litigantes processados.")
    print(f"      Novos entrantes: {len(delta['novos_entrantes'])}")
    print(f"      Saídas: {len(delta['saidas'])}")


if __name__ == "__main__":
    main()
