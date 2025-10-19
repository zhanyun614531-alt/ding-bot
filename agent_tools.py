import os
import json
import requests
import hashlib
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
import pytz
from playwright.async_api import async_playwright
import re
import asyncio
import traceback

# 加载环境变量
load_dotenv()


def create_openai_client():
    """安全地创建OpenAI客户端"""
    return OpenAI(
        base_url="https://ark.cn-beijing.volces.com/api/v3/bots",
        api_key=os.environ.get("ARK_API_KEY")
    )


class StockAnalysisPDFAgent:
    """股票分析PDF生成器 - 纯内存操作"""

    def __init__(self):
        # LLM客户端配置 - 使用安全的初始化方式
        self.llm_client = create_openai_client()
        self.model_id = "bot-20250907084333-cbvff"

        # 系统提示词 - AI金融分析师角色
        self.system_prompt = """你是一位顶级的金融分析师，你的任务是为客户撰写一份专业、深入、数据驱动且观点明确的股票研究报告。
        你的分析必须客观、严谨，并结合基本面、技术面和市场情绪进行综合判断。
        
请遵循以下规则进行回答：
1. 在回答任何用户问题前，你必须先在一个<think>标签内进行逐步的深度思考。
2. 思考过程中可以调用联网搜索功能获取实时信息。
3. 思考完毕后，在</think>标签外给出最终答案

请严格遵循以下结构和要求，生成一份完整的美观的HTML格式的股票分析报告：

报告结构与格式要求：

1. 报告摘要 (Report Summary)
   - 关键投资亮点：以要点形式列出3-5个最重要的投资亮点或关注点
   - 投资者画像：指出该股票适合哪类投资者，并说明建议的投资时间周期

2. 深度分析 (In-Depth Analysis)
   2.1 公司与行业分析
     - 商业模式：公司如何创造收入？核心产品、服务和主要客户群体
     - 行业格局与竞争优势：行业驱动因素、市场规模、增长前景、主要竞争对手、护城河分析

   2.2 财务健康状况与业绩
     - 近期业绩：注明最近财报日期，总结业绩超预期/不及预期的关键点
     - 核心财务趋势：过去3-5年收入、净利润和利润率趋势
     - 关键财务比率分析：提供P/S、P/B、PEG、债务权益比等，并与行业比较

   2.3 增长前景与催化剂
     - 增长战略：新产品发布、市场扩张、并购等计划
     - 潜在催化剂：未来6-12个月内可能影响股价的事件

   2.4 技术分析与市场情绪
     - 价格行为与趋势：当前趋势、移动平均线状态
     - 关键价位：支撑位和阻力位分析
     - 成交量分析：近期成交量趋势
     - 市场情绪与持仓：分析师评级分布、机构持仓趋势

   2.5 风险评估
     - 核心业务风险：主要经营风险
     - 宏观与行业风险：经济周期、政策变化等影响
     - 危险信号：需要警惕的负面信号

HTML格式要求：
- 使用专业的金融报告样式
- 包含清晰的章节分隔
- 重要数据加粗突出显示
- 风险提示使用醒目标记
- 适当使用图表和表格展示数据
- 确保响应式设计，适应PDF输出
- 报告需要美观和简洁

重要：直接输出完整的HTML代码，不要包含任何代码块标记（如```html或```）"""

    def clean_html_content(self, html_content):
        """清理HTML内容中的代码块标记和其他不需要的字符"""
        print("🧹 清理HTML内容中的代码块标记...")

        # 移除代码块标记
        cleaned_content = re.sub(r'^```html\s*', '', html_content)
        cleaned_content = re.sub(r'\s*```$', '', cleaned_content)
        cleaned_content = cleaned_content.replace('```html', '').replace('```', '')

        print(f"✅ HTML内容清理完成，长度: {len(cleaned_content)} 字符")
        return cleaned_content

    def get_html_from_llm(self, stock_name_or_code):
        """从LLM获取股票分析HTML报告"""
        print(f"📝 请求LLM生成 {stock_name_or_code} 的股票分析报告...")

        user_prompt = f"请为股票 '{stock_name_or_code}' 生成一份完整的专业股票分析报告。"

        try:
            response = self.llm_client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=15000,
                temperature=0.3
            )
            html_content = response.choices[0].message.content.strip()
            print(f"✅ 生成HTML报告（{len(html_content)} 字符）")

            # 清理HTML内容
            cleaned_html = self.clean_html_content(html_content)
            return cleaned_html

        except Exception as e:
            print(f"❌ LLM调用失败: {str(e)}")
            # 如果是API错误，可能有更详细的错误信息
            if hasattr(e, 'response'):
                print(f"🔧 API响应详情: {e.response}")
            return None

    async def html_to_pdf(self, html_content):
        """
        使用系统Chrome将HTML转换为PDF二进制数据
        """
        print("📄 启动系统Chrome，转换HTML为PDF...")

        try:
            async with async_playwright() as p:
                # 使用系统安装的Chrome
                print("🚀 启动系统Chrome浏览器...")
                browser = await p.chromium.launch(
                    executable_path="/usr/bin/google-chrome-stable",
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--disable-software-rasterizer',
                        '--disable-extensions',
                        '--disable-background-timer-throttling',
                        '--disable-renderer-backgrounding',
                        '--disable-backgrounding-occluded-windows',
                        '--disable-client-side-phishing-detection',
                        '--disable-crash-reporter',
                        '--disable-oopr-debug-crash-dump'
                        '--no-first-run',
                        '--single-process',  # 单进程模式，减少内存使用
                        '--memory-pressure-off',  # 禁用内存压力监控
                        '--no-zygote',
                        '--max-old-space-size=1024'  # 限制Node.js内存使用（如果适用）
                    ]
                )

                print("🌐 创建新页面...")
                page = await browser.new_page()

                # 设置页面尺寸为A4
                await page.set_viewport_size({"width": 1200, "height": 1697})

                print("📝 加载HTML内容...")
                await page.set_content(html_content, wait_until='networkidle')

                # 等待额外时间确保所有资源加载完成
                await asyncio.sleep(2)

                # 生成PDF二进制数据
                print("🖨️ 生成PDF...")
                pdf_options = {
                    "format": 'A4',
                    "print_background": True,
                    "margin": {"top": "0.5in", "right": "0.5in", "bottom": "0.5in", "left": "0.5in"},
                    "display_header_footer": False,
                    "prefer_css_page_size": True
                }

                pdf_data = await page.pdf(**pdf_options)
                await browser.close()

                print(f"✅ PDF二进制数据生成成功，大小: {len(pdf_data)} 字节")
                return pdf_data

        except Exception as e:
            print(f"❌ PDF生成失败: {e}")
            import traceback
            print(f"📋 详细错误信息: {traceback.format_exc()}")
            return None

    async def generate_stock_report(self, stock_name_or_code):
        """生成股票分析报告的主方法（异步版本）"""
        print(f"🎯 开始生成 {stock_name_or_code} 的分析报告...")

        # 获取HTML内容
        html_content = self.get_html_from_llm(stock_name_or_code)
        if html_content:
            print(f"✅ 成功获取HTML内容，长度: {len(html_content)} 字符")
            # 转换为PDF二进制数据
            pdf_binary = await self.html_to_pdf(html_content)
            if pdf_binary:
                print(f"✅ {stock_name_or_code} 分析报告生成成功！PDF大小: {len(pdf_binary)} 字节")
                return pdf_binary
            else:
                print(f"❌ {stock_name_or_code} PDF转换失败")
                return None
        else:
            print(f"❌ 无法获取 {stock_name_or_code} 的HTML内容，可能是LLM API调用失败")
            return None


