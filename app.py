from flask import Flask, request, jsonify, Response
from playwright.sync_api import sync_playwright
import logging
import random

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# 用户代理池
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
]

@app.route('/fetch', methods=['GET'])
def fetch_page():
    """处理 GET 请求，获取并返回网页内容"""
    try:
        url = request.args.get('url')
        if not url:
            return jsonify({"error": "URL 参数缺失"}), 400

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        logger.info(f"正在访问: {url}")
        with sync_playwright() as p:
            browser = p.webkit.launch(headless=True)
            context = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1280, "height": 720}
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=10000)
            page.evaluate("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page_source = page.content()
            browser.close()

        return Response(page_source, mimetype='text/html')

    except Exception as e:
        logger.error(f"错误: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET'])
def index():
    page_source = "<h1>404</h1>"
    return Response(page_source, mimetype='text/html')

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
