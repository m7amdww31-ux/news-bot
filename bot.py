# -*- coding: utf-8 -*-
"""
بوت أخبار ديسكورد
=========================================
بوت يجيب أخبار عربية عامة/عالمية من مصادر RSS.
- أمر يدوي: #اخبار  (يجيب آخر الأخبار وقت ما تبي)
- نشر تلقائي: ينشر الأخبار الجديدة في قناة محددة كل فترة
المكتبات: discord.py + feedparser
"""

import os
import json
import asyncio
import datetime
import logging

import discord
from discord.ext import commands, tasks
import feedparser

# ------------------------------------------------------------------ #
#  الإعدادات
# ------------------------------------------------------------------ #

# التوكن يجي من متغيرات البيئة (Railway → Variables)
TOKEN = os.getenv("DISCORD_TOKEN")

# رمز الأوامر
PREFIX = "#"

# كل كم دقيقة يفحص الأخبار الجديدة (من متغير البيئة أو ١٥ افتراضي)
INTERVAL = int(os.getenv("NEWS_INTERVAL_MINUTES", "15"))

# قناة النشر التلقائي الافتراضية (اختياري، تقدرين تحطينها كـ ID)
DEFAULT_CHANNEL = os.getenv("NEWS_CHANNEL_ID")

# كم خبر يطلع مع أمر #اخبار افتراضياً
DEFAULT_COUNT = 5

# كم خبر ينشر في كل دورة نشر تلقائي (افتراضي ٣)
PER_POST = int(os.getenv("NEWS_PER_POST", "3"))

# ملف يحفظ الإعدادات والروابط المنشورة (ينحفظ محلياً)
DATA_FILE = "data.json"

# ------------------------------------------------------------------ #
#  مصادر الأخبار (RSS) - عربية عامة/عالمية
#  تقدرين تضيفين/تحذفين أي مصدر. لو رابط ما اشتغل البوت يتخطاه.
# ------------------------------------------------------------------ #
FEEDS = {
    "الجزيرة": "https://www.aljazeera.net/xml/rss/all.xml",
    "BBC عربي": "https://feeds.bbci.co.uk/arabic/rss.xml",
    "RT عربي": "https://arabic.rt.com/rss/",
    "سكاي نيوز عربية": "https://www.skynewsarabia.com/web/rss/91.xml",
    "العربية": "https://www.alarabiya.net/feed/rss2/ar.xml",
}

# لون مميز لكل مصدر (اختياري - شكلي)
COLORS = {
    "الجزيرة": 0xC8842E,
    "BBC عربي": 0xBB1919,
    "RT عربي": 0x4CA22F,
    "سكاي نيوز عربية": 0x0F4C81,
    "العربية": 0xD4AF37,
}
DEFAULT_COLOR = 0x2B3A55

# ------------------------------------------------------------------ #
#  اللوق
# ------------------------------------------------------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("news-bot")

# ------------------------------------------------------------------ #
#  حفظ/تحميل البيانات
# ------------------------------------------------------------------ #
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"تعذّر قراءة {DATA_FILE}: {e}")
    return {"channel_id": None, "seen": [], "auto_on": True}


def save_data(data: dict) -> None:
    try:
        # نقص قائمة المنشورة عشان ما تكبر بلا حدود
        data["seen"] = data["seen"][-800:]
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        log.warning(f"تعذّر حفظ {DATA_FILE}: {e}")


data = load_data()
if DEFAULT_CHANNEL and not data.get("channel_id"):
    try:
        data["channel_id"] = int(DEFAULT_CHANNEL)
    except ValueError:
        pass

# ------------------------------------------------------------------ #
#  البوت
# ------------------------------------------------------------------ #
intents = discord.Intents.default()
intents.message_content = True  # ضروري للأوامر النصية

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


# ------------------------------------------------------------------ #
#  جلب الأخبار (feedparser متزامن، نشغّله في executor عشان ما يوقف البوت)
# ------------------------------------------------------------------ #
async def fetch_feed(url: str):
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, feedparser.parse, url)
    except Exception as e:
        log.warning(f"فشل جلب {url}: {e}")
        return None


async def get_latest(per_source: int = 3):
    """يرجّع قائمة أخبار من كل المصادر: [(source, entry), ...]"""
    items = []
    for source, url in FEEDS.items():
        parsed = await fetch_feed(url)
        if not parsed or not getattr(parsed, "entries", None):
            log.info(f"لا توجد أخبار من: {source}")
            continue
        for entry in parsed.entries[:per_source]:
            items.append((source, entry))
    return items


def entry_id(entry) -> str:
    return getattr(entry, "id", None) or getattr(entry, "link", "") or getattr(entry, "title", "")


def make_embed(source: str, entry) -> discord.Embed:
    title = getattr(entry, "title", "بدون عنوان")
    link = getattr(entry, "link", None)

    # ملخّص مختصر إن وجد
    summary = getattr(entry, "summary", "") or ""
    # نشيل أي وسوم HTML بسيطة
    import re
    summary = re.sub(r"<[^>]+>", "", summary).strip()
    if len(summary) > 300:
        summary = summary[:297] + "..."

    embed = discord.Embed(
        title=title[:256],
        url=link,
        description=summary or None,
        color=COLORS.get(source, DEFAULT_COLOR),
    )
    embed.set_author(name=f"📰 {source}")

    # وقت النشر إن وجد
    if getattr(entry, "published", None):
        embed.set_footer(text=entry.published)

    # صورة مصغّرة إن وجدت
    img = None
    if getattr(entry, "media_thumbnail", None):
        img = entry.media_thumbnail[0].get("url")
    elif getattr(entry, "media_content", None):
        img = entry.media_content[0].get("url")
    elif getattr(entry, "links", None):
        for l in entry.links:
            if l.get("type", "").startswith("image"):
                img = l.get("href")
                break
    if img:
        embed.set_thumbnail(url=img)

    return embed


