import os
import json
import requests
from datetime import datetime
from collections import defaultdict
import anthropic

SCRIPT_URL = os.getenv("APPS_SCRIPT_URL")  # URL do Apps Script implantado


def get_mes_atual():
    return datetime.now().strftime("%Y-%m")


def _get_remoto(acao, mes=None):
    """Busca dados via Apps Script (GET)"""
    try:
        params = {"acao": acao, "mes": mes or get_mes_atual()}
        r = requests.get(SCRIPT_URL, params=params, timeout=10)
        d = r.json()
        return d.get("dados") if d.get("ok") else None
    except Exception as e:
        print(f"Erro GET {acao}: {e}")
        return None


def _post_remoto(payload):
    """Envia dados via Apps Script (POST)"""
    try:
        r = requests.post(SCRIPT_URL, json=payload, timeout=10)
        d = r.json()
        return d.get("ok", False)
    except Exception as e:
        print(f"Erro POST: {e}")
        return False


# ── GASTOS ──────────────────────────────────────────────────────────────────

def registrar_na_planilha(gasto):
    return _post_remoto(gasto)


def get_total_mes(categoria=None):
    resumo = get_resumo_mes()
    if not resumo:
        return 0.0
    if categoria:
        for item in resumo.get("por_categoria", []):
            if item["cat"] == categoria:
                return item["total"]
        return 0.0
    return resumo.get("total", 0.0)


def get_resumo_mes():
    return _get_remoto("resumo")


def get_historico_mes(limite=10):
    hist = _get_remoto("historico") or []
    return hist[:limite]


# ── ORÇAMENTO ────────────────────────────────────────────────────────────────
# Orçamento é salvo localmente no Railway via variável de ambiente
# e também postado no Apps Script para o app HTML ler

_orcamento_cache = {}


def get_orcamento():
    mes = get_mes_atual()
    if mes in _orcamento_cache:
        return {"total": _orcamento_cache[mes]}
    # tenta buscar do Apps Script
    dados = _get_remoto("orcamento")
    if dados and dados.get("total"):
        _orcamento_cache[mes] = dados["total"]
        return {"total": dados["total"]}
    return None


def set_orcamento(valor):
    mes = get_mes_atual()
    _orcamento_cache[mes] = valor
    # salva no Apps Script para sincronizar com o app HTML
    _post_remoto({
        "tipo": "orcamento",
        "mes": datetime.now().isoformat(),
        "valor": valor,
        "categoria": "",
        "origem": "bot",
    })


def get_orcamento_categorias():
    dados = _get_remoto("orcamento_cats")
    if isinstance(dados, dict):
        return dados
    return {}


# ── CONTAS FIXAS ────────────────────────────────────────────────────────────

def get_contas_fixas():
    return _get_remoto("contas") or []




# ── PARCELAS A VENCER ────────────────────────────────────────────────────────

def get_parcelas_mes(mes=None):
    """
    Busca todos os gastos parcelados de todos os meses e calcula
    quais parcelas vencem no mes especificado.
    Retorna lista de {descricao, valor_parcela, parcela_atual, total_parcelas}
    """
    if mes is None:
        mes = get_mes_atual()
    
    try:
        # Busca historico completo (sem filtro de mes)
        r = requests.get(SCRIPT_URL, params={"acao": "todos_parcelados"}, timeout=10)
        d = r.json()
        if not d.get("ok"):
            return []
        
        gastos_parcelados = d.get("dados", [])
        parcelas_mes = []
        
        from datetime import datetime
        ano_mes = datetime.strptime(mes, "%Y-%m")
        
        for g in gastos_parcelados:
            try:
                ts = datetime.fromisoformat(g["timestamp"].replace("Z", ""))
                n_parcelas = int(g.get("parcelas", 1))
                if n_parcelas <= 1:
                    continue
                
                valor_parcela = float(g["valor"]) / n_parcelas
                
                # Calcular em quais meses as parcelas caem
                for i in range(n_parcelas):
                    # Parcela i cai no mes da compra + i meses
                    mes_parcela_num = ts.month + i
                    ano_parcela = ts.year + (mes_parcela_num - 1) // 12
                    mes_parcela_num = ((mes_parcela_num - 1) % 12) + 1
                    
                    if ano_parcela == ano_mes.year and mes_parcela_num == ano_mes.month:
                        parcelas_mes.append({
                            "descricao": g.get("descricao", ""),
                            "valor_parcela": valor_parcela,
                            "parcela_atual": i + 1,
                            "total_parcelas": n_parcelas,
                            "quem": g.get("quem", ""),
                        })
                        break
            except Exception as e:
                print(f"Erro ao calcular parcela: {e}")
                continue
        
        return parcelas_mes
    except Exception as e:
        print(f"Erro get_parcelas_mes: {e}")
        return []


