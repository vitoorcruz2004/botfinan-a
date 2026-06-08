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

def parse_gasto(texto: str, quem: str) -> dict | None:
    try:
        prompt = f"""Extraia dados deste gasto em portugues: "{texto}"

Retorne SOMENTE JSON valido assim:
{{"valor": 50.0, "descricao": "mercado", "categoria": "Mercado", "meio": "Debito", "parcelas": 1}}

Categorias: Mercado, Alimentacao, Transporte, Saude, Lazer, Contas, Roupas, Outros
Meios: Debito, PIX, Dinheiro, Credito a vista, Credito parcelado
Se nao identificar valor, retorne: null"""

        response = get_client().messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        if not raw or raw == "null":
            return None
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        if not data or "valor" not in data or not data["valor"]:
            return None
        data["quem"] = quem
        data["timestamp"] = datetime.now().isoformat()
        return data
    except Exception as e:
        print(f"Erro no parse: {e}")
        return None
