import os
import json
import anthropic
from datetime import datetime

client = None

def get_client():
    global client
    if client is None:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return client

SYSTEM_PROMPT = """Voce e um parser financeiro. Extraia informacoes de gastos de mensagens em portugues informal.

Retorne SOMENTE um JSON valido com estes campos:
{"valor": numero float obrigatorio, "descricao": "string curta", "categoria": "uma de: Mercado, Alimentacao, Transporte, Saude, Lazer, Contas, Roupas, Outros", "meio": "uma de: Debito, PIX, Dinheiro, Credito a vista, Credito parcelado", "parcelas": numero inteiro 1 se nao parcelado}

Exemplos:
- "gastei 1786 no itau no credito" -> {"valor": 1786.0, "descricao": "itau", "categoria": "Outros", "meio": "Credito a vista", "parcelas": 1}
- "comprei tenis por 280 em 3x" -> {"valor": 280.0, "descricao": "tenis", "categoria": "Roupas", "meio": "Credito parcelado", "parcelas": 3}
- "paguei 47 no mercado no debito" -> {"valor": 47.0, "descricao": "mercado", "categoria": "Mercado", "meio": "Debito", "parcelas": 1}

Se nao conseguir identificar o valor, retorne null.
Nao inclua markdown, texto adicional ou explicacoes. Apenas o JSON."""

def parse_gasto(texto: str, quem: str) -> dict | None:
    try:
        response = get_client().messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            messages=[{"role": "user", "content": f"{SYSTEM_PROMPT}\n\nMensagem: {texto}"}]
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        if not raw or raw == "null":
            return None
        data = json.loads(raw)
        if not data or "valor" not in data or not data["valor"]:
            return None
        data["quem"] = quem
        data["timestamp"] = datetime.now().isoformat()
        return data
    except Exception as e:
        print(f"Erro no parse: {e}")
        return None
