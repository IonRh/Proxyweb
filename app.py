from flask import Flask, request, jsonify, Response
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import logging
import time

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_driver():
    """初始化 Chrome 浏览器，优化反爬设置"""
    chrome_options = Options()
    # 可选启用 headless，视情况注释
    chrome_options.add_argument("--headless=new")  # 新 headless 模式
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # 反爬措施
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")  # 隐藏自动化标志
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(options=chrome_options)
    # 移除 webdriver 属性
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


@app.route('/fetch', methods=['GET'])
def fetch_page():
    """处理 GET 请求，拼接 URL 并返回页面内容"""
    try:
        # 获取 URL 参数
        url = request.args.get('url')
        if not url:
            return jsonify({"error": "URL 参数缺失"}), 400

        # 确保 URL 包含协议
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        # 初始化浏览器
        driver = init_driver()
        logger.info(f"正在访问: {url}")

        # 获取页面内容，添加延迟以确保动态内容加载
        driver.get(url)
        time.sleep(2)  # 视网站动态加载时间调整
        page_source = driver.page_source

        # 关闭浏览器
        driver.quit()

        return Response(page_source, mimetype='text/html')

    except Exception as e:
        logger.error(f"错误: {str(e)}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
