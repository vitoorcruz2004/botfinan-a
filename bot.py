import os
import re
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from parser_gasto import parse_gasto
from sheets import (
    registrar_na_planilha,
    get_resumo_mes,
    get_orcamento,
    set_orcamento,
    get_total_mes,
    get_contas_fixas,
    get_orcamento_categorias,
    get_historico_mes,
    gerar_insight_mensal,
    zerar_mes_atual,
)

logging.basicConfig(level=logging.INFO)
ALLOWED_IDS = os.getenv("ALLOWED_IDS", "").split(",")


def autorizado(update: Update) -> bool:
    uid = str(update.effective_user.id)
    return not ALLOWED_IDS or uid in ALLOWED_IDS


def fmt(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def barra_progresso(pct: float) -> str:
    filled = round(pct / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {pct:.0f}%"


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return
    orcamento = get_orcamento()
    if not orcamento:
        await update.message.reply_text(
            "👋 Oi! Sou o bot de finanças do casal.\n\n"
            "Para começar, me diz: *qual é o limite de gastos do mês?*\n\n"
            "Exemplo: _limite 3000_ ou manda /limite 4500",
            parse_mode="Markdown",
        )
    else:
        await ajuda(update, ctx)


async def ajuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return
    await update.message.reply_text(
        "📖 *Comandos disponíveis:*\n\n"
        "💬 *Registrar gasto* — só mandar em texto livre\n"
        "  Ex: _gastei 47 no mercado no débito_\n"
        "  Ex: _comprei tênis por 280 em 3x_\n\n"
        "/saldo — quanto ainda posso gastar\n"
        "/resumo — total do mês por categoria\n"
        "/contas — contas fixas e vencimentos\n"
        "/limite [valor] — definir orçamento mensal\n"
        "/historico — últimos 10 gastos\n"
        "/insight — análise inteligente do mês\n"
        "/zerar — zerar gastos do mês atual\n"
        "/ajuda — este menu",
        parse_mode="Markdown",
    )


async def cmd_limite(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return
    args = ctx.args
    if not args:
        orcamento = get_orcamento()
        if orcamento:
            await update.message.reply_text(
                f"💰 Orçamento atual: *{fmt(orcamento['total'])}*\n"
                f"Para mudar: /limite 3500",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Nenhum orçamento definido. Use: /limite 3000")
        return
    try:
        valor = float(args[0].replace(",", "."))
        set_orcamento(valor)
        mes = datetime.now().strftime("%B/%Y")
        await update.message.reply_text(
            f"✅ Orçamento de *{fmt(valor)}* definido para {mes}!\n\n"
            f"Use /saldo a qualquer hora para ver quanto ainda sobra. 💪",
            parse_mode="Markdown",
        )
    except Exception:
        await update.message.reply_text("Valor inválido. Use: /limite 3000")


async def cmd_saldo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return
    orcamento = get_orcamento()
    if not orcamento:
        await update.message.reply_text("Nenhum orçamento definido ainda. Use /limite 3000")
        return

    limite = orcamento["total"]
    total_gasto = get_total_mes()
    fixas = get_contas_fixas()
    total_fixas = sum(f["valor"] for f in fixas)
    comprometido = total_gasto + total_fixas
    saldo = limite - comprometido
    pct = min((comprometido / limite) * 100, 100) if limite > 0 else 0
    emoji = "🟢" if pct < 70 else ("🟡" if pct < 90 else "🔴")

    msg = (
        f"{emoji} *Saldo do mês*\n\n"
        f"Orçamento: {fmt(limite)}\n"
        f"Gastos lançados: {fmt(total_gasto)}\n"
        f"Contas fixas: {fmt(total_fixas)}\n"
        f"Comprometido: {fmt(comprometido)}\n"
        f"{barra_progresso(pct)}\n\n"
        f"*Disponível: {fmt(max(saldo, 0))}*"
    )
    if saldo < 0:
        msg += f"\n\n⚠️ Orçamento estourado em {fmt(abs(saldo))}!"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_resumo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return
    dados = get_resumo_mes()
    if not dados or not dados.get("por_categoria"):
        await update.message.reply_text("Nenhum gasto registrado este mês ainda.")
        return

    total = sum(d["total"] for d in dados["por_categoria"])
    mes = datetime.now().strftime("%B/%Y")
    msg = f"📊 *Resumo de {mes}*\n\n*Por categoria:*\n"
    for item in dados["por_categoria"]:
        pct = (item["total"] / total * 100) if total > 0 else 0
        msg += f"• {item['cat']}: {fmt(item['total'])} ({pct:.0f}%)\n"

    msg += "\n*Por pessoa:*\n"
    for item in dados.get("por_pessoa", []):
        msg += f"• {item['quem']}: {fmt(item['total'])}\n"

    msg += f"\n💸 *Total: {fmt(total)}*"

    orcamento = get_orcamento()
    if orcamento:
        saldo = orcamento["total"] - total
        msg += f"\n📦 Orçamento: {fmt(orcamento['total'])}"
        msg += f"\n{'✅' if saldo >= 0 else '🔴'} Disponível: {fmt(max(saldo, 0))}"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_contas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return
    contas = get_contas_fixas()
    if not contas:
        await update.message.reply_text(
            "Nenhuma conta fixa cadastrada ainda.\n\n"
            "Cadastre na aba 'Fixas' da planilha com as colunas:\n"
            "Nome | Valor | Dia vencimento | Categoria"
        )
        return

    hoje = datetime.now().day
    msg = "📋 *Contas fixas do mês:*\n\n"
    total = 0
    for c in sorted(contas, key=lambda x: x.get("dia", 31)):
        dia = c.get("dia", "?")
        status = "⏳" if isinstance(dia, int) and dia >= hoje else "✅"
        msg += f"{status} {c['nome']}: {fmt(c['valor'])}"
        if isinstance(dia, int):
            msg += f" (dia {dia})"
        msg += "\n"
        total += c["valor"]
    msg += f"\n💰 *Total fixo: {fmt(total)}*"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_historico(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return
    hist = get_historico_mes(limite=10)
    if not hist:
        await update.message.reply_text("Nenhum gasto registrado este mês.")
        return
    msg = "🕐 *Últimos 10 gastos:*\n\n"
    for g in hist:
        ts = datetime.fromisoformat(g["timestamp"])
        data = ts.strftime("%d/%m %H:%M")
        origem = " [bot]" if g.get("origem") == "bot" else " [app]"
        msg += f"• {data}{origem}\n  {fmt(g['valor'])} · {g['descricao']} · {g['quem']}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_zerar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return
    args = ctx.args
    if not args or args[0].lower() != "confirmar":
        mes = datetime.now().strftime("%B/%Y")
        total = get_total_mes()
        await update.message.reply_text(
            f"Tem certeza que quer zerar os gastos de {mes}?\n\n"
            f"Total atual: {fmt(total)}\n\n"
            f"Para confirmar, mande:\n/zerar confirmar",
        )
        return
    ok = zerar_mes_atual()
    if ok:
        await update.message.reply_text(
            f"Gastos de {datetime.now().strftime('%B/%Y')} zerados! "
            f"Pode comecar a registrar do zero."
        )
    else:
        await update.message.reply_text("Erro ao zerar. Tenta de novo.")


async def cmd_insight(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return
    await update.message.reply_text("🤖 Analisando seus gastos com IA... aguarda!")
    insight = gerar_insight_mensal()
    if not insight:
        await update.message.reply_text(
            "Dados insuficientes para análise ainda.\n"
            "Registre mais gastos e tente no fim do mês!"
        )
        return
    await update.message.reply_text(insight, parse_mode="Markdown")


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return

    texto = update.message.text
    texto_lower = texto.lower().strip()

    # Detecta definição de orçamento em texto livre
    for kw in ["limite", "orcamento", "orçamento", "budget", "teto"]:
        if kw in texto_lower:
            nums = re.findall(r"\d+(?:[.,]\d{1,2})?", texto_lower)
            if nums:
                try:
                    valor = float(nums[0].replace(",", "."))
                    set_orcamento(valor)
                    await update.message.reply_text(
                        f"✅ Orçamento de *{fmt(valor)}* definido!\n"
                        f"Use /saldo a qualquer hora para ver quanto sobra.",
                        parse_mode="Markdown",
                    )
                    return
                except Exception:
                    pass

    quem = update.effective_user.first_name
    resultado = parse_gasto(texto, quem)

    if not resultado:
        await update.message.reply_text(
            "Não consegui identificar o valor. 🤔\n"
            "Tenta assim: _gastei 50 no mercado no débito_\n\n"
            "Use /ajuda para ver todos os comandos.",
            parse_mode="Markdown",
        )
        return

    ok = registrar_na_planilha(resultado)
    if not ok:
        await update.message.reply_text("❌ Erro ao salvar na planilha. Tenta de novo.")
        return

    parcel_info = (
        f"\n💳 {resultado['parcelas']}x de {fmt(resultado['valor'] / resultado['parcelas'])}"
        if resultado["parcelas"] > 1
        else ""
    )
    msg = (
        f"✅ *Registrado!*\n\n"
        f"📝 {resultado['descricao']}\n"
        f"💰 {fmt(resultado['valor'])}\n"
        f"🏷️ {resultado['categoria']}\n"
        f"💳 {resultado['meio']}{parcel_info}\n"
        f"👤 {resultado['quem']}"
    )

    # Alerta por categoria
    orcamento_cats = get_orcamento_categorias()
    cat = resultado["categoria"]
    if cat in orcamento_cats:
        total_cat = get_total_mes(categoria=cat)
        limite_cat = orcamento_cats[cat]
        pct_cat = (total_cat / limite_cat * 100) if limite_cat > 0 else 0
        if pct_cat >= 100:
            msg += f"\n\n🔴 *Limite de {cat} estourado!* ({fmt(total_cat)} / {fmt(limite_cat)})"
        elif pct_cat >= 90:
            msg += f"\n\n🟡 *{cat}:* {pct_cat:.0f}% do limite ({fmt(total_cat)} / {fmt(limite_cat)})"
        elif pct_cat >= 70:
            msg += f"\n\n🟡 {cat}: {pct_cat:.0f}% do limite usado"

    await update.message.reply_text(msg, parse_mode="Markdown")

    # Alerta de orçamento geral (mensagem separada só se alertar)
    orcamento = get_orcamento()
    if orcamento:
        total_gasto = get_total_mes()
        fixas = get_contas_fixas()
        total_fixas = sum(f["valor"] for f in fixas)
        comprometido = total_gasto + total_fixas
        limite = orcamento["total"]
        pct = (comprometido / limite * 100) if limite > 0 else 0

        if pct >= 100:
            await update.message.reply_text(
                f"🔴 *ATENÇÃO: Orçamento estourado!*\n"
                f"Comprometido: {fmt(comprometido)} de {fmt(limite)}",
                parse_mode="Markdown",
            )
        elif pct >= 90:
            await update.message.reply_text(
                f"🔴 *Quase no limite!* {pct:.0f}% do orçamento usado.\n"
                f"Disponível: {fmt(limite - comprometido)}",
                parse_mode="Markdown",
            )
        elif pct >= 70:
            await update.message.reply_text(
                f"🟡 {pct:.0f}% do orçamento usado. Disponível: {fmt(limite - comprometido)}",
                parse_mode="Markdown",
            )


if __name__ == "__main__":
    token = os.getenv("TELEGRAM_TOKEN")
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("help", ajuda))
    app.add_handler(CommandHandler("limite", cmd_limite))
    app.add_handler(CommandHandler("orcamento", cmd_limite))
    app.add_handler(CommandHandler("saldo", cmd_saldo))
    app.add_handler(CommandHandler("resumo", cmd_resumo))
    app.add_handler(CommandHandler("contas", cmd_contas))
    app.add_handler(CommandHandler("historico", cmd_historico))
    app.add_handler(CommandHandler("insight", cmd_insight))
    app.add_handler(CommandHandler("zerar", cmd_zerar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot rodando com todas as features...")
    app.run_polling()
