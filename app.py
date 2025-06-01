import asyncio
import logging
import time
from fastapi import FastAPI, HTTPException
from starlette.responses import HTMLResponse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

app = FastAPI()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局 WebDriver 实例和异步锁
driver = None
driver_lock = asyncio.Lock()

def init_driver():
    """初始化 Chrome 浏览器，优化反爬设置"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")  # 生产环境中启用 headless
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # 反爬措施
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

async def cleanup_driver():
    """清理 WebDriver 资源"""
    global driver
    async with driver_lock:
        if driver is not None:
            driver.quit()
            logger.info("WebDriver 已关闭")
            driver = None

# 在应用启动时初始化 WebDriver
driver = init_driver()

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
            driver.get(url)
            time.sleep(2)  # 视网站动态加载时间调整
            page_source = driver.page_source

        return HTMLResponse(content=page_source)

    except Exception as e:
        logger.error(f"错误: {str(e)}")
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
