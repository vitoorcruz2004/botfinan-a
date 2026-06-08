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

SYSTEM_PROMPT = """Você é um parser financeiro. Extraia informações de gastos de mensagens em português informal.

Retorne SOMENTE um JSON válido com estes campos:
{
  "valor": número (float, obrigatório),
  "descricao": "string curta descrevendo o gasto",
  "categoria": "uma de: Mercado, Alimentação, Transporte, Saúde, Lazer, Contas, Roupas, Outros",
  "meio": "uma de: Débito, PIX, Dinheiro, Crédito à vista, Crédito parcelado",
  "parcelas": número inteiro (1 se não parcelado)
}
Se não conseguir identificar o valor, retorne null.
Não inclua markdown, texto adicional ou explicações. Apenas o JSON."""

def parse_gasto(texto: str, quem: str) -> dict | None:
    try:
        response = get_client().messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": texto}]
        )
        raw = response.content[0].text.strip()
        data = json.loads(raw)
        if data is None or "valor" not in data or data["valor"] is None:
            return None
        data["quem"] = quem
        data["timestamp"] = datetime.now().isoformat()
        return data
    except Exception as e:
        print(f"Erro no parse: {e}")
        return None