class GoogleCalendarManager:
    """Google日历管理器 - 支持本地credentials.json认证"""

    def __init__(self):
        # 权限范围 - 包含Tasks API
        self.SCOPES = [
            'https://www.googleapis.com/auth/calendar',
            'https://www.googleapis.com/auth/tasks'
        ]
        self.beijing_tz = pytz.timezone('Asia/Shanghai')  # 北京时区
        self.service = self._authenticate()
        if self.service:
            self.tasks_service = build('tasks', 'v1', credentials=self.service._http.credentials)
        else:
            self.tasks_service = None

    def _authenticate(self):
        """Google日历认证 - 优先使用本地credentials.json"""
        creds = None

        # 方案1: 从本地token.pickle文件加载（开发环境优先）
        if os.path.exists('token.pickle'):
            try:
                with open('token.pickle', 'rb') as token:
                    creds = pickle.load(token)
                print("✅ 从本地token.pickle加载令牌成功")
            except Exception as e:
                print(f"❌ 从token.pickle加载令牌失败: {e}")

        # 方案2: 从环境变量加载令牌（生产环境）
        if not creds:
            token_json = os.environ.get('GOOGLE_TOKEN_JSON')
            if token_json:
                try:
                    token_info = json.loads(token_json)
                    creds = Credentials.from_authorized_user_info(token_info, self.SCOPES)
                    print("✅ 从环境变量加载令牌成功")
                except Exception as e:
                    print(f"❌ 从环境变量加载令牌失败: {e}")

        # 检查令牌有效性
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                print("✅ 令牌刷新成功")
            except Exception as e:
                print(f"❌ 令牌刷新失败: {e}")
                creds = None

        # 如果没有有效令牌，启动OAuth流程（使用本地credentials.json）
        if not creds:
            print("🚀 启动本地OAuth授权流程...")
            try:
                # 优先使用本地的credentials.json文件
                if os.path.exists('credentials.json'):
                    flow = InstalledAppFlow.from_client_secrets_file(
                        'credentials.json', self.SCOPES)
                    creds = flow.run_local_server(port=0)
                    print("✅ 使用credentials.json授权成功")
                else:
                    # 备选方案：从环境变量构建配置
                    credentials_info = self._get_credentials_from_env()
                    flow = InstalledAppFlow.from_client_config(
                        credentials_info, self.SCOPES)
                    creds = flow.run_local_server(port=0)
                    print("✅ 使用环境变量配置授权成功")

                # 保存令牌供后续使用
                with open('token.pickle', 'wb') as token:
                    pickle.dump(creds, token)
                print("✅ OAuth授权成功，令牌已保存到token.pickle")

            except Exception as e:
                print(f"❌ OAuth授权失败: {e}")
                print("💡 请确保：")
                print("   1. 在项目根目录放置credentials.json文件")
                print("   2. 或者在.env文件中配置GOOGLE_CLIENT_ID和GOOGLE_CLIENT_SECRET")
                return None

        return build('calendar', 'v3', credentials=creds)

    def _get_credentials_from_env(self):
        """从环境变量构建credentials字典（备用方案）"""
        credentials_info = {
            "installed": {
                "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
                "project_id": os.environ.get("GOOGLE_PROJECT_ID", ""),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                "redirect_uris": [os.environ.get("GOOGLE_REDIRECT_URIS", "http://localhost")]
            }
        }
        return credentials_info

    # ========== 任务管理功能 ==========

    def get_task_lists(self):
        """获取任务列表"""
        if not self.tasks_service:
            return []
        try:
            task_lists = self.tasks_service.tasklists().list().execute()
            return task_lists.get('items', [])
        except HttpError as error:
            print(f"❌ 获取任务列表失败: {error}")
            return []

    def get_or_create_default_task_list(self):
        """获取或创建默认任务列表"""
        if not self.tasks_service:
            return None

        task_lists = self.get_task_lists()
        if task_lists:
            # 返回第一个任务列表
            return task_lists[0]['id']
        else:
            # 创建新的任务列表
            try:
                task_list = self.tasks_service.tasklists().insert(body={
                    'title': '智能助手任务'
                }).execute()
                return task_list['id']
            except HttpError as error:
                print(f"❌ 创建任务列表失败: {error}")
                return None

    def create_task(self, title, notes="", due_date=None, reminder_minutes=60, priority="medium"):
        """
        创建Google任务
        """
        if not self.tasks_service:
            return {
                "success": False,
                "error": "❌ 任务服务未初始化"
            }

        try:
            task_list_id = self.get_or_create_default_task_list()
            if not task_list_id:
                return {
                    "success": False,
                    "error": "❌ 无法获取任务列表"
                }

            # 优先级映射
            priority_map = {"low": "1", "medium": "3", "high": "5"}

            task_body = {
                'title': title,
                'notes': notes,
                'status': 'needsAction'  # 未完成状态
            }

            # 设置截止日期
            if due_date:
                # 确保使用北京时区
                if due_date.tzinfo is None:
                    due_date = self.beijing_tz.localize(due_date)
                # Google Tasks使用RFC 3339格式
                task_body['due'] = due_date.isoformat()

            # 设置优先级
            task_body['priority'] = priority_map.get(priority, "3")

            task = self.tasks_service.tasks().insert(
                tasklist=task_list_id,
                body=task_body
            ).execute()

            return {
                "success": True,
                "task_id": task['id'],
                "message": f"✅ 任务创建成功: {title}"
            }

        except HttpError as error:
            return {
                "success": False,
                "error": f"❌ 创建任务失败: {error}"
            }

    def query_tasks(self, show_completed=False, max_results=50):
        """
        查询任务
        """
        if not self.tasks_service:
            return {
                "success": False,
                "error": "❌ 任务服务未初始化"
            }

        try:
            task_list_id = self.get_or_create_default_task_list()
            if not task_list_id:
                return {
                    "success": False,
                    "error": "❌ 无法获取任务列表"
                }

            # 构建查询参数
            params = {
                'tasklist': task_list_id,
                'maxResults': max_results
            }

            if not show_completed:
                params['showCompleted'] = False
                params['showHidden'] = False

            tasks_result = self.tasks_service.tasks().list(**params).execute()
            tasks = tasks_result.get('items', [])

            if not tasks:
                return {
                    "success": True,
                    "tasks": [],
                    "message": "📭 没有找到任务"
                }

            formatted_tasks = []
            for task in tasks:
                # 处理截止日期
                due_date = task.get('due')
                if due_date:
                    due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                    due_beijing = due_dt.astimezone(self.beijing_tz)
                    due_display = due_beijing.strftime('%Y-%m-%d %H:%M')
                else:
                    due_display = "无截止日期"

                # 处理优先级
                priority_map = {"1": "low", "3": "medium", "5": "high"}
                priority = priority_map.get(task.get('priority', '3'), 'medium')

                # 处理状态
                status = "completed" if task.get('status') == 'completed' else "needsAction"

                formatted_tasks.append({
                    'id': task['id'],
                    'title': task['title'],
                    'notes': task.get('notes', ''),
                    'due': due_display,
                    'priority': priority,
                    'status': status,
                    'completed': task.get('completed') if status == "completed" else None
                })

            return {
                "success": True,
                "tasks": formatted_tasks,
                "count": len(formatted_tasks),
                "message": f"📋 找到{len(formatted_tasks)}个任务"
            }

        except HttpError as error:
            return {
                "success": False,
                "error": f"❌ 查询任务失败: {error}"
            }

    def update_task_status(self, task_id, status="completed"):
        """
        更新任务状态
        """
        if not self.tasks_service:
            return {
                "success": False,
                "error": "❌ 任务服务未初始化"
            }

        try:
            task_list_id = self.get_or_create_default_task_list()
            if not task_list_id:
                return {
                    "success": False,
                    "error": "❌ 无法获取任务列表"
                }

            # 先获取任务
            task = self.tasks_service.tasks().get(
                tasklist=task_list_id,
                task=task_id
            ).execute()

            # 更新状态
            if status == "completed":
                task['status'] = 'completed'
                task['completed'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            else:
                task['status'] = 'needsAction'
                task.pop('completed', None)  # 移除完成时间

            updated_task = self.tasks_service.tasks().update(
                tasklist=task_list_id,
                task=task_id,
                body=task
            ).execute()

            status_text = "完成" if status == "completed" else "重新打开"
            return {
                "success": True,
                "message": f"✅ 任务已标记为{status_text}"
            }

        except HttpError as error:
            return {
                "success": False,
                "error": f"❌ 更新任务状态失败: {error}"
            }

    def delete_task(self, task_id):
        """删除任务"""
        if not self.tasks_service:
            return {
                "success": False,
                "error": "❌ 任务服务未初始化"
            }

        try:
            task_list_id = self.get_or_create_default_task_list()
            if not task_list_id:
                return {
                    "success": False,
                    "error": "❌ 无法获取任务列表"
                }

            self.tasks_service.tasks().delete(
                tasklist=task_list_id,
                task=task_id
            ).execute()

            return {
                "success": True,
                "message": "🗑️ 任务已成功删除"
            }

        except HttpError as error:
            return {
                "success": False,
                "error": f"❌ 删除任务失败: {error}"
            }

    def delete_task_by_title(self, title_keyword, show_completed=True):
        """根据标题关键词删除任务"""
        try:
            result = self.query_tasks(show_completed=show_completed, max_results=100)
            if not result["success"]:
                return result

            matching_tasks = []
            for task in result["tasks"]:
                if title_keyword.lower() in task['title'].lower():
                    matching_tasks.append(task)

            if not matching_tasks:
                return {
                    "success": False,
                    "error": f"❌ 未找到包含 '{title_keyword}' 的任务"
                }

            # 删除匹配的任务
            deleted_count = 0
            for task in matching_tasks:
                delete_result = self.delete_task(task['id'])
                if delete_result["success"]:
                    deleted_count += 1

            return {
                "success": True,
                "message": f"🗑️ 成功删除 {deleted_count} 个匹配任务",
                "deleted_count": deleted_count
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"❌ 删除任务时出错: {str(e)}"
            }

    def delete_tasks_by_time_range(self, start_date=None, end_date=None, show_completed=True):
        """
        根据时间范围批量删除任务

        Args:
            start_date: 开始日期 (datetime对象或字符串 "YYYY-MM-DD")
            end_date: 结束日期 (datetime对象或字符串 "YYYY-MM-DD")
            show_completed: 是否包含已完成的任务
        """
        if not self.tasks_service:
            return {
                "success": False,
                "error": "❌ 任务服务未初始化"
            }

        try:
            # 解析日期参数
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, "%Y-%m-%d")
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, "%Y-%m-%d")

            # 如果没有指定结束日期，默认为开始日期后30天
            if start_date and not end_date:
                end_date = start_date + timedelta(days=30)

            # 如果没有指定开始日期，默认为今天
            if not start_date:
                start_date = datetime.now(self.beijing_tz)

            # 如果没有指定结束日期，默认为开始日期后30天
            if not end_date:
                end_date = start_date + timedelta(days=30)

            # 确保使用北京时区
            if start_date.tzinfo is None:
                start_date = self.beijing_tz.localize(start_date)
            if end_date.tzinfo is None:
                end_date = self.beijing_tz.localize(end_date)

            # 获取所有任务
            result = self.query_tasks(show_completed=show_completed, max_results=500)
            if not result["success"]:
                return result

            matching_tasks = []
            for task in result["tasks"]:
                # 检查任务是否有截止日期
                if task['due'] != "无截止日期":
                    try:
                        # 解析任务的截止日期
                        task_due = datetime.strptime(task['due'], '%Y-%m-%d %H:%M')
                        task_due = self.beijing_tz.localize(task_due)

                        # 检查任务是否在时间范围内
                        if start_date <= task_due <= end_date:
                            matching_tasks.append(task)
                    except ValueError:
                        # 如果日期解析失败，跳过这个任务
                        continue

            if not matching_tasks:
                start_str = start_date.strftime('%Y-%m-%d')
                end_str = end_date.strftime('%Y-%m-%d')
                return {
                    "success": False,
                    "error": f"❌ 在 {start_str} 到 {end_str} 范围内没有找到任务"
                }

            # 删除匹配的任务
            deleted_count = 0
            for task in matching_tasks:
                delete_result = self.delete_task(task['id'])
                if delete_result["success"]:
                    deleted_count += 1

            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            return {
                "success": True,
                "message": f"🗑️ 成功删除 {deleted_count} 个在 {start_str} 到 {end_str} 范围内的任务",
                "deleted_count": deleted_count
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"❌ 按时间范围删除任务时出错: {str(e)}"
            }

    # ========== 日历事件功能 ==========

    def create_event(self, summary, description="", start_time=None, end_time=None,
                     reminder_minutes=30, priority="medium", status="confirmed"):
        """
        创建日历事件 - 修复时区问题
        """
        if not self.service:
            return {
                "success": False,
                "error": "❌ 日历服务未初始化"
            }

        # 确保使用北京时间
        if not start_time:
            start_time = datetime.now(self.beijing_tz) + timedelta(hours=1)
        if not end_time:
            end_time = start_time + timedelta(hours=1)

        # 如果传入的是naive datetime，转换为北京时区
        if start_time.tzinfo is None:
            start_time = self.beijing_tz.localize(start_time)
        if end_time.tzinfo is None:
            end_time = self.beijing_tz.localize(end_time)

        # 优先级映射
        priority_map = {"low": "5", "medium": "3", "high": "1"}

        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Shanghai',  # 明确指定时区
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Shanghai',  # 明确指定时区
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': reminder_minutes},
                ],
            },
            'extendedProperties': {
                'private': {
                    'priority': priority,
                    'status': status
                }
            }
        }

        try:
            event = self.service.events().insert(calendarId='primary', body=event).execute()
            return {
                "success": True,
                "event_id": event['id'],
                "html_link": event.get('htmlLink', ''),
                "message": f"✅ 日历事件创建成功: {summary} (北京时间)"
            }
        except HttpError as error:
            return {
                "success": False,
                "error": f"❌ 创建日历事件失败: {error}"
            }

    def query_events(self, days=30, max_results=50):
        """
        查询未来一段时间内的日历事件 - 修复时区问题
        """
        if not self.service:
            return {
                "success": False,
                "error": "❌ 日历服务未初始化"
            }

        # 使用北京时区的时间范围
        now_beijing = datetime.now(self.beijing_tz)
        future_beijing = now_beijing + timedelta(days=days)

        # 转换为RFC3339格式（Google Calendar API要求的格式）
        now_rfc3339 = now_beijing.isoformat()
        future_rfc3339 = future_beijing.isoformat()

        try:
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=now_rfc3339,
                timeMax=future_rfc3339,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])

            if not events:
                return {
                    "success": True,
                    "events": [],
                    "message": f"📭 未来{days}天内没有日历事件"
                }

            formatted_events = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                priority = event.get('extendedProperties', {}).get('private', {}).get('priority', 'medium')
                status = event.get('extendedProperties', {}).get('private', {}).get('status', 'confirmed')

                # 转换时间为北京时间显示
                if 'T' in start:  # 这是日期时间，不是全天事件
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    start_beijing = start_dt.astimezone(self.beijing_tz)
                    start = start_beijing.strftime('%Y-%m-%d %H:%M:%S')

                formatted_events.append({
                    'id': event['id'],
                    'summary': event.get('summary', '无标题'),
                    'description': event.get('description', ''),
                    'start': start,
                    'end': end,
                    'priority': priority,
                    'status': status
                })

            return {
                "success": True,
                "events": formatted_events,
                "count": len(formatted_events),
                "message": f"📅 找到{len(formatted_events)}个未来{days}天内的事件 (北京时间)"
            }

        except HttpError as error:
            return {
                "success": False,
                "error": f"❌ 查询日历事件失败: {error}"
            }

    def get_current_time_info(self):
        """获取当前时间信息 - 用于调试时区问题"""
        utc_now = datetime.now(timezone.utc)
        beijing_now = datetime.now(self.beijing_tz)
        server_now = datetime.now()

        return {
            "utc_time": utc_now.strftime('%Y-%m-%d %H:%M:%S %Z'),
            "beijing_time": beijing_now.strftime('%Y-%m-%d %H:%M:%S %Z'),
            "server_time": server_now.strftime('%Y-%m-%d %H:%M:%S'),
            "server_timezone": str(server_now.tzinfo) if server_now.tzinfo else "None (naive)"
        }

    def update_event_status(self, event_id, status="completed"):
        """更新事件状态"""
        if not self.service:
            return {
                "success": False,
                "error": "❌ 日历服务未初始化"
            }

        try:
            # 先获取事件
            event = self.service.events().get(calendarId='primary', eventId=event_id).execute()

            # 更新状态
            if 'extendedProperties' not in event:
                event['extendedProperties'] = {'private': {}}
            elif 'private' not in event['extendedProperties']:
                event['extendedProperties']['private'] = {}

            event['extendedProperties']['private']['status'] = status

            # 如果是完成状态，可以添加完成标记
            if status == "completed":
                event['summary'] = "✅ " + event.get('summary', '')

            updated_event = self.service.events().update(
                calendarId='primary', eventId=event_id, body=event).execute()

            return {
                "success": True,
                "message": f"✅ 事件状态已更新为: {status}"
            }

        except HttpError as error:
            return {
                "success": False,
                "error": f"❌ 更新事件状态失败: {error}"
            }

    def delete_event(self, event_id):
        """删除日历事件"""
        if not self.service:
            return {
                "success": False,
                "error": "❌ 日历服务未初始化"
            }

        try:
            self.service.events().delete(calendarId='primary', eventId=event_id).execute()
            return {
                "success": True,
                "message": "🗑️ 日历事件已成功删除"
            }
        except HttpError as error:
            return {
                "success": False,
                "error": f"❌ 删除日历事件失败: {error}"
            }

    def delete_event_by_summary(self, summary, days=30):
        """根据事件标题删除事件（支持模糊匹配）"""
        try:
            # 先查询匹配的事件
            result = self.query_events(days=days, max_results=100)
            if not result["success"]:
                return result

            matching_events = []
            for event in result["events"]:
                if summary.lower() in event['summary'].lower():
                    matching_events.append(event)

            if not matching_events:
                return {
                    "success": False,
                    "error": f"❌ 未找到包含 '{summary}' 的事件"
                }

            # 删除匹配的事件
            deleted_count = 0
            for event in matching_events:
                delete_result = self.delete_event(event['id'])
                if delete_result["success"]:
                    deleted_count += 1

            return {
                "success": True,
                "message": f"🗑️ 成功删除 {deleted_count} 个匹配事件",
                "deleted_count": deleted_count
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"❌ 删除事件时出错: {str(e)}"
            }

    def delete_events_by_time_range(self, start_date=None, end_date=None):
        """
        根据时间范围批量删除日历事件

        Args:
            start_date: 开始日期 (datetime对象或字符串 "YYYY-MM-DD")
            end_date: 结束日期 (datetime对象或字符串 "YYYY-MM-DD")
        """
        if not self.service:
            return {
                "success": False,
                "error": "❌ 日历服务未初始化"
            }

        try:
            # 解析日期参数
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, "%Y-%m-%d")
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, "%Y-%m-%d")

            # 如果没有指定结束日期，默认为开始日期后30天
            if start_date and not end_date:
                end_date = start_date + timedelta(days=30)

            # 如果没有指定开始日期，默认为今天
            if not start_date:
                start_date = datetime.now(self.beijing_tz)

            # 如果没有指定结束日期，默认为开始日期后30天
            if not end_date:
                end_date = start_date + timedelta(days=30)

            # 确保使用北京时区
            if start_date.tzinfo is None:
                start_date = self.beijing_tz.localize(start_date)
            if end_date.tzinfo is None:
                end_date = self.beijing_tz.localize(end_date)

            # 转换为RFC3339格式
            start_rfc3339 = start_date.isoformat()
            end_rfc3339 = end_date.isoformat()

            # 查询时间范围内的事件
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_rfc3339,
                timeMax=end_rfc3339,
                maxResults=500,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])

            if not events:
                start_str = start_date.strftime('%Y-%m-%d')
                end_str = end_date.strftime('%Y-%m-%d')
                return {
                    "success": False,
                    "error": f"❌ 在 {start_str} 到 {end_str} 范围内没有找到日历事件"
                }

            # 删除匹配的事件
            deleted_count = 0
            for event in events:
                try:
                    self.service.events().delete(
                        calendarId='primary',
                        eventId=event['id']
                    ).execute()
                    deleted_count += 1
                except HttpError as error:
                    print(f"❌ 删除事件 {event['id']} 失败: {error}")
                    continue

            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            return {
                "success": True,
                "message": f"🗑️ 成功删除 {deleted_count} 个在 {start_str} 到 {end_str} 范围内的日历事件",
                "deleted_count": deleted_count
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"❌ 按时间范围删除日历事件时出错: {str(e)}"
            }

