"""
Bot conversacional - Monitor de Preços
Usuários cadastram produtos pelo Telegram.
Admin tem painel de controle.
"""

import os, html, logging, asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters,
)
import database as db
import buscar_precos as bp

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID  = int(os.environ.get("ADMIN_CHAT_ID", "0"))

# Estados da conversa
AGUARDA_PRODUTO, AGUARDA_PRECO_ALVO, AGUARDA_PRECO_MERCADO, AGUARDA_HORARIO = range(4)

HORARIOS_DISPONIVEIS = [
    ["06:00", "07:00", "08:00", "09:00"],
    ["10:00", "11:00", "12:00", "13:00"],
    ["14:00", "15:00", "16:00", "17:00"],
    ["18:00", "19:00", "20:00", "21:00"],
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def registrar_usuario(update: Update):
    user = update.effective_user
    db.salvar_usuario(
        chat_id=user.id,
        username=user.username or "",
        nome=user.full_name or "",
    )


def montar_mensagem_preco(produto: dict, item: dict) -> str:
    preco   = item["preco"]
    alvo    = produto.get("preco_alvo")
    mercado = produto.get("preco_mercado")

    nome      = html.escape(produto["nome"])
    titulo    = html.escape(item["titulo"] or "")
    loja      = html.escape(item["loja"] or "")
    preco_txt = html.escape(item["preco_txt"] or "")
    link      = f'<a href="{html.escape(item["link"] or "")}">🛒 Compre aqui</a>'

    if alvo and preco <= alvo:
        cabecalho  = f"🚨 <b>ALERTA DE PREÇO — {nome}</b>"
        linha_alvo = f"🎯 ABAIXO DO SEU ALVO de {bp.fmt_brl(alvo)}!"
    elif alvo:
        cabecalho  = f"🔎 <b>{nome}</b>"
        linha_alvo = f"🎯 Faltam {bp.fmt_brl(preco - alvo)} para seu alvo ({bp.fmt_brl(alvo)})"
    else:
        cabecalho  = f"🔎 <b>{nome}</b>"
        linha_alvo = None

    linhas = [cabecalho, "", f"📦 {titulo}", f"🏪 Loja: {loja}", f"💰 Preço: {preco_txt}"]

    if mercado:
        economia = mercado - preco
        if economia > 0:
            linhas.append(f"📊 {bp.fmt_brl(economia)} abaixo do preço de mercado ({bp.fmt_brl(mercado)})")
        else:
            linhas.append(f"📊 Preço de mercado: {bp.fmt_brl(mercado)}")

    if linha_alvo:
        linhas.append(linha_alvo)

    if item.get("cupom"):
        linhas.append(f"🏷️ Cupom: <b>{html.escape(item['cupom'])}</b>")

    linhas += ["", link]
    return "\n".join(linhas)


# ── Comandos gerais ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    registrar_usuario(update)
    nome = update.effective_user.first_name
    await update.message.reply_text(
        f"Olá, {nome}! 👋\n\n"
        "Sou o <b>Monitor de Preços</b> — te aviso automaticamente quando o produto "
        "que você quer cair de preço! 🔎\n\n"
        "Use os comandos abaixo:\n"
        "• /monitorar — cadastrar um produto\n"
        "• /meu_produto — ver o produto cadastrado\n"
        "• /remover — remover o produto\n"
        "• /ajuda — ver todos os comandos",
        parse_mode="HTML",
    )

async def cmd_ajuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 <b>Comandos disponíveis:</b>\n\n"
        "• /monitorar — cadastrar um produto para monitorar\n"
        "• /meu_produto — ver o produto que está monitorando\n"
        "• /buscar_agora — buscar o preço agora mesmo\n"
        "• /remover — parar de monitorar o produto\n"
        "• /ajuda — ver esta mensagem",
        parse_mode="HTML",
    )

async def cmd_meu_produto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    registrar_usuario(update)
    produto = db.buscar_produto_usuario(update.effective_user.id)
    if not produto:
        await update.message.reply_text(
            "Você não tem nenhum produto cadastrado.\n"
            "Use /monitorar para cadastrar um!"
        )
        return
    await update.message.reply_text(
        f"📦 <b>Produto monitorado:</b>\n\n"
        f"🔎 {html.escape(produto['nome'])}\n"
        f"🎯 Preço alvo: {bp.fmt_brl(produto['preco_alvo'])}\n"
        f"📊 Preço de mercado: {bp.fmt_brl(produto['preco_mercado'])}\n"
        f"⏰ Notificação diária às: {produto['horario']}",
        parse_mode="HTML",
    )