# ------------------------------------------------------------------ #
#  الأحداث
# ------------------------------------------------------------------ #
@bot.event
async def on_ready():
    log.info(f"تم تسجيل الدخول كـ {bot.user}")
    # نعلّم كل الأخبار الحالية كـ"مقروءة" عشان ما يصير سبام أول تشغيل
    if not data.get("seen"):
        items = await get_latest(per_source=10)
        data["seen"] = [entry_id(e) for _, e in items]
        save_data(data)
        log.info(f"تم تجهيز {len(data['seen'])} خبر كمقروء.")
    # نشغّل حلقة النشر التلقائي
    if not auto_news.is_running():
        auto_news.start()
    await bot.change_presence(activity=discord.Game(name="#اخبار 📰"))


# ------------------------------------------------------------------ #
#  حلقة النشر التلقائي
# ------------------------------------------------------------------ #
@tasks.loop(minutes=INTERVAL)
async def auto_news():
    if not data.get("auto_on", True):
        return
    channel_id = data.get("channel_id")
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        return

    items = await get_latest(per_source=5)
    seen = set(data.get("seen", []))
    new_items = [(s, e) for s, e in items if entry_id(e) not in seen]

    if not new_items:
        return

    # ننشر الأقدم أولاً، وبحد أقصى PER_POST بالمرة الواحدة
    new_items = new_items[:PER_POST]
    for source, entry in reversed(new_items):
        try:
            await channel.send(embed=make_embed(source, entry))
            data["seen"].append(entry_id(entry))
            await asyncio.sleep(1.5)  # نتجنب حدود ديسكورد
        except Exception as e:
            log.warning(f"تعذّر إرسال خبر: {e}")

    save_data(data)
    log.info(f"تم نشر {len(new_items)} خبر جديد في القناة.")


@auto_news.before_loop
async def before_auto():
    await bot.wait_until_ready()


# ------------------------------------------------------------------ #
#  الأوامر
# ------------------------------------------------------------------ #
@bot.command(name="اخبار")
async def news_cmd(ctx, count: int = DEFAULT_COUNT):
    """يجيب آخر الأخبار. مثال: #اخبار 3"""
    count = max(1, min(count, 10))
    async with ctx.typing():
        items = await get_latest(per_source=5)

    if not items:
        await ctx.send("⚠️ ما قدرت أجيب أخبار حالياً، جرّبي بعد شوي.")
        return

    # ناخذ أحدث الأخبار من كل المصادر
    for source, entry in items[:count]:
        await ctx.send(embed=make_embed(source, entry))
        await asyncio.sleep(0.5)


@bot.command(name="قناة_الاخبار")
@commands.has_permissions(manage_channels=True)
async def set_channel(ctx):
    """يخلي القناة الحالية قناة النشر التلقائي."""
    data["channel_id"] = ctx.channel.id
    data["auto_on"] = True
    save_data(data)
    await ctx.send(f"✅ تم تعيين {ctx.channel.mention} كقناة الأخبار. بنشر كل {INTERVAL} دقيقة.")


@bot.command(name="ايقاف_الاخبار")
@commands.has_permissions(manage_channels=True)
async def stop_auto(ctx):
    """يوقف النشر التلقائي."""
    data["auto_on"] = False
    save_data(data)
    await ctx.send("⏸️ تم إيقاف النشر التلقائي. ترجعينه بأمر `#قناة_الاخبار`.")


@bot.command(name="مصادر")
async def sources_cmd(ctx):
    """يعرض مصادر الأخبار."""
    lst = "\n".join(f"• {name}" for name in FEEDS)
    await ctx.send(f"📰 **مصادر الأخبار:**\n{lst}")


@bot.command(name="مساعدة")
async def help_cmd(ctx):
    embed = discord.Embed(title="📰 أوامر بوت الأخبار", color=DEFAULT_COLOR)
    embed.add_field(name="`#اخبار`", value="يجيب آخر الأخبار (تقدرين تحددين العدد: `#اخبار 3`)", inline=False)
    embed.add_field(name="`#قناة_الاخبار`", value="يخلي القناة الحالية قناة النشر التلقائي (للمشرفين)", inline=False)
    embed.add_field(name="`#ايقاف_الاخبار`", value="يوقف النشر التلقائي (للمشرفين)", inline=False)
    embed.add_field(name="`#مصادر`", value="يعرض مصادر الأخبار", inline=False)
    await ctx.send(embed=embed)


@set_channel.error
@stop_auto.error
async def perm_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 هذا الأمر للمشرفين فقط (صلاحية إدارة القنوات).")


# ------------------------------------------------------------------ #
#  التشغيل
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("❌ ما لقيت DISCORD_TOKEN. حطّيه في متغيرات البيئة.")
    bot.run(TOKEN)
