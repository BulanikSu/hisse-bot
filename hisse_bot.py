"""
📈 Telegram Hisse Takip Botu
─────────────────────────────
Kurulum:
  pip install python-telegram-bot yfinance

Çalıştırma:
  python hisse_bot.py

Komutlar:
  /ekle THYAO 250.50 100 2024-01-15   → hisse ekle (sembol, alış fiyatı, adet, tarih)
  /portfoy                             → portföyü göster
  /sil THYAO                           → hisseyi sil
  /gecmis                              → tüm işlem geçmişi
  /yardim                              → komut listesi
"""

import sqlite3
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import yfinance as yf

# ── Ayarlar ────────────────────────────────────────────────────────────────
BOT_TOKEN = "BURAYA_BOT_TOKEN_YAZI"   # @BotFather'dan alınan token
DB_FILE   = "portfoy.db"
# ───────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ── Veritabanı ─────────────────────────────────────────────────────────────

def db_baglanti():
    return sqlite3.connect(DB_FILE)

def db_olustur():
    with db_baglanti() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS hisseler (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                kullanici   INTEGER NOT NULL,
                sembol      TEXT    NOT NULL,
                alis_fiyati REAL    NOT NULL,
                adet        REAL    NOT NULL,
                tarih       TEXT    NOT NULL,
                eklendi     TEXT    DEFAULT (datetime('now','localtime'))
            )
        """)
        con.commit()


# ── Fiyat çekme ────────────────────────────────────────────────────────────

def guncel_fiyat(sembol: str) -> float | None:
    """yfinance ile anlık/son kapanış fiyatını döndürür."""
    try:
        ticker = yf.Ticker(sembol)
        info   = ticker.fast_info
        fiyat  = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
        return float(fiyat) if fiyat else None
    except Exception as e:
        logger.warning(f"Fiyat alınamadı ({sembol}): {e}")
        return None


# ── Yardımcılar ────────────────────────────────────────────────────────────

def kar_emoji(yuzde: float) -> str:
    if yuzde >= 10:  return "🚀"
    if yuzde >= 5:   return "📈"
    if yuzde >= 0:   return "✅"
    if yuzde >= -5:  return "📉"
    return "🔴"

def tarih_dogrula(tarih_str: str) -> bool:
    try:
        datetime.strptime(tarih_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# ── /yardim ────────────────────────────────────────────────────────────────

async def yardim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    mesaj = (
        "📋 *Hisse Takip Botu - Komutlar*\n\n"
        "`/ekle SEMBOL ALIŞ_FİYATI ADET TARİH`\n"
        "  → Portföye hisse ekler\n"
        "  → Tarih: YYYY-MM-DD formatında\n"
        "  → Örn: `/ekle THYAO.IS 250.50 100 2024-01-15`\n\n"
        "`/portfoy`\n"
        "  → Tüm hisseleri güncel fiyat ve kâr/zarar ile gösterir\n\n"
        "`/sil SEMBOL`\n"
        "  → O semboldeki tüm pozisyonları siler\n\n"
        "`/gecmis`\n"
        "  → Tüm kayıtlı işlemleri listeler\n\n"
        "💡 *İpucu:* Borsa İstanbul hisseleri için `.IS` ekleyin\n"
        "  Örn: `THYAO.IS`, `GARAN.IS`, `ASELS.IS`\n"
        "  ABD hisseleri direkt: `AAPL`, `TSLA`, `NVDA`"
    )
    await update.message.reply_text(mesaj, parse_mode="Markdown")


# ── /ekle ──────────────────────────────────────────────────────────────────

async def ekle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if len(ctx.args) < 4:
        await update.message.reply_text(
            "❌ Eksik parametre!\n"
            "Kullanım: `/ekle SEMBOL ALIŞ_FİYATI ADET TARİH`\n"
            "Örn: `/ekle THYAO.IS 250.50 100 2024-01-15`",
            parse_mode="Markdown"
        )
        return

    sembol = ctx.args[0].upper()
    tarih  = ctx.args[3]

    try:
        alis  = float(ctx.args[1].replace(",", "."))
        adet  = float(ctx.args[2].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Fiyat ve adet sayı olmalı.")
        return

    if not tarih_dogrula(tarih):
        await update.message.reply_text("❌ Tarih formatı yanlış. Doğru format: `YYYY-MM-DD`", parse_mode="Markdown")
        return

    # Sembolün varlığını doğrula
    await update.message.reply_text(f"🔍 `{sembol}` doğrulanıyor...", parse_mode="Markdown")
    fiyat = guncel_fiyat(sembol)
    if fiyat is None:
        await update.message.reply_text(
            f"⚠️ `{sembol}` için fiyat alınamadı. Sembolü kontrol et.\n"
            f"BIST hisseleri için sonuna `.IS` ekle (örn: `THYAO.IS`)",
            parse_mode="Markdown"
        )
        return

    toplam_maliyet = alis * adet

    with db_baglanti() as con:
        con.execute(
            "INSERT INTO hisseler (kullanici, sembol, alis_fiyati, adet, tarih) VALUES (?,?,?,?,?)",
            (uid, sembol, alis, adet, tarih)
        )
        con.commit()

    kar_zarar = (fiyat - alis) * adet
    yuzde     = ((fiyat - alis) / alis) * 100
    emoji     = kar_emoji(yuzde)

    await update.message.reply_text(
        f"✅ *{sembol}* portföye eklendi!\n\n"
        f"📅 Alış tarihi: `{tarih}`\n"
        f"💰 Alış fiyatı: `{alis:,.2f}`\n"
        f"📦 Adet: `{adet:,.0f}`\n"
        f"💵 Toplam maliyet: `{toplam_maliyet:,.2f}`\n\n"
        f"📊 *Güncel durum:*\n"
        f"  Şu an: `{fiyat:,.2f}`\n"
        f"  Kâr/Zarar: `{kar_zarar:+,.2f}` ({yuzde:+.2f}%) {emoji}",
        parse_mode="Markdown"
    )


# ── /portfoy ───────────────────────────────────────────────────────────────

async def portfoy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    with db_baglanti() as con:
        satirlar = con.execute(
            "SELECT sembol, alis_fiyati, adet, tarih FROM hisseler WHERE kullanici=? ORDER BY sembol, tarih",
            (uid,)
        ).fetchall()

    if not satirlar:
        await update.message.reply_text(
            "📭 Portföyünde henüz hisse yok.\n"
            "Eklemek için: `/ekle THYAO.IS 250.50 100 2024-01-15`",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text("⏳ Güncel fiyatlar alınıyor...", parse_mode="Markdown")

    # Sembolleri grupla
    sembol_gruplari: dict[str, list] = {}
    for sembol, alis, adet, tarih in satirlar:
        sembol_gruplari.setdefault(sembol, []).append((alis, adet, tarih))

    toplam_maliyet   = 0.0
    toplam_deger     = 0.0
    satirlar_metin   = []

    for sembol, pozisyonlar in sembol_gruplari.items():
        fiyat = guncel_fiyat(sembol)
        if fiyat is None:
            satirlar_metin.append(f"⚠️ *{sembol}* — fiyat alınamadı")
            continue

        for alis, adet, tarih in pozisyonlar:
            maliyet   = alis * adet
            deger     = fiyat * adet
            kar       = deger - maliyet
            yuzde     = ((fiyat - alis) / alis) * 100
            emoji     = kar_emoji(yuzde)

            toplam_maliyet += maliyet
            toplam_deger   += deger

            satirlar_metin.append(
                f"{emoji} *{sembol}*\n"
                f"  📅 {tarih} | {adet:,.0f} adet\n"
                f"  Alış: `{alis:,.2f}` → Şimdi: `{fiyat:,.2f}`\n"
                f"  K/Z: `{kar:+,.2f}` ({yuzde:+.2f}%)"
            )

    toplam_kar    = toplam_deger - toplam_maliyet
    toplam_yuzde  = ((toplam_deger - toplam_maliyet) / toplam_maliyet * 100) if toplam_maliyet else 0
    ozet_emoji    = kar_emoji(toplam_yuzde)

    mesaj = (
        "📊 *Portföyüm*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(satirlar_metin)
        + "\n\n━━━━━━━━━━━━━━━━━━\n"
        f"💼 *Toplam Özet*\n"
        f"  Maliyet: `{toplam_maliyet:,.2f}`\n"
        f"  Güncel:  `{toplam_deger:,.2f}`\n"
        f"  Kâr/Zarar: `{toplam_kar:+,.2f}` ({toplam_yuzde:+.2f}%) {ozet_emoji}"
    )

    await update.message.reply_text(mesaj, parse_mode="Markdown")


# ── /sil ───────────────────────────────────────────────────────────────────

async def sil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not ctx.args:
        await update.message.reply_text("❌ Kullanım: `/sil SEMBOL`\nÖrn: `/sil THYAO.IS`", parse_mode="Markdown")
        return

    sembol = ctx.args[0].upper()

    with db_baglanti() as con:
        etkilenen = con.execute(
            "DELETE FROM hisseler WHERE kullanici=? AND sembol=?", (uid, sembol)
        ).rowcount
        con.commit()

    if etkilenen:
        await update.message.reply_text(f"🗑️ *{sembol}* portföyden silindi. ({etkilenen} kayıt)", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ Portföyde `{sembol}` bulunamadı.", parse_mode="Markdown")


# ── /gecmis ────────────────────────────────────────────────────────────────

async def gecmis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    with db_baglanti() as con:
        kayitlar = con.execute(
            "SELECT sembol, alis_fiyati, adet, tarih, eklendi FROM hisseler WHERE kullanici=? ORDER BY eklendi DESC",
            (uid,)
        ).fetchall()

    if not kayitlar:
        await update.message.reply_text("📭 Hiç işlem kaydı yok.")
        return

    satirlar = ["📜 *İşlem Geçmişi*\n━━━━━━━━━━━━━━━━━━\n"]
    for sembol, alis, adet, tarih, eklendi in kayitlar:
        toplam = alis * adet
        satirlar.append(
            f"• *{sembol}* | {adet:,.0f} adet @ `{alis:,.2f}`\n"
            f"  📅 Alış: {tarih} | Kaydedildi: {eklendi[:10]}\n"
            f"  💵 Maliyet: `{toplam:,.2f}`"
        )

    await update.message.reply_text("\n\n".join(satirlar), parse_mode="Markdown")


# ── Ana program ────────────────────────────────────────────────────────────

def main():
    if BOT_TOKEN == "BURAYA_BOT_TOKEN_YAZI":
        print("❌ Lütfen BOT_TOKEN değişkenini kendi token'ınızla değiştirin!")
        print("   @BotFather → /newbot → token'ı kopyalayın")
        return

    db_olustur()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   yardim))
    app.add_handler(CommandHandler("yardim",  yardim))
    app.add_handler(CommandHandler("ekle",    ekle))
    app.add_handler(CommandHandler("portfoy", portfoy))
    app.add_handler(CommandHandler("sil",     sil))
    app.add_handler(CommandHandler("gecmis",  gecmis))

    print("🤖 Bot başlatılıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
