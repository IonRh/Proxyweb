import asyncio
import logging
from typing import Optional
from dataclasses import dataclass
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, HTMLResponse
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import re
import time
from contextlib import asynccontextmanager

app = FastAPI()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class DriverInfo:
    """WebDriver 信息"""
    driver: uc.Chrome
    in_use: bool = False
    created_at: float = 0.0
    last_used: float = 0.0
    usage_count: int = 0

class WebDriverPool:
    """WebDriver 连接池"""
    
    def __init__(self, pool_size: int = 1, max_usage_per_driver: int = 100, max_idle_time: int = 300):
        self.pool_size = pool_size
        self.max_usage_per_driver = max_usage_per_driver
        self.max_idle_time = max_idle_time
        self.pool: list[DriverInfo] = []
        self.pool_lock = asyncio.Lock()
        self.cleanup_task = None
        
    def create_driver_options(self) -> Options:
        """创建 Chrome 配置选项"""
        chrome_options = uc.ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
        
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.cookies": 1,
            "profile.managed_default_content_settings.plugins": 2,
            "profile.managed_default_content_settings.popups": 2,
            "profile.managed_default_content_settings.geolocation": 2,
            "profile.managed_default_content_settings.media_stream": 2,
        }
        chrome_options.add_experimental_option("prefs", prefs)
        return chrome_options
    
    def create_driver(self) -> uc.Chrome:
        """创建单个 WebDriver 实例"""
        try:
            chrome_options = self.create_driver_options()
            driver = uc.Chrome(
                options=chrome_options,
                headless=True,
                use_subprocess=False
            )
            driver.set_page_load_timeout(30)
            driver.implicitly_wait(10)
            return driver
        except Exception as e:
            logger.error(f"创建 WebDriver 失败: {str(e)}")
            raise
    
    async def initialize_pool(self):
        """初始化连接池"""
        logger.info(f"开始初始化 WebDriver 连接池，目标大小: {self.pool_size}")
        async with self.pool_lock:
            for i in range(self.pool_size):
                try:
                    logger.info(f"创建第 {i+1} 个 WebDriver 实例...")
                    driver = await asyncio.get_event_loop().run_in_executor(None, self.create_driver)
                    driver_info = DriverInfo(
                        driver=driver,
                        created_at=time.time(),
                        last_used=time.time()
                    )
                    self.pool.append(driver_info)
                    logger.info(f"第 {i+1} 个 WebDriver 实例创建成功")
                except Exception as e:
                    logger.error(f"创建第 {i+1} 个 WebDriver 实例失败: {str(e)}")
                    continue
        logger.info(f"连接池初始化完成，成功创建 {len(self.pool)} 个实例")
        self.cleanup_task = asyncio.create_task(self.cleanup_expired_drivers())
    
    @asynccontextmanager
    async def get_driver(self):
        """获取可用的 WebDriver 实例（上下文管理器）"""
        driver_info = None
        try:
            async with self.pool_lock:
                for info in self.pool:
                    if not info.in_use:
                        if info.usage_count >= self.max_usage_per_driver:
                            logger.info(f"WebDriver 使用次数过多({info.usage_count})，替换新实例")
                            await self._replace_driver(info)
                        info.in_use = True
                        info.usage_count += 1
                        info.last_used = time.time()
                        driver_info = info
                        break
                if driver_info is None:
                    logger.warning("连接池已满，创建临时 WebDriver 实例")
                    temp_driver = await asyncio.get_event_loop().run_in_executor(None, self.create_driver)
                    driver_info = DriverInfo(
                        driver=temp_driver,
                        in_use=True,
                        created_at=time.time(),
                        last_used=time.time(),
                        usage_count=1
                    )
            yield driver_info.driver
            # 修改 1: 移除 finally 块中的释放逻辑，交给调用者手动释放
        except Exception as e:
            logger.error(f"获取 WebDriver 失败: {str(e)}")
            raise
        finally:
            # 修改 2: 仅在异常情况下释放临时 driver
            if driver_info and driver_info not in self.pool:
                try:
                    driver_info.driver.quit()
                except:
                    pass
    
    async def release_driver(self, driver: uc.Chrome):
        """手动释放 WebDriver 到连接池"""
        async with self.pool_lock:
            for info in self.pool:
                if info.driver == driver and info.in_use:
                    info.in_use = False
                    info.last_used = time.time()
                    logger.info("WebDriver 已归还到连接池")
                    return
            logger.warning("尝试释放的 WebDriver 不在连接池中，可能为临时实例")
            try:
                driver.quit()
            except:
                pass
    
    async def _replace_driver(self, old_driver_info: DriverInfo):
        """替换过度使用的 WebDriver"""
        try:
            old_driver_info.driver.quit()
        except:
            pass
        try:
            new_driver = await asyncio.get_event_loop().run_in_executor(None, self.create_driver)
            old_driver_info.driver = new_driver
            old_driver_info.usage_count = 0
            old_driver_info.created_at = time.time()
            logger.info("WebDriver 实例替换成功")
        except Exception as e:
            logger.error(f"替换 WebDriver 失败: {str(e)}")
            if old_driver_info in self.pool:
                self.pool.remove(old_driver_info)
    
    async def cleanup_expired_drivers(self):
        """定期清理过期的 WebDriver 实例"""
        while True:
            try:
                await asyncio.sleep(60)
                current_time = time.time()
                async with self.pool_lock:
                    for driver_info in self.pool[:]:
                        if not driver_info.in_use and current_time - driver_info.last_used > self.max_idle_time:
                            logger.info("清理过期的 WebDriver 实例")
                            try:
                                driver_info.driver.quit()
                            except:
                                pass
                            self.pool.remove(driver_info)
                            if len(self.pool) < self.pool_size:
                                try:
                                    new_driver = await asyncio.get_event_loop().run_in_executor(None, self.create_driver)
                                    new_driver_info = DriverInfo(
                                        driver=new_driver,
                                        created_at=time.time(),
                                        last_used=time.time()
                                    )
                                    self.pool.append(new_driver_info)
                                    logger.info("补充新的 WebDriver 实例到连接池")
                                except Exception as e:
                                    logger.error(f"补充 WebDriver 实例失败: {str(e)}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理任务异常: {str(e)}")
    
    async def close_all(self):
        """关闭所有 WebDriver 实例"""
        logger.info("开始关闭所有 WebDriver 实例...")
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        async with self.pool_lock:
            for driver_info in self.pool:
                try:
                    driver_info.driver.quit()
                except Exception as e:
                    logger.error(f"关闭 WebDriver 失败: {str(e)}")
            self.pool.clear()
        logger.info("所有 WebDriver 实例已关闭")
    
    def get_pool_status(self) -> dict:
        """获取连接池状态"""
        available = sum(1 for info in self.pool if not info.in_use)
        in_use = len(self.pool) - available
        return {
            "total": len(self.pool),
            "available": available,
            "in_use": in_use,
            "pool_size": self.pool_size,
            "details": [
                {
                    "in_use": info.in_use,
                    "usage_count": info.usage_count,
                    "created_at": info.created_at,
                    "last_used": info.last_used,
                    "age_seconds": time.time() - info.created_at
                }
                for info in self.pool
            ]
        }

