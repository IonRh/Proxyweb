import asyncio
import logging
from fastapi import FastAPI, HTTPException
from starlette.responses import HTMLResponse
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

app = FastAPI()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 全局 WebDriver 实例和异步锁
driver = None
driver_lock = asyncio.Lock()

def init_driver():
    """初始化 Chrome 浏览器，优化反爬设置"""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")  # 生产环境中启用 headless
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # 反爬措施
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Selenium-wire 特定的配置
        seleniumwire_options = {
            'suppress_connection_errors': True,  # 抑制连接错误
            'connection_timeout': 10,  # 设置连接超时
        }
        
        # 使用 ChromeDriverManager 自动匹配 Chromium 版本
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager(chrome_type="chromium").install()),
            options=chrome_options,
            seleniumwire_options=seleniumwire_options
        )
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        logger.info("WebDriver 初始化成功")
        return driver
    except Exception as e:
        logger.error(f"WebDriver 初始化失败: {str(e)}")
        raise

async def cleanup_driver():
    """清理 WebDriver 资源"""
    global driver
    async with driver_lock:
        if driver is not None:
            try:
                driver.quit()
                logger.info("WebDriver 已关闭")
            except Exception as e:
                logger.error(f"WebDriver 关闭失败: {str(e)}")
            driver = None

# 在应用启动时初始化 WebDriver
try:
    driver = init_driver()
except Exception as e:
    logger.critical(f"启动时 WebDriver 初始化失败: {str(e)}")
    raise

# 注册清理函数，确保应用关闭时释放资源
@app.on_event("shutdown")
async def shutdown_event():
    await cleanup_driver()

@app.get("/fetch")
async def fetch_page(url: str | None = None):
    """处理 GET 请求，拼接 URL 并返回页面内容"""
    global driver
    try:
        if not url:
            raise HTTPException(status_code=400, detail="URL 参数缺失")

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        logger.info(f"正在访问: {url}")
        async with driver_lock:
            # 清空之前的请求数据（selenium-wire 特性）
            del driver.requests
            driver.get(url)
            # 显式等待页面 body 元素加载完成，最多等待 10 秒
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            page_source = driver.page_source

        return HTMLResponse(content=page_source)

    except Exception as e:
        logger.error(f"请求处理错误: {str(e)}")
        async with driver_lock:
            try:
                driver.quit()
            except:
                pass
            driver = init_driver()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