async def cmd_remover(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    registrar_usuario(update)
    produto = db.buscar_produto_usuario(update.effective_user.id)
    if not produto:
        await update.message.reply_text("Você não tem nenhum produto cadastrado.")
        return
    db.remover_produto(update.effective_user.id)
    await update.message.reply_text(
        f"✅ Produto <b>{html.escape(produto['nome'])}</b> removido com sucesso!\n"
        "Use /monitorar para cadastrar um novo.",
        parse_mode="HTML",
    )

async def cmd_buscar_agora(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    registrar_usuario(update)
    produto = db.buscar_produto_usuario(update.effective_user.id)
    if not produto:
        await update.message.reply_text(
            "Você não tem nenhum produto cadastrado.\nUse /monitorar para cadastrar!"
        )
        return
    msg = await update.message.reply_text("🔍 Buscando o melhor preço agora...")
    try:
        item = bp.buscar_mais_barato(
            produto["busca"], produto.get("modelo", ""), produto.get("preco_alvo", 0)
        )
        if not item:
            await msg.edit_text("😕 Não encontrei resultado para este produto agora. Tente mais tarde.")
            return
        mensagem = montar_mensagem_preco(produto, item)
        if item.get("foto"):
            await ctx.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=item["foto"], caption=mensagem, parse_mode="HTML"
            )
            await msg.delete()
        else:
            await msg.edit_text(mensagem, parse_mode="HTML")
    except Exception as e:
        await msg.edit_text(f"❌ Erro ao buscar: {str(e)}")


# ── Fluxo de cadastro ─────────────────────────────────────────────────────────

async def cmd_monitorar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    registrar_usuario(update)
    produto_existente = db.buscar_produto_usuario(update.effective_user.id)
    if produto_existente:
        await update.message.reply_text(
            f"⚠️ Você já está monitorando: <b>{html.escape(produto_existente['nome'])}</b>\n\n"
            "No momento o limite é de 1 produto por pessoa.\n"
            "Use /remover para trocar de produto.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🔎 <b>Vamos cadastrar seu produto!</b>\n\n"
        "Qual produto você quer monitorar?\n"
        "<i>Ex: Aspirador Robô Xiaomi S40C</i>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return AGUARDA_PRODUTO


async def receber_produto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["nome_produto"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Produto: <b>{html.escape(ctx.user_data['nome_produto'])}</b>\n\n"
        "💰 Qual o <b>preço alvo</b>? (valor em que quer ser avisado)\n"
        "<i>Ex: 1000</i>",
        parse_mode="HTML",
    )
    return AGUARDA_PRECO_ALVO


async def receber_preco_alvo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip().replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        preco_alvo = float(texto)
        if preco_alvo <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Valor inválido. Digite só o número. Ex: 1000")
        return AGUARDA_PRECO_ALVO

    ctx.user_data["preco_alvo"] = preco_alvo
    await update.message.reply_text(
        f"✅ Preço alvo: <b>{bp.fmt_brl(preco_alvo)}</b>\n\n"
        "📊 Qual o <b>preço de mercado atual</b> desse produto?\n"
        "<i>Ex: 1500 (preço que você viu nas lojas)</i>",
        parse_mode="HTML",
    )
    return AGUARDA_PRECO_MERCADO


async def receber_preco_mercado(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip().replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        preco_mercado = float(texto)
        if preco_mercado <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Valor inválido. Digite só o número. Ex: 1500")
        return AGUARDA_PRECO_MERCADO

    ctx.user_data["preco_mercado"] = preco_mercado
    await update.message.reply_text(
        f"✅ Preço de mercado: <b>{bp.fmt_brl(preco_mercado)}</b>\n\n"
        "⏰ Em qual horário quer receber a notificação diária?",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(
            HORARIOS_DISPONIVEIS, one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return AGUARDA_HORARIO


async def receber_horario(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    horario = update.message.text.strip()
    horarios_validos = [h for linha in HORARIOS_DISPONIVEIS for h in linha]
    if horario not in horarios_validos:
        await update.message.reply_text("⚠️ Escolha um horário da lista.")
        return AGUARDA_HORARIO

    nome_produto = ctx.user_data["nome_produto"]
    preco_alvo   = ctx.user_data["preco_alvo"]
    preco_mercado = ctx.user_data["preco_mercado"]

    # Usa o nome como busca e tenta extrair modelo (última palavra em maiúscula)
    palavras = nome_produto.split()
    modelo = ""
    for p in reversed(palavras):
        if any(c.isdigit() for c in p) or p.isupper():
            modelo = p
            break

    db.salvar_produto(
        chat_id=update.effective_user.id,
        nome=nome_produto,
        busca=nome_produto,
        modelo=modelo,
        preco_alvo=preco_alvo,
        preco_mercado=preco_mercado,
        horario=horario,
    )

    await update.message.reply_text(
        f"🎉 <b>Cadastro concluído!</b>\n\n"
        f"📦 Produto: {html.escape(nome_produto)}\n"
        f"🎯 Preço alvo: {bp.fmt_brl(preco_alvo)}\n"
        f"📊 Preço de mercado: {bp.fmt_brl(preco_mercado)}\n"
        f"⏰ Notificação diária às: {horario}\n\n"
        "Todo dia nesse horário vou buscar o melhor preço e te avisar! 🔔\n"
        "Use /buscar_agora para buscar agora mesmo.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Notifica o admin
    if ADMIN_CHAT_ID:
        user = update.effective_user
        total = db.total_usuarios()
        await ctx.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"👤 Novo produto cadastrado!\n"
                 f"Usuário: {user.full_name} (@{user.username})\n"
                 f"Produto: {nome_produto}\n"
                 f"Alvo: {bp.fmt_brl(preco_alvo)}\n"
                 f"Total de usuários ativos: {total}",
        )

    return ConversationHandler.END


async def cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Cadastro cancelado.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# ── Painel Admin ──────────────────────────────────────────────────────────────

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Acesso restrito.")
        return

    usuarios = db.listar_usuarios()
    total = len(usuarios)

    linhas = [f"📊 <b>Painel Admin — {total} usuário(s)</b>\n"]
    for u in usuarios[:20]:  # mostra até 20
        nome = html.escape(u["nome"] or "—")
        username = f"@{u['username']}" if u["username"] else "sem username"
        produtos = u["total_produtos"]
        linhas.append(f"👤 {nome} ({username}) — {produtos} produto(s)")

    if total > 20:
        linhas.append(f"\n... e mais {total - 20} usuário(s).")

    await update.message.reply_text("\n".join(linhas), parse_mode="HTML")


# ── Agendador de buscas ───────────────────────────────────────────────────────

async def rodar_buscas_agendadas(app: Application):
    """Roda a cada minuto e verifica se há produtos para buscar nesse horário."""
    while True:
        agora = datetime.now().strftime("%H:%M")
        produtos = db.produtos_por_horario(agora)

        for produto in produtos:
            try:
                item = bp.buscar_mais_barato(
                    produto["busca"],
                    produto.get("modelo", ""),
                    produto.get("preco_alvo", 0),
                )
                if not item:
                    continue
                mensagem = montar_mensagem_preco(produto, item)
                foto = item.get("foto")
                if foto:
                    await app.bot.send_photo(
                        chat_id=produto["chat_id"],
                        photo=foto, caption=mensagem, parse_mode="HTML"
                    )
                else:
                    await app.bot.send_message(
                        chat_id=produto["chat_id"],
                        text=mensagem, parse_mode="HTML"
                    )
            except Exception as e:
                logging.error(f"Erro ao buscar produto {produto['nome']}: {e}")

        await asyncio.sleep(60)  # verifica a cada 1 minuto


# ── Main ──────────────────────────────────────────────────────────────────────

import os
import asyncio
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

# Captura e valida o token das variáveis de ambiente
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

def main():
    # Trava de segurança para identificar falha de leitura da variável
    if not TELEGRAM_TOKEN:
        raise ValueError(
            "ERRO: A variável TELEGRAM_TOKEN não foi encontrada ou está vazia no painel de deploy!"
        )

    db.inicializar()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Fluxo de cadastro
    conv = ConversationHandler(
        entry_points=[CommandHandler("monitorar", cmd_monitorar)],
        states={
            AGUARDA_PRODUTO:       [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_produto)],
            AGUARDA_PRECO_ALVO:     [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_preco_alvo)],
            AGUARDA_PRECO_MERCADO:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_preco_mercado)],
            AGUARDA_HORARIO:        [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_horario)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("ajuda",        cmd_ajuda))
    app.add_handler(CommandHandler("meu_produto",  cmd_meu_produto))
    app.add_handler(CommandHandler("remover",      cmd_remover))
    app.add_handler(CommandHandler("buscar_agora", cmd_buscar_agora))
    app.add_handler(CommandHandler("admin",        cmd_admin))

    # Inicia o agendador em paralelo
    loop = asyncio.get_event_loop()
    loop.create_task(rodar_buscas_agendadas(app))

    app.run_polling()


if __name__ == "__main__":
    main()
