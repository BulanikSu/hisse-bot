"""
📈 Telegram Hisse Takip Botu
─────────────────────────────
Hisse ekle:    THYAO 125
               THYAO 125 100        (adet belirtmek istersen)
Durum gör:     son durum
Sil:           /sil THYAO
Geçmiş:        /gecmis
"""

import sqlite3
import logging
from datetime import datetime, date
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yfinance as yf

BOT_TOKEN = "7376422219:AAGTK3QKYGFUs0kIR3ZuH5TFdcwRasbsCRo"
DB_FILE   = "portfoy.db"

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Veritabanı ─────────────────────────────────────────────────────────────

def db():
    return sqlite3.connect(DB_FILE)

def db_olustur():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS hisseler (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                kullanici   INTEGER NOT NULL,
                sembol      TEXT    NOT NULL,     -- dahili: THYAO.IS
                sembol_goster TEXT  NOT NULL,     -- kullanıcıya gösterilen: THYAO
                alis_fiyati REAL    NOT NULL,
                adet        REAL    NOT NULL DEFAULT 1,
                tarih       TEXT    NOT NULL,     -- YYYY-MM-DD
                eklendi     TEXT    DEFAULT (datetime('now','localtime'))
            )
        """)
        con.commit()


# ── Fiyat çekme ────────────────────────────────────────────────────────────

def fiyat_al(sembol: str):
    """(fiyat, tam_sembol) döndürür. Önce direkt, sonra .IS ekleyerek dener."""
    denemeler = [sembol, sembol + ".IS"] if not sembol.endswith(".IS") else [sembol]
    for s in denemeler:
        try:
            info  = yf.Ticker(s).fast_info
            fiyat = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
            if fiyat:
                return float(fiyat), s
        except Exception as e:
            logger.warning(f"{s}: {e}")
    return None, None


# ── Yardımcılar ────────────────────────────────────────────────────────────

def kar_emoji(yuzde: float) -> str:
    if yuzde >= 15: return "🚀"
    if yuzde >= 5:  return "📈"
    if yuzde >= 0:  return "✅"
    if yuzde >= -5: return "📉"
    return "🔴"

def gun_farki(tarih_str: str) -> int:
    t = datetime.strptime(tarih_str, "%Y-%m-%d").date()
    return (date.today() - t).days

def bugun() -> str:
    return date.today().strftime("%Y-%m-%d")


# ── /yardim ────────────────────────────────────────────────────────────────

async def yardim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Hisse Takip Botu*\n\n"
        "Hisse eklemek için yaz:\n"
        "`THYAO 125`\n"
        "`THYAO 125 100`  _(adetli)_\n\n"
        "Tarih otomatik kaydedilir ✅\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "`son durum` → kapsamlı kâr/zarar raporu\n"
        "`/sil THYAO` → hisseyi sil\n"
        "`/gecmis` → tüm alımlar\n"
        "`/yardim` → bu mesaj",
        parse_mode="Markdown"
    )


# ── Hisse ekleme (düz mesaj) ───────────────────────────────────────────────

async def mesaj_isle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    metin = update.message.text.strip()

    # "son durum" kontrolü
    if metin.lower() in ["son durum", "son durum?", "durum", "portfoy", "portföy"]:
        await son_durum_goster(update, uid)
        return

    parcalar = metin.split()

    # Format: SEMBOL FİYAT [ADET]
    if len(parcalar) < 2 or len(parcalar) > 3:
        await update.message.reply_text(
            "❓ Anlamadım.\n\n"
            "Hisse eklemek için:\n`THYAO 125`\n`THYAO 125 100`\n\n"
            "Durum için: `son durum`",
            parse_mode="Markdown"
        )
        return

    sembol_goster = parcalar[0].upper()

    try:
        alis = float(parcalar[1].replace(",", "."))
        adet = float(parcalar[2].replace(",", ".")) if len(parcalar) == 3 else 1.0
    except ValueError:
        await update.message.reply_text("❌ Fiyat sayı olmalı. Örn: `THYAO 125`", parse_mode="Markdown")
        return

    if alis <= 0 or adet <= 0:
        await update.message.reply_text("❌ Fiyat ve adet 0'dan büyük olmalı.")
        return

    await update.message.reply_text(f"🔍 `{sembol_goster}` aranıyor...", parse_mode="Markdown")

    fiyat, sembol_tam = fiyat_al(sembol_goster)

    if fiyat is None:
        await update.message.reply_text(
            f"⚠️ `{sembol_goster}` bulunamadı.\n"
            f"Sembolü kontrol et. (Örn: THYAO, GARAN, AAPL, BTC-USD)",
            parse_mode="Markdown"
        )
        return

    tarih = bugun()

    with db() as con:
        con.execute(
            "INSERT INTO hisseler (kullanici, sembol, sembol_goster, alis_fiyati, adet, tarih) VALUES (?,?,?,?,?,?)",
            (uid, sembol_tam, sembol_goster, alis, adet, tarih)
        )
        con.commit()

    kar_zarar = (fiyat - alis) * adet
    yuzde     = ((fiyat - alis) / alis) * 100
    emoji     = kar_emoji(yuzde)
    bist      = " _(BIST)_" if sembol_tam.endswith(".IS") else ""

    await update.message.reply_text(
        f"✅ *{sembol_goster}*{bist} kaydedildi!\n\n"
        f"📅 Tarih: `{tarih}`\n"
        f"💰 Alış: `{alis:,.2f}`\n"
        f"📦 Adet: `{adet:,.0f}`\n"
        f"💵 Toplam: `{alis * adet:,.2f}`\n\n"
        f"📊 Şu anki fiyat: `{fiyat:,.2f}`\n"
        f"K/Z: `{kar_zarar:+,.2f}` ({yuzde:+.2f}%) {emoji}\n\n"
        f"_Rapor için: son durum_",
        parse_mode="Markdown"
    )


# ── Son Durum Raporu ───────────────────────────────────────────────────────

async def son_durum_goster(update: Update, uid: int):
    with db() as con:
        kayitlar = con.execute(
            """SELECT sembol, sembol_goster, alis_fiyati, adet, tarih
               FROM hisseler WHERE kullanici=?
               ORDER BY sembol_goster, tarih""",
            (uid,)
        ).fetchall()

    if not kayitlar:
        await update.message.reply_text(
            "📭 Henüz hisse yok.\n\nEklemek için: `THYAO 125`",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text("⏳ Fiyatlar alınıyor...", parse_mode="Markdown")

    # Sembolleri grupla, tek seferde fiyat çek
    semboller = list({r[0] for r in kayitlar})
    fiyatlar  = {}
    for s in semboller:
        try:
            info  = yf.Ticker(s).fast_info
            f     = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
            fiyatlar[s] = float(f) if f else None
        except:
            fiyatlar[s] = None

    # Grupla: sembol → pozisyonlar
    gruplar: dict[str, list] = {}
    for sembol, goster, alis, adet, tarih in kayitlar:
        gruplar.setdefault(sembol, {"goster": goster, "pozisyonlar": []})
        gruplar[sembol]["pozisyonlar"].append((alis, adet, tarih))

    toplam_maliyet = 0.0
    toplam_deger   = 0.0
    en_iyi         = ("", -999)
    en_kotu        = ("", 999)
    satirlar       = []

    for sembol, bilgi in gruplar.items():
        goster     = bilgi["goster"]
        pozisyonlar = bilgi["pozisyonlar"]
        fiyat      = fiyatlar.get(sembol)

        if fiyat is None:
            satirlar.append(f"⚠️ *{goster}* — fiyat alınamadı")
            continue

        for alis, adet, tarih in pozisyonlar:
            gun       = gun_farki(tarih)
            maliyet   = alis * adet
            deger     = fiyat * adet
            kar       = deger - maliyet
            yuzde     = ((fiyat - alis) / alis) * 100
            emoji     = kar_emoji(yuzde)

            toplam_maliyet += maliyet
            toplam_deger   += deger

            if yuzde > en_iyi[1]:
                en_iyi = (goster, yuzde)
            if yuzde < en_kotu[1]:
                en_kotu = (goster, yuzde)

            gun_metin = f"{gun} gün önce" if gun > 0 else "bugün"

            satirlar.append(
                f"{emoji} *{goster}*\n"
                f"  🗓 Alış: `{alis:,.2f}` → Şimdi: `{fiyat:,.2f}` ({gun_metin})\n"
                f"  📦 {adet:,.0f} adet | Maliyet: `{maliyet:,.2f}`\n"
                f"  💰 Güncel değer: `{deger:,.2f}`\n"
                f"  {'📈' if kar >= 0 else '📉'} K/Z: `{kar:+,.2f}` ({yuzde:+.2f}%)"
            )

    toplam_kar   = toplam_deger - toplam_maliyet
    toplam_yuzde = (toplam_kar / toplam_maliyet * 100) if toplam_maliyet else 0
    ozet_emoji   = kar_emoji(toplam_yuzde)

    # Özet bölümü
    ozet = (
        "━━━━━━━━━━━━━━━━━━\n"
        f"💼 *PORTFÖY ÖZETİ*\n\n"
        f"  Toplam yatırım: `{toplam_maliyet:,.2f}`\n"
        f"  Güncel değer:   `{toplam_deger:,.2f}`\n"
        f"  Net K/Z:        `{toplam_kar:+,.2f}` ({toplam_yuzde:+.2f}%) {ozet_emoji}\n"
    )

    if en_iyi[0]:
        ozet += f"\n  🏆 En iyi: *{en_iyi[0]}* ({en_iyi[1]:+.2f}%)"
    if en_kotu[0] and en_kotu[0] != en_iyi[0]:
        ozet += f"\n  💔 En kötü: *{en_kotu[0]}* ({en_kotu[1]:+.2f}%)"

    mesaj = (
        f"📊 *SON DURUM*  —  {date.today().strftime('%d.%m.%Y')}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(satirlar)
        + "\n\n" + ozet
    )

    await update.message.reply_text(mesaj, parse_mode="Markdown")


# ── /sil ───────────────────────────────────────────────────────────────────

async def sil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not ctx.args:
        await update.message.reply_text("❌ Kullanım: `/sil THYAO`", parse_mode="Markdown")
        return

    s = ctx.args[0].upper().replace(".IS", "")

    with db() as con:
        n = con.execute(
            "DELETE FROM hisseler WHERE kullanici=? AND (sembol_goster=? OR sembol=? OR sembol=?)",
            (uid, s, s, s + ".IS")
        ).rowcount
        con.commit()

    if n:
        await update.message.reply_text(f"🗑️ *{s}* silindi. ({n} kayıt)", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ `{s}` portföyde bulunamadı.", parse_mode="Markdown")


# ── /gecmis ────────────────────────────────────────────────────────────────

async def gecmis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    with db() as con:
        kayitlar = con.execute(
            "SELECT sembol_goster, alis_fiyati, adet, tarih FROM hisseler WHERE kullanici=? ORDER BY eklendi DESC",
            (uid,)
        ).fetchall()

    if not kayitlar:
        await update.message.reply_text("📭 Hiç kayıt yok.")
        return

    satirlar = [f"📜 *Tüm Alımlar*  ({len(kayitlar)} kayıt)\n━━━━━━━━━━━━━━━━━━"]
    for goster, alis, adet, tarih in kayitlar:
        gun = gun_farki(tarih)
        satirlar.append(
            f"• *{goster}* — `{alis:,.2f}` × {adet:,.0f} adet\n"
            f"  📅 {tarih}  _{gun} gün önce_"
        )

    await update.message.reply_text("\n\n".join(satirlar), parse_mode="Markdown")


# ── Ana program ────────────────────────────────────────────────────────────

def main():
    db_olustur()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   yardim))
    app.add_handler(CommandHandler("yardim",  yardim))
    app.add_handler(CommandHandler("sil",     sil))
    app.add_handler(CommandHandler("gecmis",  gecmis))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mesaj_isle))

    print("🤖 Bot başlatılıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