class KuaiDi100:
    def __init__(self):
        self.key = os.environ.get("KUAIDI100_APP_KEY")
        self.customer = os.environ.get("KUAIDI100_CUSTOMER")
        self.url = 'https://poll.kuaidi100.com/poll/query.do'  # 请求地址

    def identify_company(self, num: str) -> Optional[str]:
        """
        自动识别快递公司编码

        :param num: 快递单号
        :return: 快递公司编码，如无法识别则返回None
        """
        try:
            url = "https://poll.kuaidi100.com/autonumber/auto"
            params = {
                "num": num,
                "key": self.key
            }

            response = requests.get(url, params=params)
            result = response.json()

            if result.get("status") == "200" and result.get("auto"):
                # 返回最可能的快递公司编码
                return result["auto"][0]["comCode"]
            return None
        except Exception as e:
            print(f"识别快递公司失败: {str(e)}")
            return None

    def kuaidi_track(self, com, num, phone=None, ship_from=None, ship_to=None):
        """
        物流轨迹实时查询
        :param com: 查询的快递公司的编码，一律用小写字母
        :param num: 查询的快递单号，单号的最大长度是32个字符
        :param phone: 收件人或寄件人的手机号或固话（也可以填写后四位，如果是固话，请不要上传分机号）
        :param ship_from: 出发地城市，省-市-区，非必填，填了有助于提升签收状态的判断的准确率，请尽量提供
        :param ship_to: 目的地城市，省-市-区，非必填，填了有助于提升签收状态的判断的准确率，且到达目的地后会加大监控频率，请尽量提供
        :return: requests.Response.text
        """
        param = {
            'com': com,
            'num': num,
            # 'phone': phone,
            # 'from': ship_from,
            # 'to': ship_to,
            'resultv2': '1',  # 添加此字段表示开通行政区域解析功能。0：关闭（默认），1：开通行政区域解析功能，2：开通行政解析功能并且返回出发、目的及当前城市信息
            'show': '0',  # 返回数据格式。0：json（默认），1：xml，2：html，3：text
            'order': 'desc'  # 返回结果排序方式。desc：降序（默认），asc：升序
        }
        param_str = json.dumps(param)  # 转json字符串

        # 签名加密， 用于验证身份， 按param + key + customer 的顺序进行MD5加密（注意加密后字符串要转大写）， 不需要“+”号
        temp_sign = param_str + self.key + self.customer
        md = hashlib.md5()
        md.update(temp_sign.encode())
        sign = md.hexdigest().upper()
        request_data = {'customer': self.customer, 'param': param_str, 'sign': sign}
        result = requests.post(self.url, request_data).text  # 发送请求
        return self.format_logistics_info(result)

    def format_logistics_info(self, json_str):
        """
        将快递100返回的JSON数据格式化为指定的物流信息字符串

        参数:
            json_str: 快递100返回的JSON格式字符串

        返回:
            格式化后的物流信息字符串
        """
        # 解析JSON数据
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return "JSON数据解析错误"

        # 提取基础信息
        waybill_number = data.get("nu", "未知单号")
        company = data.get("com", "未知快递公司")
        data_raw = data.get("data", [])

        # 获取当前状态
        current_status = data_raw[0].get("status",
                                         "未知状态") if data_raw else "无物流信息"

        # 整理物流节点信息
        logistics_nodes = []
        for node in data_raw:
            time = node.get("time", "未知时间")
            area_name = node.get("areaName", "未知地点")
            status_desc = node.get("context", "无描述")
            # 简化状态描述，移除冗余信息
            simplified_desc = status_desc.split("，")[0].replace("[深圳市]",
                                                                "").strip()
            logistics_nodes.append({
                "time": time,
                "location": area_name,
                "status": simplified_desc
            })

        # 构建输出字符串
        result = []
        result.append(f"快递单号：{waybill_number}")
        result.append(f"快递公司：{company}")
        result.append(f"当前状态：{current_status}")
        result.append("\n物流轨迹：")

        for i, node in enumerate(logistics_nodes, 1):
            result.append(
                f"{i}. 时间：{node['time']} | 地点：{node['location']} | 状态：{node['status']}")

        return "\n".join(result)

