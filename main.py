import requests
from bs4 import BeautifulSoup
import os
import re
import time

CHANNEL = os.getenv("EITAA_CHANNEL")
TOKEN = os.getenv("TELEGRAM_TOKEN")
# همه چت‌آیدی‌ها رو با کاما از هم جدا کن
CHAT_IDS = [cid.strip() for cid in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if cid.strip()]
LIMIT = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def extract_bg_url(style):
    """از یک style attribute مثل background-image:url('...') آدرس عکس رو استخراج می‌کنه"""
    if not style:
        return None
    m = re.search(r"background-image:\s*url\(['\"]?(.*?)['\"]?\)", style)
    return m.group(1) if m else None


def get_latest_messages(channel):
    url = f"https://eitaa.com/{channel}"
    messages = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        posts = soup.find_all("div", class_="etme_widget_message")

        for post in posts[:LIMIT]:
            text_div = post.find("div", class_="etme_widget_message_text")
            text = text_div.get_text(separator="\n", strip=True) if text_div else ""

            post_url = ""
            link_tag = post.find("a", href=True)
            if link_tag and channel in link_tag.get("href", ""):
                href = link_tag["href"]
                post_url = "https://eitaa.com" + href if href.startswith("/") else href

            photos = []
            videos = []
            gifs = []
            stickers = []
            documents = []

            # عکس‌ها: دیوهایی که کلاسشون شامل photo هست و background-image دارن (استیکر رو استثنا می‌کنیم)
            for div in post.find_all("div", style=True):
                classes = " ".join(div.get("class", [])).lower()
                if "photo" in classes and "sticker" not in classes:
                    bg = extract_bg_url(div.get("style", ""))
                    if bg and bg not in photos:
                        photos.append(bg)

            # استیکرها: دیو/img با کلاس شامل sticker
            for tag in post.find_all(["div", "img"]):
                classes = " ".join(tag.get("class", [])).lower()
                if "sticker" in classes:
                    src = tag.get("src") or extract_bg_url(tag.get("style", ""))
                    if src and src not in stickers:
                        stickers.append(src)

            # ویدیو/گیف: تگ <video> یا <source> داخلش؛ اگه کلاس والد شامل gif/roundvideo باشه، به‌عنوان گیف علامت می‌زنیم
            for video_tag in post.find_all("video"):
                src = video_tag.get("src") or video_tag.get("data-src")
                if not src:
                    source_tag = video_tag.find("source")
                    if source_tag:
                        src = source_tag.get("src")
                if not src:
                    continue
                parent_classes = " ".join(video_tag.find_parent("div").get("class", [])).lower() if video_tag.find_parent("div") else ""
                is_gif = "gif" in parent_classes or video_tag.get("loop") is not None or video_tag.get("autoplay") is not None
                if is_gif:
                    if src not in gifs:
                        gifs.append(src)
                else:
                    if src not in videos:
                        videos.append(src)

            # فایل‌ها: لینک‌هایی که به یک فایل با پسوند شناخته‌شده اشاره می‌کنن
            for a in post.find_all("a", href=True):
                href = a["href"]
                if re.search(r"\.(pdf|zip|rar|7z|docx?|xlsx?|pptx?|apk|mp3|ogg|txt)(\?.*)?$", href, re.I):
                    if href not in documents:
                        documents.append(href)

            if text.strip() or photos or videos or gifs or stickers or documents:
                messages.append({
                    "text": text,
                    "post_url": post_url,
                    "photos": photos,
                    "videos": videos,
                    "gifs": gifs,
                    "stickers": stickers,
                    "documents": documents,
                })

        return messages
    except Exception as e:
        return [{
            "text": f"❌ خطا در دریافت پیام‌ها:\n{str(e)}",
            "post_url": "", "photos": [], "videos": [], "gifs": [], "stickers": [], "documents": [],
        }]