def extract_text_content(html_content: str) -> str:
    """从HTML中提取纯文本内容"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        for script in soup(["script", "style", "meta", "link", "noscript"]):
            script.decompose()
        text = soup.get_text()
        text = re.sub(r'\n+', '\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        return text.strip()
    except Exception as e:
        logger.error(f"文本提取失败: {str(e)}")
        return html_content

def clean_html_content(html_content: str) -> str:
    """清理HTML内容，移除不必要的脚本和样式，但保留结构"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 移除危险的脚本和样式标签
        for script in soup(["script", "noscript"]):
            script.decompose()
            
        # 移除内联事件处理器
        for tag in soup.find_all():
            if tag.attrs:
                # 移除所有 on* 事件属性
                attrs_to_remove = [attr for attr in tag.attrs if attr.startswith('on')]
                for attr in attrs_to_remove:
                    del tag.attrs[attr]
        
        return str(soup)
    except Exception as e:
        logger.error(f"HTML清理失败: {str(e)}")
        return html_content

# 创建全局连接池实例
driver_pool = WebDriverPool(pool_size=1)

@app.on_event("startup")
async def startup_event():
    """应用启动时初始化连接池"""
    logger.info("应用启动，开始初始化 WebDriver 连接池...")
    try:
        await driver_pool.initialize_pool()
        logger.info("WebDriver 连接池初始化完成")
    except Exception as e:
        logger.error(f"连接池初始化失败: {str(e)}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时清理连接池"""
    await driver_pool.close_all()

@app.get("/fetch", response_class=PlainTextResponse)
async def fetch_page_text(url: Optional[str] = None, wait_time: int = 5):
    """获取页面纯文本内容，支持 Cloudflare 等防护绕过"""
    if not url:
        raise HTTPException(status_code=400, detail="URL 参数缺失")
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    logger.info(f"正在访问: {url}, 等待时间: {wait_time}秒")
    
    try:
        async with driver_pool.get_driver() as driver:
            try:
                driver.get(url)
                
                if wait_time > 0:
                    logger.info(f"等待 {wait_time} 秒以确保页面加载...")
                    await asyncio.sleep(wait_time)
                
                # 等待主要内容加载
                try:
                    WebDriverWait(driver, 10).until(
                        EC.any_of(
                            EC.presence_of_element_located((By.TAG_NAME, "body")),
                            EC.presence_of_element_located((By.TAG_NAME, "main")),
                            EC.presence_of_element_located((By.CLASS_NAME, "content"))
                        )
                    )
                except:
                    pass
                
                final_source = driver.page_source
                # 修改 3: 在提取页面源码后立即归还 WebDriver
                await driver_pool.release_driver(driver)
                
                if any(keyword in final_source.lower() for keyword in ['just a moment', 'checking your browser']):
                    raise HTTPException(status_code=403, detail="网站防护验证失败")
                
                text_content = extract_text_content(final_source)
                logger.info(f"成功获取页面内容，文本长度: {len(text_content)}")
                return text_content
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"页面访问错误: {str(e)}")
                raise HTTPException(status_code=500, detail=f"页面访问失败: {str(e)}")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 WebDriver 失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")