class DeepseekAgent:
    """智能助手Agent - 集成股票分析功能"""

    def __init__(self):
        # 使用安全的客户端初始化方式
        self.client = create_openai_client()
        self.model_id = "bot-20250907084333-cbvff"

        # 初始化Google日历管理器
        self.calendar_manager = GoogleCalendarManager()

        # 初始化股票分析代理
        self.stock_agent = StockAnalysisPDFAgent()

        # 初始化快递查询
        self.kuaidi = KuaiDi100()

        # 更新系统提示词 - 支持多个任务
        self.system_prompt = """你是一个智能助手，具备工具调用能力。当用户请求涉及日历、任务、邮件、股票分析和快递查询时，你需要返回JSON格式的工具调用。

重要更新：现在支持一次处理多个任务！当用户输入包含多个请求时，你需要返回一个JSON数组，包含多个工具调用。

可用工具：
【日历事件功能】
1. 创建日历事件：{"action": "create_event", "parameters": {"summary": "事件标题", "description": "事件描述", "start_time": "开始时间(YYYY-MM-DD HH:MM)", "end_time": "结束时间(YYYY-MM-DD HH:MM)", "reminder_minutes": 30, "priority": "medium"}}
2. 查询日历事件：{"action": "query_events", "parameters": {"days": 30, "max_results": 20}}
3. 更新事件状态：{"action": "update_event_status", "parameters": {"event_id": "事件ID", "status": "completed"}}
4. 删除日历事件：{"action": "delete_event", "parameters": {"event_id": "事件ID"}}
5. 按标题删除事件：{"action": "delete_event_by_summary", "parameters": {"summary": "事件标题关键词", "days": 30}}
6. 按时间范围删除事件：{"action": "delete_events_by_time_range", "parameters": {"start_date": "开始日期(YYYY-MM-DD)", "end_date": "结束日期(YYYY-MM-DD)"}}

【任务管理功能】
7. 创建任务：{"action": "create_task", "parameters": {"title": "任务标题", "notes": "任务描述", "due_date": "截止时间(YYYY-MM-DD HH:MM)", "reminder_minutes": 60, "priority": "medium"}}
8. 查询任务：{"action": "query_tasks", "parameters": {"show_completed": false, "max_results": 20}}
9. 更新任务状态：{"action": "update_task_status", "parameters": {"task_id": "任务ID", "status": "completed"}}
10. 删除任务：{"action": "delete_task", "parameters": {"task_id": "任务ID"}}
11. 按标题删除任务：{"action": "delete_task_by_title", "parameters": {"title_keyword": "任务标题关键词"}}
12. 按时间范围删除任务：{"action": "delete_tasks_by_time_range", "parameters": {"start_date": "开始日期(YYYY-MM-DD)", "end_date": "结束日期(YYYY-MM-DD)", "show_completed": true}}

【股票分析功能】
13. 生成股票分析报告：{"action": "generate_stock_report", "parameters": {"stock_name": "股票名称或代码"}}

【其他功能】
14. 发送邮件：{"action": "send_email", "parameters": {"to": "收件邮箱", "subject": "邮件主题", "body": "邮件内容"}}
15. 快递查询：{"action": "kuaidi_query", "parameters": {"num": "快递单号"}}

重要规则：
1. 当需要调用工具时，必须返回 ```json 和 ``` 包裹的JSON格式
2. 支持单个工具调用（JSON对象）和多个工具调用（JSON数组）
3. 不需要工具时，直接用自然语言回答
4. JSON格式必须严格符合上面的示例
5. 时间格式：YYYY-MM-DD HH:MM (24小时制)，日期格式：YYYY-MM-DD
6. 优先级：low(低), medium(中), high(高)
7. 股票分析功能会返回PDF二进制数据，用于后续上传或其他操作

示例：
用户：生成腾讯控股的股票分析报告
AI：```json
{"action": "generate_stock_report", "parameters": {"stock_name": "腾讯控股"}}
```
用户：删除10月份的所有任务，并查看我的日历事件
AI：```json
[
{"action": "delete_tasks_by_time_range", "parameters": {"start_date": "2025-10-01", "end_date": "2025-10-31"}},
{"action": "query_events", "parameters": {"days": 7, "max_results": 10}}
]
```
用户：创建明天下午2点的会议，并生成茅台股票报告
AI：```json
[
  {"action": "create_event", "parameters": {"summary": "团队会议", "description": "讨论项目进度", "start_time": "2025-10-08 14:00", "end_time": "2025-10-08 15:00"}},
  {"action": "generate_stock_report", "parameters": {"stock_name": "贵州茅台"}}
]
```
用户：查询快递单号为SF1234567890的物流信息
AI：```json
{"action": "kuaidi_query", "parameters": {"num": "快递单号"}}
```
"""

    def send_email(self, to, subject, body):
        """发送邮件 - 使用 Brevo API"""
        if not all([to, subject, body]):
            return "收件人、主题或正文不能为空"

        brevo_api_key = os.environ.get("BREVO_API_KEY")
        sender_email = os.environ.get("BREVO_SENDER_EMAIL")
        sender_name = os.environ.get("BREVO_SENDER_NAME", "智能助手")

        if not brevo_api_key:
            return "邮件服务未配置"

        try:
            url = "https://api.brevo.com/v3/smtp/email"

            payload = {
                "sender": {
                    "name": sender_name,
                    "email": sender_email
                },
                "to": [{"email": to}],
                "subject": subject,
                "htmlContent": f"""
                <div style="font-family: Arial, sans-serif; line-height: 1.6;">
                    <h2>{subject}</h2>
                    <div style="white-space: pre-line; padding: 20px; background: #f9f9f9; border-radius: 5px;">
                        {body}
                    </div>
                    <p style="color: #999; font-size: 12px; margin-top: 20px;">
                        此邮件由智能助手自动发送
                    </p>
                </div>
                """,
                "textContent": body
            }

            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "api-key": brevo_api_key
            }

            response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code == 201:
                return f"📧 邮件发送成功！已发送至：{to}"
            else:
                error_data = response.json()
                return f"❌ 邮件发送失败：{error_data.get('message', 'Unknown error')}"

        except Exception as e:
            return f"❌ 邮件发送异常：{str(e)}"


    # ========== 股票分析功能 ==========

    async def generate_stock_report(self, stock_name):
        """
        生成股票分析报告（异步版本）

        参数:
        - stock_name: 股票名称或代码

        返回:
        - PDF二进制数据，如果失败则返回None
        """
        print(f"📈 开始生成股票分析报告: {stock_name}")

        try:
            pdf_binary = await self.stock_agent.generate_stock_report(stock_name)
            if pdf_binary:
                print(f"✅ 股票分析报告生成成功，大小: {len(pdf_binary)} 字节")
                # 返回PDF二进制数据，用于后续上传或其他操作
                return pdf_binary
            else:
                print("❌ 股票分析报告生成失败")
                return None

        except Exception as e:
            print(f"❌ 生成股票分析报告时出错: {e}")
            return None


    # ========== Google日历和任务相关方法 ==========

    def create_task(self, title, notes="", due_date=None, reminder_minutes=60, priority="medium"):
        """创建Google任务"""
        try:
            print(f"📝 开始创建任务: {title}")

            # 解析时间字符串
            due_dt = None
            if due_date:
                print(f"⏰ 解析截止时间: {due_date}")
                due_dt = datetime.strptime(due_date, "%Y-%m-%d %H:%M")
                print(f"✅ 时间解析成功: {due_dt}")

            result = self.calendar_manager.create_task(
                title=title,
                notes=notes,
                due_date=due_dt,
                reminder_minutes=reminder_minutes,
                priority=priority
            )

            if result.get("success"):
                print(f"✅ 任务创建成功: {title}")
                return result.get("message", f"✅ 任务 '{title}' 创建成功")
            else:
                error_msg = result.get("error", "创建任务失败")
                print(f"❌ 任务创建失败: {error_msg}")
                return f"❌ {error_msg}"

        except Exception as e:
            error_msg = f"❌ 创建任务时出错: {str(e)}"
            print(error_msg)
            return error_msg


    def query_tasks(self, show_completed=False, max_results=20):
        """查询任务"""
        try:
            print(f"🔍 查询任务: show_completed={show_completed}")

            result = self.calendar_manager.query_tasks(
                show_completed=show_completed,
                max_results=max_results
            )

            if not result["success"]:
                error_msg = result.get("error", "查询任务失败")
                print(f"❌ 查询失败: {error_msg}")
                return f"❌ {error_msg}"

            if not result["tasks"]:
                print("📭 没有找到任务")
                return result["message"]

            # 格式化输出任务列表
            status_text = "所有" if show_completed else "待办"
            tasks_text = f"📋 {status_text}任务列表 ({result['count']}个):\n\n"

            for i, task in enumerate(result["tasks"], 1):
                status_emoji = "✅" if task['status'] == "completed" else "⏳"
                priority_emoji = {"low": "⚪", "medium": "🟡", "high": "🔴"}.get(task['priority'], '🟡')

                tasks_text += f"{i}. {status_emoji}{priority_emoji} {task['title']}\n"
                tasks_text += f"   截止: {task['due']}\n"
                if task['notes']:
                    tasks_text += f"   描述: {task['notes'][:50]}...\n"
                tasks_text += f"   状态: {task['status']} | 优先级: {task['priority']}\n"
                tasks_text += f"   ID: {task['id'][:8]}...\n\n"

            print(f"✅ 找到 {len(result['tasks'])} 个任务")
            return tasks_text

        except Exception as e:
            error_msg = f"❌ 查询任务时出错: {str(e)}"
            print(error_msg)
            return error_msg


    def update_task_status(self, task_id, status="completed"):
        """更新任务状态"""
        try:
            result = self.calendar_manager.update_task_status(task_id, status)
            return result.get("message", result.get("error", "状态更新完成"))
        except Exception as e:
            return f"❌ 更新任务状态时出错: {str(e)}"


    def delete_task(self, task_id):
        """删除任务（通过任务ID）"""
        try:
            result = self.calendar_manager.delete_task(task_id)
            return result.get("message", result.get("error", "删除完成"))
        except Exception as e:
            return f"❌ 删除任务时出错: {str(e)}"


    def delete_task_by_title(self, title_keyword):
        """根据标题删除任务"""
        try:
            result = self.calendar_manager.delete_task_by_title(title_keyword)
            return result.get("message", result.get("error", "删除完成"))
        except Exception as e:
            return f"❌ 按标题删除任务时出错: {str(e)}"


    def delete_tasks_by_time_range(self, start_date=None, end_date=None, show_completed=True):
        """按时间范围批量删除任务"""
        try:
            print(f"🗑️ 按时间范围删除任务: {start_date} 到 {end_date}")

            result = self.calendar_manager.delete_tasks_by_time_range(
                start_date=start_date,
                end_date=end_date,
                show_completed=show_completed
            )

            if result.get("success"):
                print(f"✅ 时间范围删除任务成功")
                return result.get("message", "✅ 时间范围删除任务完成")
            else:
                error_msg = result.get("error", "时间范围删除任务失败")
                print(f"❌ 时间范围删除任务失败: {error_msg}")
                return f"❌ {error_msg}"

        except Exception as e:
            error_msg = f"❌ 按时间范围删除任务时出错: {str(e)}"
            print(error_msg)
            return error_msg


    def create_event(self, summary, description="", start_time=None, end_time=None,
                     reminder_minutes=30, priority="medium"):
        """创建Google日历事件"""
        try:
            print(f"📅 开始创建日历事件: {summary}")

            # 解析时间字符串
            start_dt = None
            end_dt = None

            if start_time:
                start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
            if end_time:
                end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")

            result = self.calendar_manager.create_event(
                summary=summary,
                description=description,
                start_time=start_dt,
                end_time=end_dt,
                reminder_minutes=reminder_minutes,
                priority=priority
            )

            if result.get("success"):
                print(f"✅ 日历事件创建成功: {summary}")
                return result.get("message", f"✅ 日历事件 '{summary}' 创建成功")
            else:
                error_msg = result.get("error", "创建日历事件失败")
                print(f"❌ 日历事件创建失败: {error_msg}")
                return f"❌ {error_msg}"

        except Exception as e:
            error_msg = f"❌ 创建日历事件时出错: {str(e)}"
            print(error_msg)
            return error_msg


    def query_events(self, days=30, max_results=20):
        """查询日历事件"""
        try:
            result = self.calendar_manager.query_events(days=days, max_results=max_results)

            if not result["success"]:
                return result["error"]

            if not result["events"]:
                return result["message"]

            return result["message"]

        except Exception as e:
            return f"❌ 查询日历事件时出错: {str(e)}"


    def update_event_status(self, event_id, status="completed"):
        """更新事件状态"""
        try:
            result = self.calendar_manager.update_event_status(event_id, status)
            return result.get("message", result.get("error", "状态更新完成"))
        except Exception as e:
            return f"❌ 更新事件状态时出错: {str(e)}"


    def delete_event(self, event_id):
        """删除日历事件"""
        try:
            result = self.calendar_manager.delete_event(event_id)
            return result.get("message", result.get("error", "删除完成"))
        except Exception as e:
            return f"❌ 删除日历事件时出错: {str(e)}"


    def delete_event_by_summary(self, summary, days=30):
        """根据标题删除日历事件"""
        try:
            result = self.calendar_manager.delete_event_by_summary(summary, days)
            return result.get("message", result.get("error", "删除完成"))
        except Exception as e:
            return f"❌ 按标题删除事件时出错: {str(e)}"


    def delete_events_by_time_range(self, start_date=None, end_date=None):
        """按时间范围批量删除日历事件"""
        try:
            print(f"🗑️ 按时间范围删除日历事件: {start_date} 到 {end_date}")

            result = self.calendar_manager.delete_events_by_time_range(
                start_date=start_date,
                end_date=end_date
            )

            if result.get("success"):
                print(f"✅ 时间范围删除日历事件成功")
                return result.get("message", "✅ 时间范围删除日历事件完成")
            else:
                error_msg = result.get("error", "时间范围删除日历事件失败")
                print(f"❌ 时间范围删除日历事件失败: {error_msg}")
                return f"❌ {error_msg}"

        except Exception as e:
            error_msg = f"❌ 按时间范围删除日历事件时出错: {str(e)}"
            print(error_msg)
            return error_msg


    def extract_tool_calls(self, llm_response):
        """从LLM响应中提取工具调用指令 - 支持多个工具调用"""
        print(f"🔍 解析LLM响应: {llm_response}")

        if "```json" in llm_response and "```" in llm_response:
            try:
                start = llm_response.find("```json") + 7
                end = llm_response.find("```", start)
                json_str = llm_response[start:end].strip()
                print(f"📦 提取到JSON代码块: {json_str}")

                # 尝试解析为JSON
                parsed_data = json.loads(json_str)

                # 检查是单个工具调用还是多个工具调用
                if isinstance(parsed_data, dict):
                    # 单个工具调用
                    if "action" in parsed_data and "parameters" in parsed_data:
                        print(f"✅ 成功解析单个工具调用: {parsed_data['action']}")
                        return [parsed_data]
                    else:
                        print("❌ 单个工具调用格式不正确")
                        return None
                elif isinstance(parsed_data, list):
                    # 多个工具调用
                    valid_tools = []
                    for tool_data in parsed_data:
                        if isinstance(tool_data, dict) and "action" in tool_data and "parameters" in tool_data:
                            valid_tools.append(tool_data)
                            print(f"✅ 成功解析工具调用: {tool_data['action']}")
                        else:
                            print(f"❌ 工具调用格式不正确: {tool_data}")

                    if valid_tools:
                        print(f"✅ 成功解析 {len(valid_tools)} 个工具调用")
                        return valid_tools
                    else:
                        print("❌ 没有有效的工具调用")
                        return None
                else:
                    print("❌ JSON格式不正确")
                    return None

            except json.JSONDecodeError as e:
                print(f"❌ JSON解析失败: {e}")
                return None
            except Exception as e:
                print(f"❌ 提取工具调用失败: {e}")
                return None

        print("❌ 未找到有效的工具调用")
        return None


    async def call_tool(self, action, parameters):
        """统一工具调用入口 - 异步版本"""
        print(f"🛠️ 调用工具: {action}")
        print(f"📋 工具参数: {parameters}")

        try:
            if action == "create_task":
                return self.create_task(
                    title=parameters.get("title", ""),
                    notes=parameters.get("notes", ""),
                    due_date=parameters.get("due_date"),
                    reminder_minutes=parameters.get("reminder_minutes", 60),
                    priority=parameters.get("priority", "medium")
                )
            elif action == "query_tasks":
                return self.query_tasks(
                    show_completed=parameters.get("show_completed", False),
                    max_results=parameters.get("max_results", 20)
                )
            elif action == "update_task_status":
                return self.update_task_status(
                    task_id=parameters.get("task_id", ""),
                    status=parameters.get("status", "completed")
                )
            elif action == "delete_task":
                return self.delete_task(
                    task_id=parameters.get("task_id", "")
                )
            elif action == "delete_task_by_title":
                return self.delete_task_by_title(
                    title_keyword=parameters.get("title_keyword", "")
                )
            elif action == "delete_tasks_by_time_range":
                return self.delete_tasks_by_time_range(
                    start_date=parameters.get("start_date"),
                    end_date=parameters.get("end_date"),
                    show_completed=parameters.get("show_completed", True)
                )
            elif action == "create_event":
                return self.create_event(
                    summary=parameters.get("summary", ""),
                    description=parameters.get("description", ""),
                    start_time=parameters.get("start_time"),
                    end_time=parameters.get("end_time"),
                    reminder_minutes=parameters.get("reminder_minutes", 30),
                    priority=parameters.get("priority", "medium")
                )
            elif action == "query_events":
                return self.query_events(
                    days=parameters.get("days", 30),
                    max_results=parameters.get("max_results", 20)
                )
            elif action == "update_event_status":
                return self.update_event_status(
                    event_id=parameters.get("event_id", ""),
                    status=parameters.get("status", "completed")
                )
            elif action == "delete_event":
                return self.delete_event(
                    event_id=parameters.get("event_id", "")
                )
            elif action == "delete_event_by_summary":
                return self.delete_event_by_summary(
                    summary=parameters.get("summary", ""),
                    days=parameters.get("days", 30)
                )
            elif action == "delete_events_by_time_range":
                return self.delete_events_by_time_range(
                    start_date=parameters.get("start_date"),
                    end_date=parameters.get("end_date")
                )
            elif action == "generate_stock_report":
                # 股票分析工具返回PDF二进制数据
                pdf_binary = await self.generate_stock_report(parameters.get("stock_name", ""))
                if pdf_binary:
                    return {
                        "success": True,
                        "pdf_binary": pdf_binary,
                        "message": f"✅ 股票分析报告生成成功，PDF大小: {len(pdf_binary)} 字节",
                        "stock_name": parameters.get("stock_name", "")
                    }
                else:
                    return {
                        "success": False,
                        "error": "❌ 股票分析报告生成失败"
                    }
            elif action == "send_email":
                return self.send_email(
                    parameters.get("to", ""),
                    parameters.get("subject", ""),
                    parameters.get("body", "")
                )
            elif action == "kuaidi_query":
                num = parameters.get("num", "")
                # phone = parameters.get("phone", None)

                # 先识别快递公司
                # com = self.kuaidi.identify_company(num)
                com = None

                # 查询物流信息
                logistics_info = self.kuaidi.kuaidi_track(com, num)
                return logistics_info
            else:
                result = f"未知工具：{action}"

            print(f"✅ 工具执行结果: {result}")
            return result

        except Exception as e:
            error_msg = f"❌ 执行工具 {action} 时出错: {str(e)}"
            print(error_msg)
            return error_msg


    async def process_request(self, user_input):
        """处理用户请求（异步版本）- 支持多个工具调用"""
        print(f"👤 用户输入: {user_input}")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input}
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                stream=False
            )

            llm_response = response.choices[0].message.content.strip()
            print(f"🤖 LLM原始响应: {llm_response}")

            # 检查工具调用 - 支持多个工具调用
            tool_calls = self.extract_tool_calls(llm_response)
            if tool_calls:
                print(f"🔧 检测到 {len(tool_calls)} 个工具调用")

                results = []
                stock_pdf_result = None

                # 按顺序执行所有工具调用
                for i, tool_data in enumerate(tool_calls, 1):
                    print(f"🔄 执行第 {i}/{len(tool_calls)} 个工具: {tool_data['action']}")

                    tool_result = await self.call_tool(tool_data["action"], tool_data["parameters"])

                    # 特殊处理股票分析工具，返回PDF二进制数据
                    if tool_data["action"] == "generate_stock_report" and isinstance(tool_result, dict) and tool_result.get(
                            "success"):
                        stock_pdf_result = {
                            "type": "stock_pdf",
                            "success": True,
                            "pdf_binary": tool_result.get("pdf_binary"),
                            "message": tool_result.get("message"),
                            "stock_name": tool_result.get("stock_name")
                        }
                        results.append(stock_pdf_result["message"])
                    else:
                        results.append(str(tool_result))

                    # 添加工具间的延迟，避免API限制
                    if i < len(tool_calls):
                        await asyncio.sleep(1)

                # 如果有股票PDF结果，优先返回
                if stock_pdf_result:
                    return stock_pdf_result
                else:
                    # 合并所有工具执行结果
                    combined_result = "\n\n".join([f"任务 {i + 1}: {result}" for i, result in enumerate(results)])
                    return {
                        "type": "text",
                        "content": f"✅ 所有任务执行完成:\n\n{combined_result}",
                        "success": True
                    }
            else:
                print("💬 无工具调用，直接返回LLM响应")
                return {
                    "type": "text",
                    "content": llm_response,
                    "success": True
                }

        except Exception as e:
            error_msg = f"处理请求时出错：{str(e)}"
            print(f"❌ {error_msg}")
            return {
                "type": "text",
                "content": error_msg,
                "success": False
            }

