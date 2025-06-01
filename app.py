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
import time
import threading
import queue

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 浏览器实例池
driver_pool = queue.Queue(maxsize=3)  # 最多同时保持3个浏览器实例
driver_lock = threading.Lock()  # 用于线程安全操作

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

def get_driver():
    """从池中获取一个浏览器实例，如果池为空则创建新实例"""
    try:
        return driver_pool.get(block=False)
    except queue.Empty:
        logger.info("创建新的浏览器实例")
        return init_driver()

def release_driver(driver):
    """将浏览器实例归还到池中，如果池已满则关闭该实例"""
    if driver:
        try:
            # 清理浏览器状态
            driver.delete_all_cookies()
            driver.execute_script("window.localStorage.clear();")
            driver.execute_script("window.sessionStorage.clear();")
            
            # 尝试将浏览器放回池中
            driver_pool.put(driver, block=False)
            logger.info("浏览器实例已归还到池中")
        except queue.Full:
            # 如果池已满，关闭浏览器
            driver.quit()
            logger.info("浏览器池已满，关闭浏览器实例")
        except Exception as e:
            # 如果发生其他异常，确保浏览器被关闭
            try:
                driver.quit()
            except:
                pass
            logger.error(f"归还浏览器实例时出错: {str(e)}")

@app.route('/fetch', methods=['GET'])
def fetch_page():
    """处理 GET 请求，拼接 URL 并返回页面内容"""
    driver = None
    try:
        url = request.args.get('url')
        if not url:
            return jsonify({"error": "URL 参数缺失"}), 400

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        driver = get_driver()
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
        
        # 不要在这里关闭driver，而是归还到池中
        release_driver(driver)
        driver = None

        return Response(page_source, mimetype='text/html')

    except Exception as e:
        logger.error(f"错误: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        # 确保在出现异常时也能正确处理driver
        if driver:
            try:
                release_driver(driver)
            except:
                pass

@app.route('/', methods=['GET'])
def index():
    page_source = "<h1>404</h1>"
    return Response(page_source, mimetype='text/html')

# 初始化浏览器池
def init_driver_pool(pool_size=2):
    """预先初始化一些浏览器实例到池中"""
    for _ in range(min(pool_size, driver_pool.maxsize)):
        try:
            driver = init_driver()
            driver_pool.put(driver)
            logger.info("预初始化浏览器实例添加到池中")
        except Exception as e:
            logger.error(f"预初始化浏览器失败: {str(e)}")

# 应用关闭时清理资源
def cleanup_resources():
    """关闭所有浏览器实例"""
    while not driver_pool.empty():
        try:
            driver = driver_pool.get(block=False)
            if driver:
                driver.quit()
                logger.info("关闭浏览器实例")
        except:
            pass

if __name__ == '__main__':
    # 启动时初始化浏览器池
    init_driver_pool(2)
    
    try:
        app.run(debug=False, host='0.0.0.0', port=5000)
    finally:
        # 确保应用关闭时清理资源
        cleanup_resources()
