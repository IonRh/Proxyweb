from flask import Flask, request, jsonify, Response, make_response
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
import requests
from functools import lru_cache
import hashlib

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置参数
MAX_POOL_SIZE = 2  # 减少池大小以降低内存占用
PRELOAD_SIZE = 1   # 减少预加载数量
PAGE_LOAD_TIMEOUT = 8  # 减少页面加载超时时间
CACHE_EXPIRY = 300  # 缓存过期时间（秒）
ENABLE_CACHE = True  # 是否启用缓存
USE_LIGHTWEIGHT_MODE = False  # 是否使用轻量模式（仅使用requests而非selenium）

# 浏览器实例池
driver_pool = queue.Queue(maxsize=MAX_POOL_SIZE)
driver_lock = threading.Lock()

# 简单的内存缓存
page_cache = {}

# 用户代理池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/130.0",
]

def init_driver():
    """初始化浏览器，动态选择 Chrome 或 Chromium，并优化内存使用"""
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
    
    # 性能优化选项
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-java")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-default-apps")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--disable-translate")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.add_argument("--disable-client-side-phishing-detection")
    chrome_options.add_argument("--disable-component-update")
    chrome_options.add_argument("--disable-domain-reliability")
    chrome_options.add_argument("--disable-hang-monitor")
    chrome_options.add_argument("--disable-ipc-flooding-protection")
    chrome_options.add_argument("--disable-prompt-on-repost")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    chrome_options.add_argument("--disable-web-resources")
    chrome_options.add_argument("--memory-model=low")
    chrome_options.add_argument("--js-flags=--expose-gc")
    chrome_options.add_argument("--window-size=1280,720")  # 降低分辨率
    
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
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)  # 设置页面加载超时时间
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
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
            
            # 执行垃圾回收
            driver.execute_script("if (window.gc) window.gc();")
            
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

def get_url_hash(url):
    """生成URL的哈希值作为缓存键"""
    return hashlib.md5(url.encode('utf-8')).hexdigest()

def is_cache_valid(cache_time):
    """检查缓存是否有效"""
    return (time.time() - cache_time) < CACHE_EXPIRY

def fetch_with_requests(url):
    """使用requests库获取页面内容（轻量模式）"""
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        response = requests.get(url, headers=headers, timeout=PAGE_LOAD_TIMEOUT)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"使用requests获取页面失败: {str(e)}")
        raise

def fetch_with_selenium(url, driver):
    """使用Selenium获取页面内容"""
    try:
        driver.get(url)
        try:
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except Exception as e:
            logger.warning(f"页面加载超时: {str(e)}")
        
        # 减少滚动操作以节省资源
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(0.5)
        
        return driver.page_source
    except Exception as e:
        logger.error(f"使用Selenium获取页面失败: {str(e)}")
        raise

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
            
        # 检查是否使用轻量模式
        use_lightweight = request.args.get('lightweight', USE_LIGHTWEIGHT_MODE)
        if use_lightweight == 'true' or use_lightweight is True:
            use_lightweight = True
        else:
            use_lightweight = False
            
        # 检查缓存
        url_hash = get_url_hash(url)
        if ENABLE_CACHE and url_hash in page_cache:
            cache_data = page_cache[url_hash]
            if is_cache_valid(cache_data['timestamp']):
                logger.info(f"从缓存返回: {url}")
                return Response(cache_data['content'], mimetype='text/html')
            else:
                # 清理过期缓存
                del page_cache[url_hash]
        
        # 根据模式选择获取方式
        if use_lightweight:
            logger.info(f"使用轻量模式访问: {url}")
            page_source = fetch_with_requests(url)
        else:
            logger.info(f"使用Selenium访问: {url}")
            driver = get_driver()
            page_source = fetch_with_selenium(url, driver)
            release_driver(driver)
            driver = None
        
        # 存入缓存
        if ENABLE_CACHE:
            page_cache[url_hash] = {
                'content': page_source,
                'timestamp': time.time()
            }
            
            # 清理过期缓存（每10次请求检查一次）
            if random.randint(1, 10) == 1:
                clean_expired_cache()

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

def clean_expired_cache():
    """清理过期的缓存项"""
    current_time = time.time()
    expired_keys = [k for k, v in page_cache.items() if current_time - v['timestamp'] > CACHE_EXPIRY]
    for key in expired_keys:
        del page_cache[key]
    if expired_keys:
        logger.info(f"已清理 {len(expired_keys)} 个过期缓存项")

@app.route('/', methods=['GET'])
def index():
    page_source = "<h1>404</h1>"
    return Response(page_source, mimetype='text/html')

@app.route('/status', methods=['GET'])
def status():
    """返回服务状态信息"""
    status_info = {
        "active_drivers": MAX_POOL_SIZE - driver_pool.qsize(),
        "pool_size": MAX_POOL_SIZE,
        "cache_entries": len(page_cache),
        "cache_enabled": ENABLE_CACHE,
        "lightweight_mode": USE_LIGHTWEIGHT_MODE
    }
    return jsonify(status_info)

@app.route('/config', methods=['POST'])
def update_config():
    """更新服务配置"""
    global ENABLE_CACHE, USE_LIGHTWEIGHT_MODE, CACHE_EXPIRY
    
    try:
        data = request.get_json()
        if data.get('enable_cache') is not None:
            ENABLE_CACHE = bool(data['enable_cache'])
        
        if data.get('use_lightweight') is not None:
            USE_LIGHTWEIGHT_MODE = bool(data['use_lightweight'])
            
        if data.get('cache_expiry') is not None:
            CACHE_EXPIRY = int(data['cache_expiry'])
            
        return jsonify({"status": "success", "config": {
            "enable_cache": ENABLE_CACHE,
            "use_lightweight": USE_LIGHTWEIGHT_MODE,
            "cache_expiry": CACHE_EXPIRY
        }})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

# 初始化浏览器池
def init_driver_pool(pool_size=PRELOAD_SIZE):
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
    init_driver_pool(PRELOAD_SIZE)
    
    try:
        app.run(debug=False, host='0.0.0.0', port=5000)
    finally:
        # 确保应用关闭时清理资源
        cleanup_resources()