def download_file(url):
    """فایل رو دانلود می‌کنه تا بعدا مستقیم به تلگرام آپلود بشه (به‌جای send by URL که ممکنه CDN ایتا بلاکش کنه)"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"خطا در دانلود فایل {url}: {e}")
        return None


def send_to_telegram(text, chat_id):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text[:4090],
        "disable_web_page_preview": False
    }
    try:
        response = requests.post(url, data=data, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"خطا در ارسال پیام به {chat_id}: {e}")
        return False


def send_media_to_telegram(chat_id, media_type, file_bytes, filename, caption=""):
    method_map = {
        "photo": "sendPhoto",
        "video": "sendVideo",
        "document": "sendDocument",
        "animation": "sendAnimation",  # گیف
        "sticker": "sendSticker",       # استیکر (کپشن نداره)
    }
    field_map = {
        "photo": "photo", "video": "video", "document": "document",
        "animation": "animation", "sticker": "sticker",
    }
    url = f"https://api.telegram.org/bot{TOKEN}/{method_map[media_type]}"
    data = {"chat_id": chat_id}
    if media_type != "sticker":
        data["caption"] = caption[:1024]
    files = {field_map[media_type]: (filename, file_bytes)}
    try:
        response = requests.post(url, data=data, files=files, timeout=120)
        if response.status_code == 200:
            return True
        # اگه sendSticker به هر دلیلی fail شد (مثلا فرمت مناسب نبود)، به‌عنوان عکس/فایل بفرست
        if media_type == "sticker":
            return send_media_to_telegram(chat_id, "photo", file_bytes, filename, caption) \
                or send_media_to_telegram(chat_id, "document", file_bytes, filename, caption)
        return False
    except Exception as e:
        print(f"خطا در ارسال {media_type} به {chat_id}: {e}")
        return False


def send_message_group(msg, chat_id):
    """یک پیام کامل (متن + عکس/ویدیو/فایل در صورت وجود) رو برای یک چت ارسال می‌کنه"""
    text = msg["text"]
    full_text = f"{text}\n\n🔗 {msg['post_url']}" if msg["post_url"] else text
    caption = full_text[:1024]
    caption_used = False
    any_sent = False

    for i, photo_url in enumerate(msg["photos"]):
        content = download_file(photo_url)
        if content:
            cap = caption if not caption_used else ""
            if send_media_to_telegram(chat_id, "photo", content, f"photo_{i}.jpg", cap):
                caption_used = True
                any_sent = True
            time.sleep(1)

    for i, video_url in enumerate(msg["videos"]):
        content = download_file(video_url)
        if content:
            cap = caption if not caption_used else ""
            if send_media_to_telegram(chat_id, "video", content, f"video_{i}.mp4", cap):
                caption_used = True
                any_sent = True
            time.sleep(1)

    for i, gif_url in enumerate(msg.get("gifs", [])):
        content = download_file(gif_url)
        if content:
            cap = caption if not caption_used else ""
            if send_media_to_telegram(chat_id, "animation", content, f"gif_{i}.mp4", cap):
                caption_used = True
                any_sent = True
            time.sleep(1)

    for i, sticker_url in enumerate(msg.get("stickers", [])):
        content = download_file(sticker_url)
        if content:
            ext = "webp" if sticker_url.lower().endswith(".webp") else "png"
            # استیکر کپشن نداره، پس کپشن رو جدا به‌عنوان پیام متنی می‌فرستیم اگه هنوز نرفته
            if send_media_to_telegram(chat_id, "sticker", content, f"sticker_{i}.{ext}", ""):
                any_sent = True
            time.sleep(1)

    for i, doc_url in enumerate(msg["documents"]):
        content = download_file(doc_url)
        if content:
            filename = doc_url.split("/")[-1].split("?")[0] or f"file_{i}"
            cap = caption if not caption_used else ""
            if send_media_to_telegram(chat_id, "document", content, filename, cap):
                caption_used = True
                any_sent = True
            time.sleep(1)

    if not caption_used and full_text.strip():
        any_sent = send_to_telegram(full_text, chat_id) or any_sent

    return any_sent


if __name__ == "__main__":
    if not all([CHANNEL, TOKEN]) or not CHAT_IDS:
        print("خطا: متغیرهای محیطی تنظیم نشده‌اند")
        exit(1)

    print(f"در حال دریافت پیام‌های کانال {CHANNEL}...")
    print(f"تعداد اکانت‌ها: {len(CHAT_IDS)}")

    msgs = get_latest_messages(CHANNEL)

    if not msgs:
        for chat_id in CHAT_IDS:
            send_to_telegram("هیچ پیامی پیدا نشد.", chat_id)
    else:
        for i, msg in enumerate(reversed(msgs), 1):
            for chat_id in CHAT_IDS:
                success = send_message_group(msg, chat_id)
                print(f"پیام {i} به {chat_id} ارسال شد: {success}")
            time.sleep(1.2)

    print(f"تمام. تعداد پیام‌ها: {len(msgs)}")