@app.get("/fetch-html", response_class=HTMLResponse)
async def fetch_page_html(url: Optional[str] = None, wait_time: int = 5, clean: bool = True):
    """获取页面HTML内容，支持 Cloudflare 等防护绕过
    
    Args:
        url: 目标URL
        wait_time: 页面加载等待时间（秒）
        clean: 是否清理HTML内容（移除脚本等危险元素），默认为True
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL 参数缺失")
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    logger.info(f"正在获取HTML: {url}, 等待时间: {wait_time}秒, 清理模式: {clean}")
    
    try:
        async with driver_pool.get_driver() as driver:
            try:
                driver.get(url)
                
                if wait_time > 0:
                    logger.info(f"等待 {wait_time} 秒以确保页面加载...")
                    await asyncio.sleep(wait_time)
                
                # 等待主要内容加载
                try:
                    WebDriverWait(driver, 10).until(
                        EC.any_of(
                            EC.presence_of_element_located((By.TAG_NAME, "body")),
                            EC.presence_of_element_located((By.TAG_NAME, "main")),
                            EC.presence_of_element_located((By.CLASS_NAME, "content"))
                        )
                    )
                except:
                    pass
                
                final_source = driver.page_source
                # 在提取页面源码后立即归还 WebDriver
                await driver_pool.release_driver(driver)
                
                if any(keyword in final_source.lower() for keyword in ['just a moment', 'checking your browser']):
                    raise HTTPException(status_code=403, detail="网站防护验证失败")
                
                # 根据clean参数决定是否清理HTML
                if clean:
                    html_content = clean_html_content(final_source)
                    logger.info(f"成功获取并清理页面HTML，长度: {len(html_content)}")
                else:
                    html_content = final_source
                    logger.info(f"成功获取原始页面HTML，长度: {len(html_content)}")
                
                return HTMLResponse(content=html_content)
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"页面访问错误: {str(e)}")
                raise HTTPException(status_code=500, detail=f"页面访问失败: {str(e)}")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 WebDriver 失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")

@app.get("/pool/status")
async def get_pool_status():
    """获取连接池状态"""
    return driver_pool.get_pool_status()

@app.get("/health")
async def health_check():
    """健康检查接口"""
    pool_status = driver_pool.get_pool_status()
    return {
        "status": "healthy",
        "pool_total": pool_status["total"],
        "pool_available": pool_status["available"],
        "pool_in_use": pool_status["in_use"]
    }

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