def get_total_parcelas_mes(mes=None):
    """Retorna o total das parcelas que vencem no mes"""
    parcelas = get_parcelas_mes(mes)
    return sum(p["valor_parcela"] for p in parcelas)

# ── INSIGHT COM IA ──────────────────────────────────────────────────────────

def gerar_insight_mensal():
    resumo = get_resumo_mes()
    if not resumo or not resumo.get("por_categoria"):
        return None

    total = resumo.get("total", 0)
    if total < 10:
        return None

    orcamento  = get_orcamento()
    fixas      = get_contas_fixas()
    hist       = get_historico_mes(limite=50)
    mes        = datetime.now().strftime("%B/%Y")

    linhas_cat    = "\n".join(f"- {d['cat']}: R$ {d['total']:.2f}" for d in resumo.get("por_categoria", []))
    linhas_pessoa = "\n".join(f"- {d['quem']}: R$ {d['total']:.2f}" for d in resumo.get("por_pessoa", []))
    linhas_fixas  = "\n".join(f"- {f['nome']}: R$ {f['valor']:.2f}" for f in fixas) if fixas else "nenhuma"
    orc_str       = f"R$ {orcamento['total']:.2f}" if orcamento else "nao definido"

    contexto = (
        f"Dados financeiros do casal em {mes}:\n\n"
        f"ORCAMENTO: {orc_str}\n"
        f"TOTAL GASTO: R$ {total:.2f}\n\n"
        f"POR CATEGORIA:\n{linhas_cat}\n\n"
        f"POR PESSOA:\n{linhas_pessoa}\n\n"
        f"CONTAS FIXAS:\n{linhas_fixas}\n"
        f"REGISTROS NO MES: {len(hist)}\n"
    )

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=(
                "Voce e um consultor financeiro simpatico para um casal brasileiro. "
                "Analise os dados e de insights praticos em portugues informal. "
                "Use emojis moderadamente. Maximo 5 paragrafos curtos. "
                "Use *negrito* para destacar pontos. Nao repita dados brutos."
            ),
            messages=[{"role": "user", "content": contexto}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"Erro insight: {e}")
        return None


# ── ZERAR MÊS ATUAL ─────────────────────────────────────────────────────────

def zerar_mes_atual():
    """Apaga todos os gastos do mês atual via Apps Script"""
    try:
        r = requests.post(SCRIPT_URL, json={
            "tipo": "zerar",
            "mes": get_mes_atual(),
        }, timeout=15)
        d = r.json()
        return d.get("ok", False)
    except Exception as e:
        print(f"Erro ao zerar: {e}")
        return False


# ── RESUMO DO MÊS ANTERIOR ──────────────────────────────────────────────────

def get_resumo_mes_anterior():
    """Busca resumo do mês anterior para envio automático"""
    from datetime import date
    hoje = date.today()
    if hoje.month == 1:
        mes = f"{hoje.year - 1}-12"
    else:
        mes = f"{hoje.year}-{str(hoje.month - 1).padStart(2, '0')}"
    # Python nao tem padStart, usar zfill
    ano = hoje.year if hoje.month > 1 else hoje.year - 1
    mes_num = hoje.month - 1 if hoje.month > 1 else 12
    mes = f"{ano}-{str(mes_num).zfill(2)}"
    try:
        r = requests.get(SCRIPT_URL, params={"acao": "resumo", "mes": mes}, timeout=10)
        d = r.json()
        return d.get("dados") if d.get("ok") else None
    except Exception as e:
        print(f"Erro resumo anterior: {e}")
        return None
