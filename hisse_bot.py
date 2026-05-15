"""
📈 Profesyonel Hisse Takip Botu — Grup Uyumlu
───────────────────────────────────────────────
Sadece "Takipçi" ile başlayan mesajlara cevap verir.

Kullanım:
  Takipçi Karel 12.70                        → tek hisse
  Takipçi Karel 12.70 Glrmk 192 Hatsn 45.4  → çoklu hisse
  Takipçi menu                               → ana menü
  Takipçi son durum                          → rapor
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
PREFIX    = "takipçi"   # küçük harfle karşılaştırılacak

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
                sembol          TEXT    NOT NULL,
                sembol_goster   TEXT    NOT NULL,
                alis_fiyati     REAL    NOT NULL,
                adet            REAL    NOT NULL DEFAULT 1,
                alis_tarihi     TEXT    NOT NULL,
                durum           TEXT    NOT NULL DEFAULT 'acik',
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

def prefix_cikar(metin: str) -> str:
    """'Takipçi ...' → '...' döndürür."""
    parcalar = metin.strip().split(None, 1)
    return parcalar[1].strip() if len(parcalar) > 1 else ""


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
        [InlineKeyboardButton("❓ Yardım", callback_data="yardim")],
    ])

async def menu_goster(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    metin = (
        "📈 *Hisse Takip Botu*\n\n"
        "Hisse eklemek için:\n"
        "`Takipçi THYAO 125`\n"
        "`Takipçi Karel 12.70 Glrmk 192 Hatsn 45.4`\n\n"
        "Ne yapmak istersin?"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=ana_menu_klavye())
    else:
        await update.message.reply_text(metin, parse_mode="Markdown", reply_markup=ana_menu_klavye())


# ════════════════════════════════════════════
#  ÇOKLU HİSSE PARSE
# ════════════════════════════════════════════

def parse_hisseler(metin: str) -> list[tuple[str, float]] | None:
    """
    "Karel 12.70 Glrmk 192 Hatsn 45.4" gibi metni
    [("KAREL", 12.70), ("GLRMK", 192.0), ("HATSN", 45.4)] döndürür.
    Hatalıysa None.
    """
    parcalar = metin.split()
    if len(parcalar) % 2 != 0:
        return None
    sonuc = []
    for i in range(0, len(parcalar), 2):
        sembol = parcalar[i].upper()
        if not all(c.isalpha() or c.isdigit() or c == "-" for c in sembol):
            return None
        try:
            fiyat = float(parcalar[i + 1].replace(",", "."))
            if fiyat <= 0:
                return None
        except ValueError:
            return None
        sonuc.append((sembol, fiyat))
    return sonuc if sonuc else None


# ════════════════════════════════════════════
#  MESAJ YÖNETİCİ (sadece PREFIX ile başlayanlar)
# ════════════════════════════════════════════

# Bekleyen kapanış: {user_id: poz_id}
bekleyen_kapanis: dict[int, int] = {}

async def mesaj_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    metin = (update.message.text or "").strip()

    # Kapanış fiyatı bekleniyor mu?
    if uid in bekleyen_kapanis:
        # Takipçi prefix olmasa da kapanışı işle
        await _kapat_isle(update, ctx, uid, bekleyen_kapanis[uid])
        return

    # Prefix kontrolü — grup ve özel sohbet uyumlu
    if not metin.lower().startswith(PREFIX):
        return  # bot cevap vermez

    komut = prefix_cikar(metin).strip()

    if not komut:
        await menu_goster(update, ctx)
        return

    # Özel komutlar
    if komut.lower() in ["menu", "menü", "ana menü", "ana menu"]:
        await menu_goster(update, ctx)
        return

    if komut.lower() in ["son durum", "durum", "portfoy", "portföy"]:
        await _son_durum(update, uid)
        return

    if komut.lower() in ["yardim", "yardım"]:
        await _yardim_mesaj(update)
        return

    # Hisse parse dene
    hisseler = parse_hisseler(komut)

    if hisseler is None:
        await update.message.reply_text(
            "❓ Anlamadım.\n\n"
            "Tek hisse: `Takipçi THYAO 125`\n"
            "Çoklu: `Takipçi Karel 12.70 Glrmk 192 Hatsn 45.4`\n"
            "Menü: `Takipçi menu`",
            parse_mode="Markdown"
        )
        return

    # Çoklu hisse ekle
    await _hisse_ekle_coklu(update, uid, hisseler)


# ════════════════════════════════════════════
#  ÇOKLU HİSSE EKLE
# ════════════════════════════════════════════

async def _hisse_ekle_coklu(update: Update, uid: int, hisseler: list[tuple[str, float]]):
    if len(hisseler) == 1:
        bekle_msg = await update.message.reply_text(
            f"🔍 `{hisseler[0][0]}` aranıyor...", parse_mode="Markdown"
        )
    else:
        bekle_msg = await update.message.reply_text(
            f"🔍 {len(hisseler)} hisse aranıyor...", parse_mode="Markdown"
        )

    sonuclar = []
    hatalar  = []

    for sembol_goster, alis in hisseler:
        fiyat, sembol_tam = fiyat_al(sembol_goster)

        if fiyat is None:
            hatalar.append(sembol_goster)
            continue

        with db() as con:
            con.execute(
                "INSERT INTO pozisyonlar (kullanici, sembol, sembol_goster, alis_fiyati, adet, alis_tarihi) VALUES (?,?,?,?,?,?)",
                (uid, sembol_tam, sembol_goster, alis, 1.0, bugun())
            )
            con.commit()

        yuzde = ((fiyat - alis) / alis) * 100
        sonuclar.append((sembol_goster, alis, fiyat, yuzde))

    # Yanıt oluştur
    if len(sonuclar) == 1:
        g, alis, fiyat, yuzde = sonuclar[0]
        metin = (
            f"✅ *{g}* eklendi!\n\n"
            f"📅 `{fmt_tarih(bugun())}`\n"
            f"💰 Alış: `{alis:,.2f}`  →  Şimdi: `{fiyat:,.2f}`\n"
            f"{kar_emoji(yuzde)} `{yuzde:+.2f}%`"
        )
    elif sonuclar:
        satirlar = [f"✅ *{len(sonuclar)} hisse eklendi!*\n📅 `{fmt_tarih(bugun())}`\n"]
        for g, alis, fiyat, yuzde in sonuclar:
            satirlar.append(
                f"{kar_emoji(yuzde)} *{g}*  `{yuzde:+.2f}%`\n"
                f"   `{alis:,.2f}` → `{fiyat:,.2f}`"
            )
        metin = "\n".join(satirlar)
    else:
        metin = "⚠️ Hiçbir hisse eklenemedi."

    if hatalar:
        metin += f"\n\n⚠️ Bulunamadı: {', '.join(hatalar)}"

    klavye = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Son Durum",   callback_data="son_durum"),
            InlineKeyboardButton("📂 Açık Pozlar", callback_data="acik_pozlar"),
        ],
        [InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]
    ])

    await bekle_msg.edit_text(metin, parse_mode="Markdown", reply_markup=klavye)


# ════════════════════════════════════════════
#  SON DURUM
# ════════════════════════════════════════════

async def _son_durum(update, uid):
    with db() as con:
        kayitlar = con.execute(
            "SELECT sembol, sembol_goster, alis_fiyati, adet, alis_tarihi FROM pozisyonlar WHERE kullanici=? AND durum='acik' ORDER BY sembol_goster",
            (uid,)
        ).fetchall()

    klavye = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📂 Açık Pozlar",   callback_data="acik_pozlar"),
            InlineKeyboardButton("📁 Kapalı Pozlar", callback_data="kapali_pozlar"),
        ],
        [InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]
    ])

    if not kayitlar:
        metin = "📭 Açık pozisyon yok.\n\n`Takipçi THYAO 125` ile hisse ekle."
        if update.callback_query:
            await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=klavye)
        else:
            await update.message.reply_text(metin, parse_mode="Markdown", reply_markup=klavye)
        return

    semboller = list({r[0] for r in kayitlar})
    fiyatlar  = {}
    for s in semboller:
        try:
            info = yf.Ticker(s).fast_info
            f    = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
            fiyatlar[s] = float(f) if f else None
        except:
            fiyatlar[s] = None

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

    if update.callback_query:
        await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=klavye)
    else:
        await update.message.reply_text(metin, parse_mode="Markdown", reply_markup=klavye)


# ════════════════════════════════════════════
#  AÇIK POZİSYONLAR (kapat + sil butonu)
# ════════════════════════════════════════════

async def _acik_pozlar(update, uid, sayfa=0):
    with db() as con:
        kayitlar = con.execute(
            "SELECT id, sembol_goster, alis_fiyati, adet, alis_tarihi FROM pozisyonlar WHERE kullanici=? AND durum='acik' ORDER BY alis_tarihi DESC",
            (uid,)
        ).fetchall()

    if not kayitlar:
        klavye = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]])
        await update.callback_query.edit_message_text("📭 Açık pozisyon yok.", reply_markup=klavye)
        return

    metin = f"📂 *Açık Pozisyonlar*  ({len(kayitlar)} adet)\n━━━━━━━━━━━━━━━━━━\n\n"
    butonlar = []

    for poz_id, goster, alis, adet, tarih in kayitlar:
        gun = gun_farki(tarih)
        gun_metin = "bugün" if gun == 0 else f"{gun} gün önce"
        metin += (
            f"📌 *{goster}*  `{alis:,.2f}` × {adet:,.0f} adet\n"
            f"   📅 {fmt_tarih(tarih)}  _{gun_metin}_\n\n"
        )
        butonlar.append([
            InlineKeyboardButton(f"❌ {goster} Kapat",     callback_data=f"kapat_{poz_id}"),
            InlineKeyboardButton(f"🗑 {goster} Sil",       callback_data=f"sil_{poz_id}"),
        ])

    butonlar.append([InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")])
    await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(butonlar))


# ════════════════════════════════════════════
#  POZİSYON SİL (direkt)
# ════════════════════════════════════════════

async def _sil_poz(update, uid, poz_id):
    with db() as con:
        row = con.execute(
            "SELECT sembol_goster, alis_fiyati, adet FROM pozisyonlar WHERE id=? AND kullanici=?",
            (poz_id, uid)
        ).fetchone()
        if not row:
            await update.callback_query.answer("Bulunamadı.")
            return
        con.execute("DELETE FROM pozisyonlar WHERE id=?", (poz_id,))
        con.commit()

    goster, alis, adet = row
    await update.callback_query.answer(f"🗑 {goster} silindi.")
    await _acik_pozlar(update, uid)


# ════════════════════════════════════════════
#  POZİSYON KAPAT
# ════════════════════════════════════════════

async def _kapat_sor(update, uid, poz_id):
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

    klavye = InlineKeyboardMarkup([[InlineKeyboardButton("❌ İptal", callback_data="acik_pozlar")]])
    await update.callback_query.edit_message_text(
        f"❌ *{goster}* kapatılıyor\n\n"
        f"📅 {fmt_tarih(tarih)}  |  `{alis:,.2f}` × {adet:,.0f} adet\n\n"
        f"💬 *Satış fiyatını yaz:*\n_(Örn: `185.50`)_",
        parse_mode="Markdown",
        reply_markup=klavye
    )

async def _kapat_isle(update: Update, ctx: ContextTypes.DEFAULT_TYPE, uid: int, poz_id: int):
    metin = update.message.text.strip()

    # Eğer yeni bir Takipçi komutu yazıldıysa iptal et
    if metin.lower().startswith(PREFIX):
        del bekleyen_kapanis[uid]
        await mesaj_router(update, ctx)
        return

    try:
        satis = float(metin.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Geçersiz fiyat, tekrar yaz.")
        return

    with db() as con:
        row = con.execute(
            "SELECT sembol_goster, alis_fiyati, adet, alis_tarihi FROM pozisyonlar WHERE id=? AND kullanici=? AND durum='acik'",
            (poz_id, uid)
        ).fetchone()
        if not row:
            del bekleyen_kapanis[uid]
            await update.message.reply_text("⚠️ Pozisyon bulunamadı.")
            return
        goster, alis, adet, tarih = row
        con.execute(
            "UPDATE pozisyonlar SET durum='kapali', satis_fiyati=?, satis_tarihi=? WHERE id=?",
            (satis, bugun(), poz_id)
        )
        con.commit()

    del bekleyen_kapanis[uid]

    kar   = (satis - alis) * adet
    yuzde = ((satis - alis) / alis) * 100
    gun   = gun_farki(tarih)

    klavye = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📂 Açık Pozlar",   callback_data="acik_pozlar"),
            InlineKeyboardButton("📁 Kapalı Pozlar", callback_data="kapali_pozlar"),
        ],
        [InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]
    ])

    await update.message.reply_text(
        f"{kar_emoji(yuzde)} *{goster}* kapatıldı!\n\n"
        f"📅 {fmt_tarih(tarih)} → {fmt_tarih(bugun())}  _({gun}g)_\n"
        f"💰 `{alis:,.2f}` → `{satis:,.2f}`  |  {adet:,.0f} adet\n\n"
        f"{'🟢' if kar >= 0 else '🔴'} K/Z: `{kar:+,.2f}` ({yuzde:+.2f}%)",
        parse_mode="Markdown",
        reply_markup=klavye
    )


# ════════════════════════════════════════════
#  KAPALI POZİSYONLAR
# ════════════════════════════════════════════

async def _kapali_pozlar(update, uid):
    with db() as con:
        kayitlar = con.execute(
            "SELECT id, sembol_goster, alis_fiyati, satis_fiyati, adet, alis_tarihi, satis_tarihi FROM pozisyonlar WHERE kullanici=? AND durum='kapali' ORDER BY satis_tarihi DESC",
            (uid,)
        ).fetchall()

    if not kayitlar:
        klavye = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]])
        await update.callback_query.edit_message_text("📁 Henüz kapalı pozisyon yok.", reply_markup=klavye)
        return

    toplam_kar = 0.0
    satirlar   = []
    butonlar   = []

    for poz_id, goster, alis, satis, adet, a_tar, s_tar in kayitlar:
        kar   = (satis - alis) * adet
        yuzde = ((satis - alis) / alis) * 100
        gun   = (datetime.strptime(s_tar, "%Y-%m-%d") - datetime.strptime(a_tar, "%Y-%m-%d")).days
        toplam_kar += kar
        satirlar.append(
            f"{kar_emoji(yuzde)} *{goster}*  `{yuzde:+.2f}%`\n"
            f"   `{alis:,.2f}` → `{satis:,.2f}`  |  K/Z: `{kar:+,.2f}`\n"
            f"   _{fmt_tarih(a_tar)} – {fmt_tarih(s_tar)} ({gun}g)_"
        )
        butonlar.append([
            InlineKeyboardButton(f"🗑 {goster} Sil", callback_data=f"sil_{poz_id}")
        ])

    ozet_emoji = "🟢" if toplam_kar >= 0 else "🔴"
    metin = (
        f"📁 *Kapalı Pozisyonlar*  ({len(kayitlar)} işlem)\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(satirlar)
        + f"\n\n━━━━━━━━━━━━━━━━━━\n"
        f"{ozet_emoji} Toplam K/Z: `{toplam_kar:+,.2f}`"
    )

    butonlar.append([
        InlineKeyboardButton("📂 Açık Pozlar", callback_data="acik_pozlar"),
        InlineKeyboardButton("🏠 Ana Menü",    callback_data="ana_menu"),
    ])
    await update.callback_query.edit_message_text(metin, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(butonlar))


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
        klavye = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]])
        await update.callback_query.edit_message_text("📜 Hiç kayıt yok.", reply_markup=klavye)
        return

    satirlar = [f"📜 *İşlem Geçmişi*  (son {len(kayitlar)})\n━━━━━━━━━━━━━━━━━━"]
    for goster, alis, adet, a_tar, durum, satis, s_tar in kayitlar:
        if durum == "acik":
            gun = gun_farki(a_tar)
            satirlar.append(
                f"🟡 *{goster}*  `{alis:,.2f}` × {adet:,.0f}\n"
                f"   📅 {fmt_tarih(a_tar)}  —  _{gun}g açık_"
            )
        else:
            kar   = (satis - alis) * adet
            yuzde = ((satis - alis) / alis) * 100
            satirlar.append(
                f"{'🟢' if kar >= 0 else '🔴'} *{goster}*  `{alis:,.2f}` → `{satis:,.2f}`\n"
                f"   {fmt_tarih(a_tar)} – {fmt_tarih(s_tar)}  |  K/Z: `{kar:+,.2f}` ({yuzde:+.2f}%)"
            )

    klavye = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📂 Açık Pozlar",   callback_data="acik_pozlar"),
            InlineKeyboardButton("📁 Kapalı Pozlar", callback_data="kapali_pozlar"),
        ],
        [InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]
    ])
    await update.callback_query.edit_message_text("\n\n".join(satirlar), parse_mode="Markdown", reply_markup=klavye)


# ════════════════════════════════════════════
#  YARDIM
# ════════════════════════════════════════════

async def _yardim_mesaj(update):
    metin = (
        "❓ *Nasıl Kullanılır?*\n\n"
        "Her mesajın başına *Takipçi* yaz:\n\n"
        "`Takipçi THYAO 125`\n"
        "`Takipçi Karel 12.70 Glrmk 192`\n"
        "`Takipçi son durum`\n"
        "`Takipçi menu`\n\n"
        "Kapat/Sil:\n"
        "📂 Açık Pozlar → ❌ Kapat veya 🗑 Sil\n\n"
        "💡 _Grupta sadece Takipçi ile başlayan mesajlara cevap verir_"
    )
    klavye = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Ana Menü", callback_data="ana_menu")]])
    await update.message.reply_text(metin, parse_mode="Markdown", reply_markup=klavye)

async def _yardim(update, uid):
    metin = (
        "❓ *Nasıl Kullanılır?*\n\n"
        "Her mesajın başına *Takipçi* yaz:\n\n"
        "`Takipçi THYAO 125`\n"
        "`Takipçi Karel 12.70 Glrmk 192`\n"
        "`Takipçi son durum`\n"
        "`Takipçi menu`\n\n"
        "Kapat/Sil:\n"
        "📂 Açık Pozlar → ❌ Kapat veya 🗑 Sil\n\n"
        "💡 _Grupta sadece Takipçi ile başlayan mesajlara cevap verir_"
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

    if data == "ana_menu":          await menu_goster(update, ctx)
    elif data == "son_durum":       await _son_durum(update, uid)
    elif data == "acik_pozlar":     await _acik_pozlar(update, uid)
    elif data == "kapali_pozlar":   await _kapali_pozlar(update, uid)
    elif data == "gecmis":          await _gecmis(update, uid)
    elif data == "yardim":          await _yardim(update, uid)
    elif data.startswith("kapat_"): await _kapat_sor(update, uid, int(data.split("_")[1]))
    elif data.startswith("sil_"):   await _sil_poz(update, uid, int(data.split("_")[1]))


# ════════════════════════════════════════════
#  ANA PROGRAM
# ════════════════════════════════════════════

def main():
    db_olustur()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", menu_goster))
    app.add_handler(CommandHandler("menu",  menu_goster))
    app.add_handler(CallbackQueryHandler(callback_isle))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mesaj_router))
    print("🤖 Bot başlatılıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
