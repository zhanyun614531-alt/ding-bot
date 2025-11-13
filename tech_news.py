import aiohttp
import asyncio
import feedparser
import json
import time
import hashlib
import urllib3
import ssl
import re
import io
import os
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import logging
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import cidfonts
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import registerFontFamily
import os
from dotenv import load_dotenv
import base64

# 加载环境变量
load_dotenv()

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TechNewsTool")


@dataclass
class TechNewsToolConfig:
    """科技新闻工具配置"""
    doubao_api_key: Optional[str] = None
    doubao_base_url: Optional[str] = None
    enable_ai_summary: bool = True
    total_articles: int = 10
    articles_per_source: int = 8
    request_timeout: int = 15
    delay_between_requests: float = 2.0


@dataclass
class Article:
    """文章数据结构"""
    title: str
    link: str
    source: str
    description: str = ""
    bilingual_summary: Optional[Dict[str, str]] = None
    content: str = ""
    keywords: List[str] = None

    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []


class AsyncTechNewsTool:
    """
    异步科技新闻汇总工具

    这个工具可以从多个权威科技媒体获取最新的科技新闻，
    并使用AI生成中英文双语摘要，帮助用户快速了解前沿科技动态。
    """

    name = "tech_news_aggregator"
    description = """
    从多个权威科技媒体获取最新的科技新闻并生成AI摘要，返回PDF格式的报告。

    参数:
    - enable_ai_summary (bool): 是否启用AI摘要，默认为True
    - total_articles (int): 需要获取的文章总数，默认为10
    - articles_per_source (int): 每个来源获取的文章数量，默认为8
    - sources (list): 指定新闻来源，可选值: ['TechCrunch', 'Wired', '36Kr', 'MIT']，默认为全部

    返回:
    - PDF二进制数据，包含科技新闻标题、链接、来源和AI摘要的格式化报告
    """

    # 类变量，用于存储PDF样式，避免重复创建
    _pdf_styles = None
    _fonts_registered = False

    def __init__(self, config: TechNewsToolConfig):
        """
        初始化科技新闻工具

        Args:
            config: 工具配置
        """
        self.config = config

        # 豆包客户端配置
        self.doubao_client = None
        if config.doubao_api_key and config.doubao_base_url:
            try:
                self.doubao_client = AsyncOpenAI(
                    api_key=config.doubao_api_key,
                    base_url=config.doubao_base_url
                )
                logger.info("豆包异步客户端初始化成功")
            except Exception as e:
                logger.error(f"豆包异步客户端初始化失败: {e}")

        self.model_id = "bot-20250907084333-cbvff"

        # 创建aiohttp会话
        self.session = None

        # 科技关键词定义
        self.tech_keywords = [
            # 人工智能相关
            'AI', 'Artificial Intelligence', 'Machine Learning', 'Deep Learning', 'Neural Network',
            'Large Language Model', 'LLM', 'GPT', 'Generative AI', 'Computer Vision',
            'Natural Language Processing', 'NLP', 'Autonomous', '自动驾驶', '人工智能', '机器学习',

            # 生物医药
            'Biotech', 'Biopharma', 'Gene Editing', 'CRISPR', 'mRNA', 'Vaccine', 'Therapeutics',
            'Precision Medicine', 'Clinical Trial', 'FDA approval', '生物技术', '基因编辑', '疫苗',
            '医药', '临床试验',

            # 机器人与自动化
            'Robotics', 'Robot', 'Automation', 'Industrial Automation', 'Cobot', '无人机',
            'Drone', '机器人', '自动化',

            # 3D打印与先进制造
            '3D Printing', 'Additive Manufacturing', 'Advanced Manufacturing', '3D打印',

            # 能源技术
            'Nuclear', 'Nuclear Energy', 'Fusion', 'Fission', 'Renewable Energy', 'Solar', 'Wind',
            'Battery', 'Energy Storage', '核能', '核聚变', '可再生能源', '电池', '储能',

            # 量子计算
            'Quantum Computing', 'Quantum', 'Qubit', '量子计算', '量子',

            # 太空技术
            'Space', 'Satellite', 'Rocket', 'Spacecraft', '太空', '卫星', '火箭',

            # 其他前沿科技
            'Nanotechnology', 'Biometrics', 'VR', 'AR', 'Virtual Reality', 'Augmented Reality',
            'Internet of Things', 'IoT', '5G', '6G', '半导体', '芯片', '纳米技术', '虚拟现实'
        ]

        # 非科技内容排除词
        self.non_tech_indicators = [
            'pizza', 'oven', 'vacuum', 'gift', 'sexy', 'dating', 'relationship',
            'lice', 'craft', 'spa', 'butt lift', 'cosmetic', 'entertainment',
            'financial', 'stock', 'investment', 'bank', 'loan', 'credit',
            'shopping', 'retail', 'consumer', 'lifestyle', 'travel', 'food'
        ]

        # 中英文摘要系统提示词
        self.bilingual_summary_prompt = """你是一位专业的科技新闻编辑，你的任务是为读者生成简洁、准确、有深度的科技新闻摘要。

请严格遵循以下要求生成摘要：

**语言要求：**
必须同时提供中文和英文两种语言的摘要

**格式要求：**
中文摘要：[2-3句中文摘要]
英文摘要：[2-3句英文摘要]

**内容要求：**
1. 用2-3句话概括新闻的核心内容
2. 突出技术亮点、创新点和行业影响
3. 指出该技术可能的应用场景或市场前景
4. 语言简洁专业，避免营销术语
5. 如果涉及具体数据或融资信息，请准确包含

请严格按照上述格式输出，不要添加任何额外的说明或标记。"""

        logger.info("异步科技新闻工具初始化完成")

    def _register_chinese_fonts(self):
        """注册中文字体 - 专门为Render平台优化"""
        if AsyncTechNewsTool._fonts_registered:
            return

        try:
            # 在Render平台上，我们使用ReportLab内置的CID字体，这是最可靠的方法
            logger.info("使用ReportLab内置CID字体支持中文")

            # 注册内置CID字体
            pdfmetrics.registerFont(cidfonts.UnicodeCIDFont('STSong-Light'))

            # 同时尝试注册常见的CID字体
            cid_fonts = ['STSong-Light', 'STSongStd-Light', 'HeiseiMin-W3', 'HeiseiKakuGo-W5']
            for font_name in cid_fonts:
                try:
                    pdfmetrics.registerFont(cidfonts.UnicodeCIDFont(font_name))
                    logger.info(f"成功注册CID字体: {font_name}")
                except:
                    continue

            AsyncTechNewsTool._fonts_registered = True
            logger.info("中文字体注册完成，使用CID字体")

        except Exception as e:
            logger.error(f"注册中文字体失败: {e}")
            # 即使字体注册失败，我们仍然继续，让ReportLab使用默认字体

    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.request_timeout),
            connector=aiohttp.TCPConnector(ssl=False)  # 禁用SSL验证
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.session:
            await self.session.close()

    async def _make_request(self, url: str, method: str = "GET", headers: Dict = None, data: Any = None) -> str:
        """异步HTTP请求"""
        if not self.session:
            logger.error(f"Session未初始化，无法请求 {url}")
            raise RuntimeError("Session not initialized. Use async context manager.")

        try:
            request_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            if headers:
                request_headers.update(headers)

            logger.info(f"正在请求: {url}")
            async with self.session.request(method, url, headers=request_headers, data=data, ssl=False) as response:
                response.raise_for_status()
                content = await response.text()
                logger.info(f"请求成功: {url}, 状态码: {response.status}")
                return content

        except Exception as e:
            logger.error(f"HTTP请求失败 {url}: {e}")
            raise

    def is_tech_related(self, title: str, description: str = "") -> bool:
        """判断文章是否与前沿科技相关"""
        combined_text = (title + " " + description).lower()

        # 检查是否包含科技关键词
        for keyword in self.tech_keywords:
            if keyword.lower() in combined_text:
                return True

        # 排除明显非科技的内容
        for indicator in self.non_tech_indicators:
            if indicator in combined_text:
                return False

        return False

    async def extract_article_content(self, url: str) -> str:
        """异步从文章URL提取核心内容"""
        try:
            content = await self._make_request(url)

            # 如果返回403错误，尝试使用不同的User-Agent
            if "403" in content or "Forbidden" in content:
                logger.warning(f"网站返回403错误，尝试使用备用方法: {url}")
                # 尝试使用不同的headers
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
                content = await self._make_request(url, headers=headers)

            soup = BeautifulSoup(content, 'html.parser')

            # 移除不需要的标签
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                element.decompose()

            # 尝试多种内容提取策略
            extracted_content = ""
            article_selectors = [
                'article',
                '.article-content',
                '.post-content',
                '.entry-content',
                '.story-content',
                '.content',
                'main',
                '[class*="article"]',
                '[class*="content"]',
                '[class*="post"]'
            ]

            for selector in article_selectors:
                article_element = soup.select_one(selector)
                if article_element:
                    paragraphs = article_element.find_all(['p', 'h1', 'h2', 'h3'])
                    text_content = []
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        if len(text) > 50:
                            text_content.append(text)

                    if text_content:
                        extracted_content = " ".join(text_content[:8])
                        break

            # 策略2: 如果没找到特定标签，提取所有段落
            if not extracted_content or len(extracted_content) < 200:
                all_paragraphs = soup.find_all('p')
                paragraph_texts = []
                for p in all_paragraphs:
                    text = p.get_text(strip=True)
                    if len(text) > 100:
                        paragraph_texts.append(text)

                if paragraph_texts:
                    extracted_content = " ".join(paragraph_texts[:6])

            # 清理内容
            if extracted_content:
                extracted_content = re.sub(r'\s+', ' ', extracted_content)
                if len(extracted_content) > 1500:
                    extracted_content = extracted_content[:1497] + "..."

            return extracted_content if extracted_content else "无法提取文章内容"

        except Exception as e:
            logger.error(f"提取文章内容失败 {url}: {e}")
            return f"提取内容时出错: {str(e)}"

    async def generate_bilingual_summary(self, title: str, content: str) -> Dict[str, str]:
        """异步使用豆包LLM生成中英文双语摘要"""
        if not self.doubao_client:
            return {
                "chinese": "豆包客户端未配置，无法生成AI摘要",
                "english": "Doubao client not configured, unable to generate AI summary"
            }

        if "出错" in content or "无法提取" in content:
            return {
                "chinese": "无法获取文章内容，无法生成摘要",
                "english": "Unable to retrieve article content, cannot generate summary"
            }

        try:
            user_prompt = f"请为以下科技新闻生成中英文双语摘要：\n\n标题：{title}\n\n内容：{content}"

            response = await self.doubao_client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": self.bilingual_summary_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=800,
                temperature=0.3
            )

            full_summary = response.choices[0].message.content.strip()
            return self._parse_bilingual_summary(full_summary)

        except Exception as e:
            logger.error(f"生成AI摘要失败: {e}")
            error_msg = f"AI摘要生成失败: {str(e)}"
            return {
                "chinese": error_msg,
                "english": f"AI summary generation failed: {str(e)}"
            }

    def _parse_bilingual_summary(self, summary_text: str) -> Dict[str, str]:
        """解析AI返回的双语摘要文本，分离中英文部分"""
        result = {
            "chinese": "未能解析中文摘要",
            "english": "Failed to parse English summary"
        }

        try:
            lines = summary_text.split('\n')
            chinese_lines = []
            english_lines = []
            current_section = None

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if '中文摘要' in line or 'Chinese Summary' in line:
                    current_section = 'chinese'
                    continue
                elif '英文摘要' in line or 'English Summary' in line:
                    current_section = 'english'
                    continue

                if current_section == 'chinese':
                    if self._is_mostly_chinese(line):
                        chinese_lines.append(line)
                elif current_section == 'english':
                    if self._is_mostly_english(line):
                        english_lines.append(line)

            # 如果没有明确的章节标记，尝试智能分割
            if not chinese_lines and not english_lines:
                for line in lines:
                    if self._is_mostly_chinese(line):
                        chinese_lines.append(line)
                    elif self._is_mostly_english(line):
                        english_lines.append(line)

            if chinese_lines:
                result["chinese"] = " ".join(chinese_lines)
            if english_lines:
                result["english"] = " ".join(english_lines)

        except Exception as e:
            logger.error(f"解析双语摘要时出错: {e}")
            result["chinese"] = summary_text
            result["english"] = summary_text

        return result

    def _is_mostly_chinese(self, text: str) -> bool:
        """判断文本是否主要是中文"""
        chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
        return chinese_chars / max(len(text), 1) > 0.5

    def _is_mostly_english(self, text: str) -> bool:
        """判断文本是否主要是英文"""
        english_chars = len([c for c in text if c.isalpha() or c.isspace() or c in ',.!?;:-'])
        return english_chars / max(len(text), 1) > 0.7 and not self._is_mostly_chinese(text)

    async def fetch_techcrunch(self, max_articles: int = 15) -> List[Article]:
        """异步获取TechCrunch头条"""
        articles = []
        logger.info("正在尝试从TechCrunch获取新闻...")

        rss_urls = [
            "https://techcrunch.com/feed/",
            "http://feeds.feedburner.com/TechCrunch/",
        ]

        for rss_url in rss_urls:
            try:
                logger.info(f"尝试RSS源: {rss_url}")
                content = await self._make_request(rss_url)

                feed = feedparser.parse(content)
                if feed.entries:
                    logger.info(f"TechCrunch: 成功获取到 {len(feed.entries)} 条新闻")

                    for entry in feed.entries[:max_articles]:
                        if self.is_tech_related(entry.title, entry.get('summary', '')):
                            article = Article(
                                title=entry.title,
                                link=entry.link,
                                source='TechCrunch',
                                description=entry.get('summary', '')
                            )
                            articles.append(article)

                            if len(articles) >= max_articles:
                                break

                    logger.info(f"TechCrunch: 过滤后保留 {len(articles)} 条科技新闻")
                    break

            except Exception as e:
                logger.error(f"TechCrunch RSS源失败: {e}")

        logger.info(f"TechCrunch处理完成，共 {len(articles)} 条科技新闻")
        return articles

    async def fetch_wired(self, max_articles: int = 15) -> List[Article]:
        """异步获取Wired头条"""
        articles = []
        logger.info("正在尝试从Wired获取新闻...")

        url = "https://www.wired.com/feed/rss"
        try:
            content = await self._make_request(url)

            feed = feedparser.parse(content)
            logger.info(f"Wired: 成功获取到 {len(feed.entries)} 条新闻")

            for entry in feed.entries[:max_articles]:
                if self.is_tech_related(entry.title, entry.get('summary', '')):
                    article = Article(
                        title=entry.title,
                        link=entry.link,
                        source='Wired',
                        description=entry.get('summary', '')
                    )
                    articles.append(article)

                    if len(articles) >= max_articles:
                        break

            logger.info(f"Wired: 过滤后保留 {len(articles)} 条科技新闻")

        except Exception as e:
            logger.error(f"获取Wired时出错: {e}")

        logger.info(f"Wired处理完成，共 {len(articles)} 条科技新闻")
        return articles

    async def fetch_36kr(self, max_articles: int = 15) -> List[Article]:
        """异步获取36氪快讯头条"""
        articles = []
        logger.info("正在尝试从36氪获取新闻...")

        # 首先尝试RSS源
        rss_url = "https://36kr.com/feed"
        try:
            content = await self._make_request(rss_url)
            feed = feedparser.parse(content)
            if feed.entries:
                logger.info(f"36氪RSS: 成功获取到 {len(feed.entries)} 条新闻")

                for entry in feed.entries[:max_articles]:
                    if self.is_tech_related(entry.title, entry.get('summary', '')):
                        article = Article(
                            title=entry.title,
                            link=entry.link,
                            source='36Kr',
                            description=entry.get('summary', '')
                        )
                        articles.append(article)

                        if len(articles) >= max_articles:
                            break

                logger.info(f"36氪: 过滤后保留 {len(articles)} 条科技新闻")
                return articles
        except Exception as e:
            logger.error(f"36氪RSS获取失败: {e}")

        # 如果RSS失败，使用网页解析备用方案
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        urls = [
            "https://36kr.com/newsflashes",
            "https://36kr.com/"
        ]

        for url in urls:
            try:
                content = await self._make_request(url, headers=headers)

                soup = BeautifulSoup(content, 'html.parser')

                # 查找新闻标题
                titles = []
                selectors = [
                    '.newsflash-item .newsflash-item-title',
                    '.newsflash-item .title',
                    'a[href*="/newsflashes/"]'
                ]

                for selector in selectors:
                    elements = soup.select(selector)
                    if elements:
                        for element in elements:
                            title = element.get_text(strip=True)
                            if title and len(title) > 5 and title not in titles and self.is_tech_related(title):
                                titles.append(title)
                                if len(titles) >= max_articles:
                                    break
                        if titles:
                            break

                for title in titles:
                    article = Article(
                        title=title,
                        link=f"https://36kr.com/",
                        source='36Kr'
                    )
                    articles.append(article)

                if articles:
                    break

            except Exception as e:
                logger.error(f"获取36氪失败 ({url}): {e}")

        logger.info(f"36氪: 过滤后保留 {len(articles)} 条科技新闻")
        return articles

    async def fetch_mit_tr(self, max_articles: int = 15) -> List[Article]:
        """异步获取MIT Technology Review头条"""
        articles = []
        logger.info("正在尝试从MIT Technology Review获取新闻...")

        # 尝试RSS源
        rss_urls = [
            "https://www.technologyreview.com/feed/",
            "https://www.technologyreview.com/topics/rss/",
            "https://www.technologyreview.com/stories.rss"
        ]

        for rss_url in rss_urls:
            try:
                logger.info(f"尝试MIT RSS源: {rss_url}")
                content = await self._make_request(rss_url)
                feed = feedparser.parse(content)
                if feed.entries:
                    logger.info(f"MIT RSS: 成功获取到 {len(feed.entries)} 条新闻")

                    for entry in feed.entries[:max_articles]:
                        if self.is_tech_related(entry.title, entry.get('summary', '')):
                            article = Article(
                                title=entry.title,
                                link=entry.link,
                                source='MIT Technology Review',
                                description=entry.get('summary', '')
                            )
                            articles.append(article)

                            if len(articles) >= max_articles:
                                break

                    logger.info(f"MIT: 过滤后保留 {len(articles)} 条科技新闻")
                    return articles
            except Exception as e:
                logger.error(f"MIT RSS源失败 ({rss_url}): {e}")

        # 如果所有RSS都失败，使用网页解析
        url = "https://www.technologyreview.com/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }

        try:
            content = await self._make_request(url, headers=headers)

            soup = BeautifulSoup(content, 'html.parser')
            logger.info(f"MIT页面获取成功，开始解析...")

            selectors = [
                'h3 a',
                '.headline a',
                'article h2 a',
                'a[href*="/article/"]',
                'a[href*="/story/"]',
            ]

            seen_titles = set()
            for selector in selectors:
                elements = soup.select(selector)
                if elements:
                    for element in elements:
                        href = element.get('href', '')
                        title = element.get_text(strip=True)

                        if (title and len(title) > 10 and
                                title not in seen_titles and
                                len(title) < 200 and
                                self.is_tech_related(title)):

                            seen_titles.add(title)
                            full_url = href if href.startswith('http') else f"https://www.technologyreview.com{href}"

                            article = Article(
                                title=title[:100],
                                link=full_url,
                                source='MIT Technology Review'
                            )
                            articles.append(article)

                            if len(articles) >= max_articles:
                                break
                    if articles:
                        break

            logger.info(f"MIT Technology Review: 过滤后保留 {len(articles)} 条科技新闻")

        except Exception as e:
            logger.error(f"获取MIT Technology Review时出错: {e}")

        logger.info(f"MIT Technology Review处理完成，共 {len(articles)} 条科技新闻")
        return articles

    def _balance_articles_by_source(self, articles: List[Article], total_count: int) -> List[Article]:
        """按来源平衡选择文章，确保来源多样性"""
        # 如果文章列表为空，直接返回空列表
        if not articles:
            return []

        # 按来源分组
        source_groups = {}
        for article in articles:
            source = article.source
            if source not in source_groups:
                source_groups[source] = []
            source_groups[source].append(article)

        # 计算每个来源应该分配的数量
        source_count = len(source_groups)

        # 修复：防止除零错误
        if source_count == 0:
            return articles[:total_count]  # 如果没有来源分组，直接返回前total_count篇文章

        base_count = max(1, total_count // source_count)

        balanced_articles = []

        # 第一轮：每个来源分配基础数量
        for source, source_articles in source_groups.items():
            balanced_articles.extend(source_articles[:base_count])

        # 第二轮：如果还有剩余名额，按来源文章数量比例分配
        remaining_slots = total_count - len(balanced_articles)
        if remaining_slots > 0:
            sorted_sources = sorted(source_groups.items(),
                                    key=lambda x: len(x[1]),
                                    reverse=True)

            for source, source_articles in sorted_sources:
                if remaining_slots <= 0:
                    break
                already_selected = len([a for a in balanced_articles if a.source == source])
                available = len(source_articles) - already_selected
                if available > 0:
                    balanced_articles.append(source_articles[already_selected])
                    remaining_slots -= 1

        return balanced_articles[:total_count]

    def _create_pdf_styles(self):
        """创建PDF样式 - 使用类变量确保只创建一次"""
        if AsyncTechNewsTool._pdf_styles is not None:
            return AsyncTechNewsTool._pdf_styles

        # 注册中文字体
        self._register_chinese_fonts()

        styles = getSampleStyleSheet()

        # 使用唯一的前缀避免样式名称冲突
        style_prefix = "TechNews_"

        # 获取可用的字体 - 在Render平台上优先使用CID字体
        available_fonts = pdfmetrics.getRegisteredFontNames()

        # 分离中英文字体设置
        chinese_font = None
        english_font = 'Helvetica'  # 英文字体使用Helvetica

        # 优先寻找CID字体用于中文
        for font in available_fonts:
            if any(name in font.lower() for name in ['stsong', 'unicodecid', 'cid']):
                chinese_font = font
                logger.info(f"使用CID字体: {chinese_font}")
                break

        # 如果找不到CID字体，使用默认字体
        if chinese_font is None:
            chinese_font = 'Helvetica'
            logger.warning("未找到CID字体，使用默认字体，中文可能显示为乱码")

        # 自定义样式 - 使用唯一名称
        # 标题样式 - 使用中文字体
        if f"{style_prefix}Title" not in styles:
            styles.add(ParagraphStyle(
                name=f"{style_prefix}Title",
                parent=styles['Heading1'],
                fontName=chinese_font,
                fontSize=18,
                textColor=colors.darkblue,
                spaceAfter=30,
                alignment=TA_CENTER,
                wordWrap='CJK',  # 特别针对CJK文字换行
                leading=22  # 设置行距
            ))

        if f"{style_prefix}Subtitle" not in styles:
            styles.add(ParagraphStyle(
                name=f"{style_prefix}Subtitle",
                parent=styles['Heading2'],
                fontName=chinese_font,
                fontSize=14,
                textColor=colors.darkblue,
                spaceAfter=20,
                alignment=TA_CENTER,
                wordWrap='CJK',
                leading=18
            ))

        # 文章标题 - 智能字体选择
        if f"{style_prefix}ArticleTitle" not in styles:
            styles.add(ParagraphStyle(
                name=f"{style_prefix}ArticleTitle",
                parent=styles['Heading3'],
                fontName=chinese_font,  # 默认使用中文字体
                fontSize=12,
                textColor=colors.darkblue,
                spaceAfter=6,
                alignment=TA_LEFT,
                wordWrap='CJK',
                leading=15,
                splitLongWords=True,  # 允许拆分长单词
                spaceShrinkage=0.0,  # 禁用字间距调整
            ))

        # 英文文章标题 - 专门为英文标题设计
        if f"{style_prefix}EnglishArticleTitle" not in styles:
            styles.add(ParagraphStyle(
                name=f"{style_prefix}EnglishArticleTitle",
                parent=styles['Heading3'],
                fontName=english_font,  # 使用英文字体
                fontSize=12,
                textColor=colors.darkblue,
                spaceAfter=6,
                alignment=TA_LEFT,
                wordWrap=None,  # 英文不使用CJK换行
                leading=15,
                splitLongWords=True,
                spaceShrinkage=0.0,
            ))

        # 来源信息 - 使用中文字体
        if f"{style_prefix}Source" not in styles:
            styles.add(ParagraphStyle(
                name=f"{style_prefix}Source",
                parent=styles['Normal'],
                fontName=chinese_font,
                fontSize=10,
                textColor=colors.gray,
                spaceAfter=6,
                alignment=TA_LEFT,
                wordWrap='CJK',
                leading=12
            ))

        # 链接 - 使用英文字体（等宽字体）
        if f"{style_prefix}Link" not in styles:
            styles.add(ParagraphStyle(
                name=f"{style_prefix}Link",
                parent=styles['Normal'],
                fontName='Courier',  # 链接使用等宽英文字体
                fontSize=9,
                textColor=colors.blue,
                spaceAfter=12,
                alignment=TA_LEFT,
                wordWrap=None,  # 英文不使用CJK换行
                leading=11
            ))

        # 摘要标题 - 使用中文字体
        if f"{style_prefix}SummaryTitle" not in styles:
            styles.add(ParagraphStyle(
                name=f"{style_prefix}SummaryTitle",
                parent=styles['Heading4'],
                fontName=chinese_font,
                fontSize=10,
                textColor=colors.darkgreen,
                spaceAfter=6,
                alignment=TA_LEFT,
                wordWrap='CJK',
                leading=12
            ))

        # 摘要文本 - 根据内容智能选择字体
        if f"{style_prefix}SummaryText" not in styles:
            styles.add(ParagraphStyle(
                name=f"{style_prefix}SummaryText",
                parent=styles['Normal'],
                fontName=chinese_font,  # 默认使用中文字体
                fontSize=9,
                textColor=colors.black,
                spaceAfter=12,
                alignment=TA_JUSTIFY,
                wordWrap='CJK',
                leading=11
            ))

        # 英文摘要文本 - 专门为英文内容设计
        if f"{style_prefix}EnglishSummaryText" not in styles:
            styles.add(ParagraphStyle(
                name=f"{style_prefix}EnglishSummaryText",
                parent=styles['Normal'],
                fontName=english_font,  # 使用英文字体
                fontSize=9,
                textColor=colors.black,
                spaceAfter=12,
                alignment=TA_JUSTIFY,
                wordWrap=None,  # 英文不使用CJK换行
                leading=11,  # 设置行距
                splitLongWords=False,  # 不拆分长单词
                spaceShrinkage=0.0  # 禁用字间距调整
            ))

        # 保存到类变量
        AsyncTechNewsTool._pdf_styles = styles
        return styles

    def _generate_pdf(self, articles: List[Article], source_stats: Dict[str, int]) -> bytes:
        """
        生成PDF报告

        Args:
            articles: 文章列表
            source_stats: 来源统计

        Returns:
            bytes: PDF二进制数据
        """
        try:
            # 创建内存缓冲区
            buffer = io.BytesIO()

            # 创建PDF文档
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=18
            )

            # 获取样式
            styles = self._create_pdf_styles()
            style_prefix = "TechNews_"

            # 构建内容
            content = []

            # 标题
            title = Paragraph("每日科技新闻摘要", styles[f"{style_prefix}Title"])
            content.append(title)

            # 生成日期
            date_str = time.strftime("%Y年%m月%d日")
            subtitle = Paragraph(f"生成日期: {date_str}", styles[f"{style_prefix}Subtitle"])
            content.append(subtitle)

            content.append(Spacer(1, 20))

            # 统计信息
            stats_text = f"本次共获取 {len(articles)} 篇科技新闻，来源分布: "
            stats_text += ", ".join([f"{source}: {count}" for source, count in source_stats.items()])
            stats_para = Paragraph(stats_text, styles[f"{style_prefix}Source"])
            content.append(stats_para)

            content.append(Spacer(1, 30))

            # 添加每篇文章
            for i, article in enumerate(articles, 1):
                # 智能选择标题样式
                # 如果标题主要是英文，使用英文字体样式
                if self._is_mostly_english(article.title):
                    title_style = styles[f"{style_prefix}EnglishArticleTitle"]
                else:
                    title_style = styles[f"{style_prefix}ArticleTitle"]

                # 文章标题
                article_title = Paragraph(f"{i}. {article.title}", title_style)
                content.append(article_title)

                # 来源
                source_para = Paragraph(f"来源: {article.source}", styles[f"{style_prefix}Source"])
                content.append(source_para)

                # 链接
                link_para = Paragraph(f"链接: {article.link}", styles[f"{style_prefix}Link"])
                content.append(link_para)

                # 关键词
                if article.keywords:
                    keywords_text = f"关键词: {', '.join(article.keywords)}"
                    keywords_para = Paragraph(keywords_text, styles[f"{style_prefix}Source"])
                    content.append(keywords_para)

                # AI摘要
                if article.bilingual_summary:
                    # 中文摘要
                    chinese_title = Paragraph("中文摘要:", styles[f"{style_prefix}SummaryTitle"])
                    content.append(chinese_title)

                    chinese_text = article.bilingual_summary.get('chinese', '无中文摘要')
                    chinese_para = Paragraph(chinese_text, styles[f"{style_prefix}SummaryText"])
                    content.append(chinese_para)

                    # 英文摘要 - 使用专门的英文字体样式
                    english_title = Paragraph("English Summary:", styles[f"{style_prefix}SummaryTitle"])
                    content.append(english_title)

                    english_text = article.bilingual_summary.get('english', 'No English summary')
                    english_para = Paragraph(english_text, styles[f"{style_prefix}EnglishSummaryText"])
                    content.append(english_para)

                # 分隔线
                if i < len(articles):
                    content.append(Spacer(1, 20))
                    content.append(Paragraph("_" * 80, styles['Normal']))
                    content.append(Spacer(1, 20))
                else:
                    content.append(Spacer(1, 20))

            # 构建PDF
            doc.build(content)

            # 获取PDF二进制数据
            pdf_data = buffer.getvalue()
            buffer.close()

            logger.info(f"PDF生成成功，大小: {len(pdf_data)} 字节")
            return pdf_data

        except Exception as e:
            logger.error(f"生成PDF失败: {e}")
            raise Exception(f"PDF生成失败: {str(e)}")

    async def execute(self,
                      enable_ai_summary: bool = None,
                      total_articles: int = None,
                      articles_per_source: int = None,
                      sources: List[str] = None) -> Tuple[bool, bytes, Dict[str, Any]]:
        """
        异步执行科技新闻获取任务并返回PDF二进制数据

        Args:
            enable_ai_summary: 是否启用AI摘要
            total_articles: 总文章数量
            articles_per_source: 每个来源获取的文章数量
            sources: 指定新闻来源

        Returns:
            Tuple[bool, bytes, Dict[str, Any]]:
                - 成功状态
                - PDF二进制数据
                - 元数据信息
        """
        # 使用配置值或参数值
        enable_ai_summary = enable_ai_summary if enable_ai_summary is not None else self.config.enable_ai_summary
        total_articles = total_articles if total_articles is not None else self.config.total_articles
        articles_per_source = articles_per_source if articles_per_source is not None else self.config.articles_per_source

        # 默认使用所有来源
        if sources is None:
            sources = ['TechCrunch', 'Wired', '36Kr', 'MIT']

        logger.info(f"开始执行科技新闻获取任务: enable_ai_summary={enable_ai_summary}, "
                    f"total_articles={total_articles}, articles_per_source={articles_per_source}, "
                    f"sources={sources}")

        all_articles = []

        # 从各来源获取文章
        source_fetchers = {
            'TechCrunch': self.fetch_techcrunch,
            'Wired': self.fetch_wired,
            '36Kr': self.fetch_36kr,
            'MIT': self.fetch_mit_tr
        }

        source_results = {}

        # 顺序执行所有来源的获取任务
        for source_name in sources:
            if source_name in source_fetchers:
                logger.info(f"正在从 {source_name} 获取新闻...")
                try:
                    articles = await source_fetchers[source_name](articles_per_source)
                    source_results[source_name] = articles
                    all_articles.extend(articles)
                    logger.info(f"✅ {source_name}: 成功获取 {len(articles)} 篇文章")

                    # 添加延迟避免请求过于频繁
                    await asyncio.sleep(1.0)

                except Exception as e:
                    logger.error(f"❌ {source_name}: 获取失败 - {e}")
                    source_results[source_name] = []

        # 统计各来源结果
        source_stats = {source: len(articles) for source, articles in source_results.items()}
        logger.info(f"各来源获取统计: {source_stats}")
        logger.info(f"总计获取 {len(all_articles)} 篇文章，开始去重...")

        # 基于标题去重
        seen = set()
        unique_articles = []
        for article in all_articles:
            identifier = hashlib.md5(f"{article.title}_{article.source}".encode()).hexdigest()
            if identifier not in seen:
                seen.add(identifier)
                unique_articles.append(article)

        logger.info(f"去重后剩余 {len(unique_articles)} 篇文章")

        # 按来源平衡选择文章
        balanced_articles = self._balance_articles_by_source(unique_articles, total_articles)
        logger.info(f"平衡选择后得到 {len(balanced_articles)} 篇文章")

        # 如果需要AI摘要，则处理每篇文章
        final_articles = []
        if enable_ai_summary and self.doubao_client:
            logger.info("正在使用AI生成双语新闻摘要...")

            # 并发处理文章内容提取和AI摘要生成
            process_tasks = []
            for article in balanced_articles:
                task = asyncio.create_task(self._process_article(article))
                process_tasks.append(task)

            # 限制并发数量，避免过多请求
            for i in range(0, len(process_tasks), 3):  # 每次处理3篇文章
                batch = process_tasks[i:i + 3]
                results = await asyncio.gather(*batch, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"处理文章时出错: {result}")
                    else:
                        final_articles.append(result)

                # 批次之间添加延迟
                if i + 3 < len(process_tasks):
                    await asyncio.sleep(self.config.delay_between_requests)
        else:
            final_articles = balanced_articles

        # 生成PDF
        try:
            pdf_data = self._generate_pdf(final_articles, source_stats)

            # 构建元数据
            metadata = {
                "execution_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "tool_name": self.name,
                "parameters": {
                    "enable_ai_summary": enable_ai_summary,
                    "total_articles": total_articles,
                    "articles_per_source": articles_per_source,
                    "sources": sources
                },
                "summary": {
                    "total_articles": len(final_articles),
                    "source_distribution": source_stats,
                    "has_ai_summary": enable_ai_summary and self.doubao_client is not None
                }
            }

            logger.info(f"科技新闻获取任务完成，共获取 {len(final_articles)} 篇文章，生成PDF大小: {len(pdf_data)} 字节")

            # 关键修复：确保返回的是三个值的元组
            # return (True, pdf_data, metadata)
            return pdf_data

        except Exception as e:
            logger.error(f"任务执行失败: {e}")
            return (False, b"", {"error": str(e)})

    async def _process_article(self, article: Article) -> Article:
        """异步处理单篇文章（内容提取和AI摘要）"""
        logger.info(f"处理文章: {article.source}: {article.title[:50]}...")

        # 提取文章内容
        content = await self.extract_article_content(article.link)
        article.content = content

        # 生成双语AI摘要
        bilingual_summary = await self.generate_bilingual_summary(article.title, content)
        article.bilingual_summary = bilingual_summary

        # 提取关键词
        article.keywords = [kw for kw in self.tech_keywords if kw.lower() in article.title.lower()]

        return article

    def get_tool_schema(self) -> Dict[str, Any]:
        """
        获取工具的模式定义，用于LLM工具调用

        Returns:
            Dict: 工具的模式定义
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "enable_ai_summary": {
                        "type": "boolean",
                        "description": "是否启用AI摘要生成",
                        "default": True
                    },
                    "total_articles": {
                        "type": "integer",
                        "description": "需要获取的文章总数",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 20
                    },
                    "articles_per_source": {
                        "type": "integer",
                        "description": "每个来源获取的文章数量",
                        "default": 8,
                        "minimum": 1,
                        "maximum": 15
                    },
                    "sources": {
                        "type": "array",
                        "description": "指定新闻来源",
                        "items": {
                            "type": "string",
                            "enum": ["TechCrunch", "Wired", "36Kr", "MIT"]
                        },
                        "default": ["TechCrunch", "Wired", "36Kr", "MIT"]
                    }
                },
                "required": []
            },
            "returns": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "任务执行是否成功"
                    },
                    "pdf_data": {
                        "type": "string",
                        "format": "binary",
                        "description": "PDF报告的二进制数据"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "执行元数据信息"
                    }
                }
            }
        }


# 使用示例 - 专门为Render平台设计
async def generate_tech_news_pdf(
        enable_ai_summary: bool = True,
        total_articles: int = 10,
        articles_per_source: int = 8,
        sources: List[str] = None
) -> Tuple[bool, bytes, Dict[str, Any]]:
    """
    生成科技新闻PDF的主函数，适合在Render平台上部署

    Args:
        enable_ai_summary: 是否启用AI摘要
        total_articles: 总文章数量
        articles_per_source: 每个来源文章数量
        sources: 新闻来源列表

    Returns:
        Tuple[bool, bytes, Dict]: 成功状态, PDF二进制数据, 元数据
    """
    try:
        # 创建配置
        config = TechNewsToolConfig(
            doubao_api_key=os.environ.get("ARK_API_KEY"),
            doubao_base_url="https://ark.cn-beijing.volces.com/api/v3/bots",
            enable_ai_summary=enable_ai_summary,
            total_articles=total_articles,
            articles_per_source=articles_per_source,
            request_timeout=30,  # Render平台上增加超时时间
            delay_between_requests=1.0  # 减少延迟以避免超时
        )

        # 使用异步上下文管理器
        async with AsyncTechNewsTool(config) as tech_news_tool:
            result = await tech_news_tool.execute(
                enable_ai_summary=enable_ai_summary,
                total_articles=total_articles,
                articles_per_source=articles_per_source,
                sources=sources
            )

            # 确保只返回三个值
            if len(result) == 3:
                return result
            else:
                # 如果返回了更多值，只取前三个
                logger.warning(f"execute方法返回了{len(result)}个值，但预期是3个")
                return result[0], result[1], result[2] if len(result) > 2 else {}

    except Exception as e:
        logger.error(f"生成PDF过程中发生错误: {e}")
        return False, b"", {"error": str(e)}

# 异步使用示例
async def main():
    """异步主函数示例"""
    try:
        # 直接调用AsyncTechNewsTool
        config = TechNewsToolConfig(
            doubao_api_key=os.environ.get("ARK_API_KEY"),
            doubao_base_url="https://ark.cn-beijing.volces.com/api/v3/bots",
            enable_ai_summary=True,
            total_articles=5,
            articles_per_source=4,
            request_timeout=30
        )

        async with AsyncTechNewsTool(config) as tech_news_tool:
            # 先获取结果，不立即解包
            result = await tech_news_tool.execute(
                enable_ai_summary=True,
                total_articles=5,
                articles_per_source=4,
                sources=['TechCrunch', 'Wired']
            )

            # 调试：确保结果是三元组
            if isinstance(result, tuple) and len(result) == 3:
                success, pdf_data, metadata = result

                if success:
                    print(f"任务执行成功!")
                    print(f"PDF大小: {len(pdf_data)} 字节")
                    print(f"元数据: {json.dumps(metadata, indent=2, ensure_ascii=False)}")

                    # 保存PDF到文件
                    with open("tech_news_report.pdf", "wb") as f:
                        f.write(pdf_data)
                    print("PDF已保存为 tech_news_report.pdf")

                    # 验证PDF数据
                    if isinstance(pdf_data, bytes):
                        print(f"PDF数据类型正确: bytes")
                    else:
                        print(f"PDF数据类型错误: {type(pdf_data)}")
                else:
                    print(f"任务执行失败: {metadata.get('error', '未知错误')}")
            else:
                print(f"错误：execute方法返回了{len(result)}个值，但预期是3个")
                print(f"返回值类型: {type(result)}")

    except Exception as e:
        print(f"执行过程中发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 运行异步主函数
    asyncio.run(main())
