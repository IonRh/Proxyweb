from flask import Flask, request, jsonify, Response
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import logging
import random
import platform
import os

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 用户代理池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/130.0",
]

def init_driver():
    """初始化浏览器，动态选择 Chrome 或 Chromium"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--window-size=1920,1080")

    # 动态查找 Chromium 可执行文件
    arch = platform.machine()
    browser_binary = None
    possible_paths = ["/usr/bin/chromium", "/usr/lib/chromium-browser/chromium", "/usr/bin/chromium-browser"]
    for path in possible_paths:
        if os.path.exists(path):
            browser_binary = path
            break
    if not browser_binary:
        logger.error("未找到 Chromium 可执行文件")
        raise Exception("未找到 Chromium 可执行文件")

    chrome_options.binary_location = browser_binary
    logger.info(f"使用浏览器: {browser_binary}")

    # 使用 chromium-driver
    service = webdriver.chrome.service.Service('/usr/bin/chromedriver')
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.execute_script("""
            window.addEventListener('mousemove', function(e) {
                window._mouseX = e.clientX;
                window._mouseY = e.clientY;
            });
        """)
        logger.info(f"WebDriver 初始化成功，浏览器版本: {driver.capabilities['browserVersion']}")
        return driver
    except Exception as e:
        logger.error(f"初始化 WebDriver 失败: {str(e)}")
        raise

@app.route('/fetch', methods=['GET'])
def fetch_page():
    """处理 GET 请求，拼接 URL 并返回页面内容"""
    try:
        url = request.args.get('url')
        if not url:
            return jsonify({"error": "URL 参数缺失"}), 400

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        driver = init_driver()
        logger.info(f"正在访问: {url}")

        driver.get(url)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except Exception as e:
            logger.warning(f"页面加载超时: {str(e)}")

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(0.5, 1.5))
        driver.execute_script("window.scrollTo(0, 0);")
        
        page_source = driver.page_source
        driver.quit()

        return Response(page_source, mimetype='text/html')

    except Exception as e:
        logger.error(f"错误: {str(e)}")
        return jsonify({"error": str(e)}), 500
@app.route('/', methods=['GET'])
def index():
    page_source="<h1>404</h1>"
    return Response(page_source, mimetype='text/html')
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
