import requests
from bs4 import BeautifulSoup

CHANNEL = "oliayazdahoom"
url = f"https://eitaa.com/{CHANNEL}"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

r = requests.get(url, headers=headers, timeout=30)
soup = BeautifulSoup(r.text, "html.parser")
posts = soup.find_all("div", class_="etme_widget_message")

print(f"تعداد پست‌های پیدا شده: {len(posts)}")

for post in posts:
    if post.find("img") or "background-image" in str(post):
        print(post.prettify()[:3000])
        break
else:
    print("هیچ پستی با عکس پیدا نشد در این ۱۰ پست")
