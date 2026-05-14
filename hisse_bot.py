"""
📈 Profesyonel Hisse Takip Botu
────────────────────────────────
Hisse aç:   THYAO 125
Ana menü:   /menu  veya  menu
"""

import sqlite3
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
import yfinance as yf

BOT_TOKEN = "7376422219:AAGTK3QKYGFUs0kIR3ZuH5TFdcwRasbsCRo"
DB_FILE   = "portfoy.db"

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


# ════════════════════════════════════════════
#  VERİTABANI
# ════════════════════════════════════════════

def db():
    return sqlite3.connect(DB_FILE)

def db_olustur():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS pozisyonlar (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                kullanici       INTEGER NOT NULL,
                sembol          TEXT    NOT NULL,   -- dahili: THYAO.IS
                sembol_goster   TEXT    NOT NULL,   -- kullanıcıya: THYAO
                alis_fiyati     REAL    NOT NULL,
                adet            REAL    NOT NULL DEFAULT 1,
                alis_tarihi     TEXT    NOT NULL,
                durum           TEXT    NOT NULL DEFAULT 'acik',  -- acik / kapali
                satis_fiyati    REAL,
                satis_tarihi    TEXT,
                eklendi         TEXT    DEFAULT (datetime('now','localtime'))
            )
        """)
        con.commit()


# ════════════════════════════════════════════
#  YARDIMCILAR
# ════════════════════════════════════════════

def fiyat_al(sembol: str):
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

def kar_emoji(yuzde: float) -> str:
    if yuzde >= 15: return "🚀"
    if yuzde >= 5:  return "📈"
    if yuzde >= 0:  return "✅"
    if yuzde >= -5: return "📉"
    return "🔴"

def gun_farki(tarih_str: str) -> int:
    return (date.today() - datetime.strptime(tarih_str, "%Y-%m-%d").date()).days

def bugun() -> str:
    return date.today().strftime("%Y-%m-%d")

def fmt_tarih(t: str) -> str:
    return datetime.strptime(t, "%Y-%m-%d").strftime("%d.%m.%Y")


# ════════════════════════════════════════════
#  ANA MENÜ
# ════════════════════════════════════════════

def ana_menu_klavye():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Son Durum",      callback_data="son_durum"),
            InlineKeyboardButton("📂 Açık Pozlar",    callback_data="acik_pozlar"),
        ],
        [
            InlineKeyboardButton("📁 Kapalı Pozlar",  callback_data="kapali_pozlar"),
            InlineKeyboardButton("📜 Geçmiş",         callback_data="gecmis"),
        ],
        [
            InlineKeyboardButton("❓ Yardım",          callback_data="yardim"),
        ],
    ])

async def menu_goster(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    metin = (
        "📈 *Hisse Takip Botu*\n\n"
        "Hisse açmak için direkt yaz:\n"
        "`THYAO 125`  veya  `THYAO 125 100`\n\n"
        "Ne yapmak istersin?"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=ana_menu_klavye())
    else:
        await update.message.reply_text(metin, parse_mode="Markdown", reply_markup=ana_menu_klavye())


# ════════════════════════════════════════════
#  HİSSE EKLE (düz mesaj)
# ════════════════════════════════════════════

async def mesaj_isle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    metin = update.message.text.strip()

    # Menü tetikleyiciler
    if metin.lower() in ["menu", "menü", "ana menü", "ana menu"]:
        await menu_goster(update, ctx)
        return
    if metin.lower() in ["son durum", "durum", "portfoy", "portföy"]:
        await _son_durum(update, uid)
        return

    parcalar = metin.split()
    if len(parcalar) < 2 or len(parcalar) > 3:
        await update.message.reply_text(
            "❓ Anlamadım.\n\n"
            "Hisse açmak için: `THYAO 125`\n"
            "Menü için: `menu`",
            parse_mode="Markdown"
        )
        return

    sembol_goster = parcalar[0].upper()

    # Sadece harf/rakam/tire içermeli
    if not all(c.isalpha() or c.isdigit() or c == "-" for c in sembol_goster):
        await update.message.reply_text("❌ Geçersiz sembol.", parse_mode="Markdown")
        return

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
            f"⚠️ `{sembol_goster}` bulunamadı. Sembolü kontrol et.",
            parse_mode="Markdown"
        )
        return

    with db() as con:
        cur = con.execute(
            "INSERT INTO pozisyonlar (kullanici, sembol, sembol_goster, alis_fiyati, adet, alis_tarihi) VALUES (?,?,?,?,?,?)",
            (uid, sembol_tam, sembol_goster, alis, adet, bugun())
        )
        poz_id = cur.lastrowid
        con.commit()

    yuzde = ((fiyat - alis) / alis) * 100
    emoji = kar_emoji(yuzde)

    klavye = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Son Durum", callback_data="son_durum"),
            InlineKeyboardButton("📂 Açık Pozlar", callback_data="acik_pozlar"),
        ],
        [InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]
    ])

    await update.message.reply_text(
        f"✅ *{sembol_goster}* pozisyon açıldı!\n\n"
        f"📅 `{fmt_tarih(bugun())}`\n"
        f"💰 Alış: `{alis:,.2f}`  |  📦 Adet: `{adet:,.0f}`\n\n"
        f"📊 Şu an: `{fiyat:,.2f}`  →  {emoji} `{yuzde:+.2f}%`",
        parse_mode="Markdown",
        reply_markup=klavye
    )


# ════════════════════════════════════════════
#  SON DURUM
# ════════════════════════════════════════════

async def _son_durum(update, uid):
    with db() as con:
        kayitlar = con.execute(
            "SELECT sembol, sembol_goster, alis_fiyati, adet, alis_tarihi FROM pozisyonlar WHERE kullanici=? AND durum='acik' ORDER BY sembol_goster",
            (uid,)
        ).fetchall()

    if not kayitlar:
        metin = "📭 Açık pozisyon yok.\n\nHisse açmak için: `THYAO 125`"
        klavye = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]])
        if update.callback_query:
            await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=klavye)
        else:
            await update.message.reply_text(metin, parse_mode="Markdown", reply_markup=klavye)
        return

    # Fiyat çek
    semboller = list({r[0] for r in kayitlar})
    fiyatlar  = {}
    for s in semboller:
        try:
            info = yf.Ticker(s).fast_info
            f    = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
            fiyatlar[s] = float(f) if f else None
        except:
            fiyatlar[s] = None

    # Grupla
    gruplar: dict = {}
    for sembol, goster, alis, adet, tarih in kayitlar:
        gruplar.setdefault(sembol, {"goster": goster, "pozlar": []})
        gruplar[sembol]["pozlar"].append((alis, adet, tarih))

    toplam_maliyet = toplam_deger = 0.0
    veriler = []

    for sembol, bilgi in gruplar.items():
        fiyat = fiyatlar.get(sembol)
        if fiyat is None:
            veriler.append((None, f"⚠️ *{bilgi['goster']}* — fiyat alınamadı"))
            continue
        for alis, adet, tarih in bilgi["pozlar"]:
            yuzde = ((fiyat - alis) / alis) * 100
            gun   = gun_farki(tarih)
            toplam_maliyet += alis * adet
            toplam_deger   += fiyat * adet
            gun_metin = "bugün" if gun == 0 else f"{gun}g"
            satir = (
                f"{kar_emoji(yuzde)} *{bilgi['goster']}*  `{yuzde:+.2f}%`\n"
                f"   `{alis:,.2f}` → `{fiyat:,.2f}`  •  _{gun_metin}_"
            )
            veriler.append((yuzde, satir))

    veriler.sort(key=lambda x: x[0] if x[0] is not None else -9999, reverse=True)

    toplam_kar   = toplam_deger - toplam_maliyet
    toplam_yuzde = (toplam_kar / toplam_maliyet * 100) if toplam_maliyet else 0

    satirlar = [f"{i}. {s}" for i, (_, s) in enumerate(veriler, 1)]

    metin = (
        f"📊 *SON DURUM*  —  {date.today().strftime('%d.%m.%Y')}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(satirlar)
        + f"\n\n━━━━━━━━━━━━━━━━━━\n"
        f"💼 *Portföy:*  `{toplam_yuzde:+.2f}%`  {kar_emoji(toplam_yuzde)}\n"
        f"   K/Z: `{toplam_kar:+,.2f}`"
    )

    klavye = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📂 Açık Pozlar", callback_data="acik_pozlar"),
            InlineKeyboardButton("📁 Kapalı Pozlar", callback_data="kapali_pozlar"),
        ],
        [InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=klavye)
    else:
        await update.message.reply_text(metin, parse_mode="Markdown", reply_markup=klavye)


# ════════════════════════════════════════════
#  AÇIK POZİSYONLAR
# ════════════════════════════════════════════

async def _acik_pozlar(update, uid):
    with db() as con:
        kayitlar = con.execute(
            "SELECT id, sembol_goster, alis_fiyati, adet, alis_tarihi FROM pozisyonlar WHERE kullanici=? AND durum='acik' ORDER BY alis_tarihi DESC",
            (uid,)
        ).fetchall()

    if not kayitlar:
        metin = "📭 Açık pozisyon yok."
        klavye = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]])
        await update.callback_query.edit_message_text(metin, reply_markup=klavye)
        return

    metin = f"📂 *Açık Pozisyonlar*  ({len(kayitlar)} adet)\n━━━━━━━━━━━━━━━━━━\n\n"
    butonlar = []

    for poz_id, goster, alis, adet, tarih in kayitlar:
        gun = gun_farki(tarih)
        gun_metin = "bugün" if gun == 0 else f"{gun} gün önce"
        metin += (
            f"📌 *{goster}*  —  `{alis:,.2f}` × {adet:,.0f} adet\n"
            f"   📅 {fmt_tarih(tarih)}  _{gun_metin}_\n\n"
        )
        butonlar.append([
            InlineKeyboardButton(f"❌ {goster} Kapat", callback_data=f"kapat_{poz_id}")
        ])

    butonlar.append([InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")])
    klavye = InlineKeyboardMarkup(butonlar)

    await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=klavye)


# ════════════════════════════════════════════
#  POZİSYON KAPAT
# ════════════════════════════════════════════

# Bekleyen kapanış: {user_id: poz_id}
bekleyen_kapanis: dict[int, int] = {}

async def _kapat_sor(update, uid, poz_id):
    """Kullanıcıya satış fiyatı sor."""
    with db() as con:
        row = con.execute(
            "SELECT sembol_goster, alis_fiyati, adet, alis_tarihi FROM pozisyonlar WHERE id=? AND kullanici=?",
            (poz_id, uid)
        ).fetchone()

    if not row:
        await update.callback_query.answer("Pozisyon bulunamadı.")
        return

    goster, alis, adet, tarih = row
    bekleyen_kapanis[uid] = poz_id

    klavye = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ İptal", callback_data="acik_pozlar")]
    ])

    await update.callback_query.edit_message_text(
        f"❌ *{goster}* pozisyonu kapatılıyor\n\n"
        f"📅 Alış: {fmt_tarih(tarih)}  |  `{alis:,.2f}` × {adet:,.0f}\n\n"
        f"💬 *Satış fiyatını yaz:*\n_(Örn: `185.50`)_",
        parse_mode="Markdown",
        reply_markup=klavye
    )


async def _kapat_isle(update: Update, ctx: ContextTypes.DEFAULT_TYPE, uid: int, poz_id: int):
    """Kullanıcının yazdığı fiyatla pozisyonu kapat."""
    metin = update.message.text.strip()

    try:
        satis = float(metin.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Geçersiz fiyat. Tekrar yaz veya /menu ile iptal et.")
        return

    if satis <= 0:
        await update.message.reply_text("❌ Fiyat 0'dan büyük olmalı.")
        return

    with db() as con:
        row = con.execute(
            "SELECT sembol_goster, alis_fiyati, adet, alis_tarihi FROM pozisyonlar WHERE id=? AND kullanici=? AND durum='acik'",
            (poz_id, uid)
        ).fetchone()

        if not row:
            del bekleyen_kapanis[uid]
            await update.message.reply_text("⚠️ Pozisyon bulunamadı veya zaten kapalı.")
            return

        goster, alis, adet, tarih = row

        con.execute(
            "UPDATE pozisyonlar SET durum='kapali', satis_fiyati=?, satis_tarihi=? WHERE id=?",
            (satis, bugun(), poz_id)
        )
        con.commit()

    del bekleyen_kapanis[uid]

    kar       = (satis - alis) * adet
    yuzde     = ((satis - alis) / alis) * 100
    emoji     = kar_emoji(yuzde)
    gun       = gun_farki(tarih)
    gun_metin = f"{gun} gün" if gun > 0 else "aynı gün"

    klavye = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📂 Açık Pozlar",  callback_data="acik_pozlar"),
            InlineKeyboardButton("📁 Kapalı Pozlar", callback_data="kapali_pozlar"),
        ],
        [InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]
    ])

    await update.message.reply_text(
        f"{emoji} *{goster}* pozisyonu kapatıldı!\n\n"
        f"📅 {fmt_tarih(tarih)} → {fmt_tarih(bugun())}  _{gun_metin}_\n"
        f"💰 Alış: `{alis:,.2f}`  →  Satış: `{satis:,.2f}`\n"
        f"📦 {adet:,.0f} adet\n\n"
        f"{'🟢' if kar >= 0 else '🔴'} *Gerçekleşen K/Z:*  `{kar:+,.2f}` ({yuzde:+.2f}%)",
        parse_mode="Markdown",
        reply_markup=klavye
    )


# ════════════════════════════════════════════
#  KAPALI POZİSYONLAR
# ════════════════════════════════════════════

async def _kapali_pozlar(update, uid):
    with db() as con:
        kayitlar = con.execute(
            """SELECT sembol_goster, alis_fiyati, satis_fiyati, adet, alis_tarihi, satis_tarihi
               FROM pozisyonlar WHERE kullanici=? AND durum='kapali'
               ORDER BY satis_tarihi DESC""",
            (uid,)
        ).fetchall()

    if not kayitlar:
        metin = "📁 Henüz kapalı pozisyon yok."
        klavye = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]])
        await update.callback_query.edit_message_text(metin, reply_markup=klavye)
        return

    toplam_kar = 0.0
    satirlar   = []

    for goster, alis, satis, adet, a_tar, s_tar in kayitlar:
        kar   = (satis - alis) * adet
        yuzde = ((satis - alis) / alis) * 100
        gun   = (datetime.strptime(s_tar, "%Y-%m-%d") - datetime.strptime(a_tar, "%Y-%m-%d")).days
        toplam_kar += kar

        satirlar.append(
            f"{kar_emoji(yuzde)} *{goster}*  `{yuzde:+.2f}%`\n"
            f"   `{alis:,.2f}` → `{satis:,.2f}`  |  {adet:,.0f} adet\n"
            f"   K/Z: `{kar:+,.2f}`  •  _{fmt_tarih(a_tar)} – {fmt_tarih(s_tar)} ({gun}g)_"
        )

    ozet_emoji = "🟢" if toplam_kar >= 0 else "🔴"
    metin = (
        f"📁 *Kapalı Pozisyonlar*  ({len(kayitlar)} işlem)\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(satirlar)
        + f"\n\n━━━━━━━━━━━━━━━━━━\n"
        f"{ozet_emoji} *Toplam Gerçekleşen K/Z:* `{toplam_kar:+,.2f}`"
    )

    klavye = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📂 Açık Pozlar", callback_data="acik_pozlar"),
            InlineKeyboardButton("📊 Son Durum",   callback_data="son_durum"),
        ],
        [InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]
    ])

    await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=klavye)


# ════════════════════════════════════════════
#  GEÇMİŞ
# ════════════════════════════════════════════

async def _gecmis(update, uid):
    with db() as con:
        kayitlar = con.execute(
            "SELECT sembol_goster, alis_fiyati, adet, alis_tarihi, durum, satis_fiyati, satis_tarihi FROM pozisyonlar WHERE kullanici=? ORDER BY eklendi DESC LIMIT 30",
            (uid,)
        ).fetchall()

    if not kayitlar:
        metin = "📜 Hiç işlem yok."
        klavye = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]])
        await update.callback_query.edit_message_text(metin, reply_markup=klavye)
        return

    satirlar = [f"📜 *İşlem Geçmişi*  (son {len(kayitlar)})\n━━━━━━━━━━━━━━━━━━"]
    for goster, alis, adet, a_tar, durum, satis, s_tar in kayitlar:
        if durum == "acik":
            satirlar.append(
                f"🟡 *{goster}*  `{alis:,.2f}` × {adet:,.0f}\n"
                f"   📅 {fmt_tarih(a_tar)}  —  _açık_"
            )
        else:
            kar   = (satis - alis) * adet
            yuzde = ((satis - alis) / alis) * 100
            satirlar.append(
                f"{'🟢' if kar >= 0 else '🔴'} *{goster}*  `{alis:,.2f}` → `{satis:,.2f}`\n"
                f"   📅 {fmt_tarih(a_tar)} – {fmt_tarih(s_tar)}  |  K/Z: `{kar:+,.2f}` ({yuzde:+.2f}%)"
            )

    metin  = "\n\n".join(satirlar)
    klavye = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📂 Açık Pozlar",  callback_data="acik_pozlar"),
            InlineKeyboardButton("📁 Kapalı Pozlar", callback_data="kapali_pozlar"),
        ],
        [InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]
    ])

    await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=klavye)


# ════════════════════════════════════════════
#  YARDIM
# ════════════════════════════════════════════

async def _yardim(update, uid):
    metin = (
        "❓ *Nasıl Kullanılır?*\n\n"
        "*Pozisyon Aç:*\n"
        "`THYAO 125`\n"
        "`THYAO 125 100`  _(adetli)_\n\n"
        "*Pozisyon Kapat:*\n"
        "📂 Açık Pozlar → ❌ Kapat butonuna bas\n"
        "Satış fiyatını yaz → bitti!\n\n"
        "*Raporlar:*\n"
        "📊 Son Durum → açık pozlar, anlık K/Z\n"
        "📁 Kapalı Pozlar → gerçekleşen K/Z\n"
        "📜 Geçmiş → tüm işlemler\n\n"
        "💡 _Menü için: `menu`_"
    )
    klavye = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]])
    await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=klavye)


# ════════════════════════════════════════════
#  CALLBACK YÖNETİCİ
# ════════════════════════════════════════════

async def callback_isle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    data = query.data

    if data == "ana_menu":
        await menu_goster(update, ctx)
    elif data == "son_durum":
        await _son_durum(update, uid)
    elif data == "acik_pozlar":
        await _acik_pozlar(update, uid)
    elif data == "kapali_pozlar":
        await _kapali_pozlar(update, uid)
    elif data == "gecmis":
        await _gecmis(update, uid)
    elif data == "yardim":
        await _yardim(update, uid)
    elif data.startswith("kapat_"):
        poz_id = int(data.split("_")[1])
        await _kapat_sor(update, uid, poz_id)


# ════════════════════════════════════════════
#  MESAJ YÖNETİCİ (kapanış fiyatı bekleniyor mu?)
# ════════════════════════════════════════════

async def mesaj_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in bekleyen_kapanis:
        await _kapat_isle(update, ctx, uid, bekleyen_kapanis[uid])
    else:
        await mesaj_isle(update, ctx)


# ════════════════════════════════════════════
#  ANA PROGRAM
# ════════════════════════════════════════════

def main():
    db_olustur()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  menu_goster))
    app.add_handler(CommandHandler("menu",   menu_goster))
    app.add_handler(CommandHandler("sil",    _sil_command))
    app.add_handler(CallbackQueryHandler(callback_isle))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mesaj_router))

    print("🤖 Bot başlatılıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


# ── /sil komutu ────────────────────────────────────────────────────────────

async def _sil_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("❌ Kullanım: `/sil THYAO`", parse_mode="Markdown")
        return
    s = ctx.args[0].upper().replace(".IS", "")
    with db() as con:
        n = con.execute(
            "DELETE FROM pozisyonlar WHERE kullanici=? AND (sembol_goster=? OR sembol=? OR sembol=?)",
            (uid, s, s, s + ".IS")
        ).rowcount
        con.commit()
    if n:
        await update.message.reply_text(f"🗑️ *{s}* silindi. ({n} kayıt)", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ `{s}` bulunamadı.", parse_mode="Markdown")


if __name__ == "__main__":
    main()