async def smart_assistant(user_input):
    """智能助手主函数 - 异步版本"""
    agent = DeepseekAgent()
    result = await agent.process_request(user_input)
    return result

# 测试函数 - 更新为支持多个任务
async def test_all_features():
    """测试所有功能 - 支持多个任务"""
    test_cases = [
    # 单个任务测试
    "生成Amazon的股票分析报告"
    # # 多个任务测试
    # "创建明天下午2点的团队会议，并生成贵州茅台的股票分析报告",
    # "查看我的待办任务，然后查询未来7天的日历事件",
    # "删除10月份的所有任务，并清理下周的所有日历事件",
    # "创建一个高优先级任务：完成项目报告，截止到周五下午6点，然后查看所有任务"
    # "创建下面三个不同的提醒任务：1.2026年6月10日，老婆生日，提前7天，这7天里每天提醒我; 2. 2026年10月1日早上8点，爸爸生日; 3. 2025年11月8日，结婚纪念日，提前7天，这7天里每天提醒我。"
    # "查询快递单号为SF0251990106101的物流信息"
    ]

    print("🧪 测试所有功能（支持多个任务）")
    print("=" * 50)

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. 测试: {test_case}")
        try:
            result = await smart_assistant(test_case)
            if result["type"] == "stock_pdf":
                print(f"✅ 股票分析报告生成成功")
                print(f"   股票名称: {result.get('stock_name')}")
                print(f"   PDF大小: {len(result.get('pdf_binary', b''))} 字节")
                print(f"   消息: {result.get('message')}")
            else:
                print(f"结果: {result.get('content', '')}")
        except Exception as e:
            print(f"❌ 测试失败: {e}")
        print("-" * 50)

if __name__ == '__main__':
    # 测试所有功能
    asyncio.run(test_all_features())
