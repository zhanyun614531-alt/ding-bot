from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
import hmac
import hashlib
import base64
import urllib.parse
import json
import requests
import os
import time
import logging
import re
import agent_tools
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
import asyncio
from contextlib import asynccontextmanager
import uuid
from datetime import datetime

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
app_logger = logging.getLogger("dingtalk-bot")

# 线程池执行器
thread_pool = ThreadPoolExecutor(max_workers=5)

# 存储处理中的任务
processing_tasks = {}

# 临时存储PDF文件（在生产环境中应该使用持久化存储）
pdf_storage = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期事件管理器"""
    # 启动时执行的操作
    app_logger.info("🚀 钉钉机器人服务启动中...")
    yield
    # 关闭时执行的操作
    app_logger.info("🛑 钉钉机器人服务关闭中...")
    thread_pool.shutdown(wait=True)
    app_logger.info("✅ 线程池已关闭")


# 初始化FastAPI应用
app = FastAPI(
    title="钉钉机器人服务",
    description="基于FastAPI的钉钉机器人智能助手",
    version="1.0.0",
    lifespan=lifespan
)

# 从环境变量获取钉钉机器人信息
ROBOT_ACCESS_TOKEN = os.getenv('ROBOT_ACCESS_TOKEN')
ROBOT_SECRET = os.getenv('ROBOT_SECRET')


def generate_dingtalk_signature(timestamp: str, secret: str) -> str:
    """生成钉钉机器人签名"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(hmac_code))


async def upload_file_to_dingtalk(file_data: bytes, file_name: str, file_type: str = "file") -> Dict[str, Any]:
    """
    上传文件到钉钉服务器并获取media_id
    """
    try:
        timestamp = str(round(time.time() * 1000))
        sign = generate_dingtalk_signature(timestamp, ROBOT_SECRET)

        upload_url = f'https://oapi.dingtalk.com/robot/upload?access_token={ROBOT_ACCESS_TOKEN}&timestamp={timestamp}&sign={sign}'

        app_logger.info(f"📎 准备上传文件到: {upload_url}")
        app_logger.info(f"📎 文件信息: {file_name}, 大小: {len(file_data)} bytes, 类型: {file_type}")

        # 准备文件上传
        files = {
            'media': (file_name, file_data, 'application/pdf')
        }

        data = {
            'type': file_type
        }

        loop = asyncio.get_event_loop()
        app_logger.info("🔄 发送文件上传请求...")
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(upload_url, files=files, data=data, timeout=30)
        )

        app_logger.info(f"📎 上传响应状态码: {response.status_code}")
        app_logger.info(f"📎 上传响应内容: {response.text}")

        if response.status_code == 200:
            result = response.json()
            if result.get('errcode') == 0:
                app_logger.info(f"✅ 文件上传成功: {file_name}, media_id: {result.get('media_id')}")
                return {
                    "success": True,
                    "media_id": result.get('media_id'),
                    "created_at": result.get('created_at')
                }
            else:
                app_logger.error(f"❌ 文件上传失败: {result}")
                return {
                    "success": False,
                    "error": f"上传失败: {result.get('errmsg', '未知错误')}"
                }
        else:
            app_logger.error(f"❌ 文件上传HTTP错误: {response.status_code}")
            return {
                "success": False,
                "error": f"HTTP错误: {response.status_code}"
            }

    except Exception as e:
        app_logger.error(f"❌ 文件上传异常: {str(e)}")
        return {
            "success": False,
            "error": f"上传异常: {str(e)}"
        }


async def send_file_message(media_id: str, file_name: str, at_user_ids=None, at_mobiles=None, is_at_all=False):
    """发送钉钉文件消息"""
    try:
        timestamp = str(round(time.time() * 1000))
        sign = generate_dingtalk_signature(timestamp, ROBOT_SECRET)

        url = f'https://oapi.dingtalk.com/robot/send?access_token={ROBOT_ACCESS_TOKEN}&timestamp={timestamp}&sign={sign}'

        body = {
            "at": {
                "isAtAll": is_at_all,
                "atUserIds": at_user_ids or [],
                "atMobiles": at_mobiles or []
            },
            "file": {
                "media_id": media_id
            },
            "msgtype": "file"
        }

        headers = {'Content-Type': 'application/json'}

        app_logger.info(f"📤 发送文件消息: {file_name}, media_id: {media_id}")
        app_logger.info(f"📤 请求URL: {url}")
        app_logger.info(f"📤 请求体: {json.dumps(body, ensure_ascii=False)}")

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: requests.post(url, json=body, headers=headers, timeout=10)
        )

        app_logger.info(f"📤 文件消息响应状态码: {resp.status_code}")
        app_logger.info(f"📤 文件消息响应内容: {resp.text}")

        if resp.status_code == 200:
            result = resp.json()
            if result.get('errcode') == 0:
                app_logger.info(f"✅ 文件消息发送成功: {file_name}")
                return True
            else:
                app_logger.warning(f"❌ 文件消息发送失败: {result}")
                return False
        else:
            app_logger.warning(f"❌ 文件消息API响应异常: {resp.status_code} - {resp.text}")
            return False

    except Exception as e:
        app_logger.error(f"❌ 发送文件消息异常: {e}")
        return False


async def send_pdf_via_dingtalk(pdf_binary: bytes, stock_name: str, at_user_ids=None):
    """
    通过钉钉发送PDF文件
    """
    try:
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"股票分析报告_{stock_name}_{timestamp}.pdf"

        app_logger.info(f"📤 开始上传PDF文件: {file_name}, 大小: {len(pdf_binary)} 字节")

        # 第一步：上传文件到钉钉服务器
        app_logger.info("🔄 开始上传文件到钉钉服务器...")
        upload_result = await upload_file_to_dingtalk(pdf_binary, file_name, "file")

        if not upload_result["success"]:
            error_msg = f"❌ PDF文件上传失败: {upload_result.get('error', '未知错误')}"
            app_logger.error(error_msg)
            await send_official_message(error_msg, at_user_ids=at_user_ids)
            return False

        app_logger.info(f"✅ 文件上传成功，media_id: {upload_result['media_id']}")

        # 第二步：发送文件消息
        app_logger.info("🔄 开始发送文件消息...")
        send_success = await send_file_message(upload_result["media_id"], file_name, at_user_ids=at_user_ids)

        if send_success:
            success_msg = f"✅ 股票分析报告已生成并发送\n📈 股票: {stock_name}\n📄 文件名: {file_name}"
            app_logger.info(success_msg)
            await send_official_message(success_msg, at_user_ids=at_user_ids)
            return True
        else:
            error_msg = f"❌ 文件消息发送失败，但文件已上传 (media_id: {upload_result['media_id']})"
            app_logger.error(error_msg)
            await send_official_message(error_msg, at_user_ids=at_user_ids)
            return False

    except Exception as e:
        error_msg = f"❌ 发送PDF文件时出错: {str(e)}"
        app_logger.error(error_msg)
        await send_official_message(error_msg, at_user_ids=at_user_ids)
        return False


async def sync_llm_processing(conversation_id, user_input, at_user_ids):
    """同步处理LLM任务（在线程中运行）"""
    try:
        app_logger.info(f"开始处理LLM请求: {user_input}")

        ark_key = os.environ.get('ARK_API_KEY')
        if not ark_key:
            error_msg = "Test1：ARK_API_KEY未设置"
            await send_official_message(error_msg, at_user_ids=at_user_ids)
            return

        result = await agent_tools.smart_assistant(user_input)

        if result:
            # 处理不同类型的返回结果
            if isinstance(result, dict) and result.get("type") == "stock_pdf" and result.get("success"):
                # 处理股票分析PDF结果
                pdf_binary = result.get("pdf_binary")
                stock_name = result.get("stock_name", "未知股票")
                message = result.get("message", "股票分析报告生成完成")

                if pdf_binary:
                    # 先发送提示消息
                    await send_official_message("📈 正在生成股票分析报告PDF，请稍候...", at_user_ids=at_user_ids)
                    # 发送PDF文件
                    await send_pdf_via_dingtalk(pdf_binary, stock_name, at_user_ids)
                else:
                    error_msg = "❌ PDF二进制数据为空"
                    await send_official_message(error_msg, at_user_ids=at_user_ids)

            elif isinstance(result, dict) and result.get("type") == "text":
                # 处理普通文本结果
                final_result = f"Test1：{result.get('content', '')}"
                await send_official_message(final_result, at_user_ids=at_user_ids)
            else:
                # 兼容旧版本返回格式
                final_result = f"Test1：{result}"
                await send_official_message(final_result, at_user_ids=at_user_ids)
        else:
            error_msg = "Test1：LLM返回了空内容"
            await send_official_message(error_msg, at_user_ids=at_user_ids)

    except Exception as e:
        error_msg = f"Test1：处理出错: {str(e)}"
        app_logger.error(f"LLM处理错误: {error_msg}")
        await send_official_message(error_msg, at_user_ids=at_user_ids)
    finally:
        if conversation_id in processing_tasks:
            del processing_tasks[conversation_id]


async def async_process_llm_message(conversation_id, user_input, at_user_ids):
    """异步包装器，在线程池中运行同步任务"""
    loop = asyncio.get_event_loop()

    processing_tasks[conversation_id] = {
        "start_time": time.time(),
        "user_input": user_input
    }

    await loop.run_in_executor(
        thread_pool,
        lambda: asyncio.run(sync_llm_processing(conversation_id, user_input, at_user_ids))
    )


async def send_official_message(msg, at_user_ids=None, at_mobiles=None, is_at_all=False):
    """发送钉钉消息"""
    try:
        timestamp = str(round(time.time() * 1000))
        sign = generate_dingtalk_signature(timestamp, ROBOT_SECRET)

        robot_token = os.environ.get('ROBOT_ACCESS_TOKEN')
        robot_secret = os.environ.get('ROBOT_SECRET')

        if not robot_token or not robot_secret:
            return False

        url = f'https://oapi.dingtalk.com/robot/send?access_token={robot_token}&timestamp={timestamp}&sign={sign}'

        body = {
            "at": {
                "isAtAll": is_at_all,
                "atUserIds": at_user_ids or [],
                "atMobiles": at_mobiles or []
            },
            "text": {
                "content": msg
            },
            "msgtype": "text"
        }

        headers = {'Content-Type': 'application/json'}

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: requests.post(url, json=body, headers=headers, timeout=10)
        )

        if resp.status_code == 200:
            result = resp.json()
            return result.get('errcode') == 0
        else:
            app_logger.warning(f"钉钉API响应异常: {resp.status_code} - {resp.text}")
            return False

    except Exception as e:
        app_logger.error(f"发送消息异常: {e}")
        return False


def process_command(command):
    """处理用户指令"""
    original_msg = command.strip()
    key = "Test1"
    raw_command = re.sub(re.escape(key), '', original_msg)
    command = re.sub(r'\s', '', raw_command)

    if not command:
        return "Test1：请发送具体指令哦~ 支持的指令：\n- LLM"
    elif command == '时间':
        return f"Test1：当前时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    elif command.startswith("LLM"):
        try:
            pure_command = re.sub(r'^LLM', '', command).strip()
            response = asyncio.run(agent_tools.smart_assistant(pure_command))

            if response is None:
                return "Test1：LLM处理超时或无响应"
            elif not response.strip():
                return "Test1：LLM返回了空内容"
            else:
                return f"Test1：{response}"

        except Exception as e:
            return f"Test1：LLM处理出错: {str(e)}"
    else:
        return f"Test1：暂不支持该指令：{command}"


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def home():
    return "钉钉机器人服务运行中 ✅"


@app.get("/health")
async def health():
    """健康检查端点"""
    health_status = {
        "status": "healthy",
        "service": "dingtalk-bot",
        "timestamp": time.time(),
        "active_tasks": len(processing_tasks),
        "environment": "production",
        "version": "1.0.0"
    }
    return JSONResponse(health_status)


@app.api_route("/dingtalk/webhook", methods=["GET", "POST"])
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """钉钉消息接收接口"""
    if request.method == "GET":
        return JSONResponse({"status": "服务运行中"})

    try:
        data = await request.json()
        app_logger.info(f"收到钉钉消息: {data}")

        if 'text' in data and 'content' in data['text']:
            raw_content = data['text']['content'].strip()
            command = re.sub(r'<at id=".*?">@.*?</at>', '', raw_content).strip()

            conversation_id = data.get('conversationId', 'unknown')
            at_user_ids = [user['dingtalkId'] for user in data.get('atUsers', [])]

            if not command.startswith("Test1 LLM"):
                result = process_command(command)
                await send_official_message(result, at_user_ids=at_user_ids)
                return JSONResponse({"success": True})
            else:
                immediate_response = "Test1：正在思考中，请稍等片刻... ⏳"
                await send_official_message(immediate_response, at_user_ids=at_user_ids)

                pure_command = re.sub(r'^Test1\s*LLM\s*', '', command).strip()

                background_tasks.add_task(
                    async_process_llm_message,
                    conversation_id,
                    pure_command,
                    at_user_ids
                )

                return JSONResponse({"success": True, "status": "processing"})

        return JSONResponse({"success": True})

    except Exception as e:
        app_logger.error(f"处理webhook请求出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理请求出错: {str(e)}")


@app.get("/debug/tasks")
async def debug_tasks():
    """调试接口：查看当前处理中的任务"""
    now = time.time()
    active_tasks = {}

    for task_id, task_info in processing_tasks.items():
        duration = now - task_info['start_time']
        active_tasks[task_id] = {
            "user_input": task_info['user_input'],
            "duration_seconds": round(duration, 1),
            "status": "running" if duration < 300 else "stuck"
        }

    return JSONResponse({
        "active_tasks_count": len(active_tasks),
        "server_time": now,
        "active_tasks": active_tasks
    })


@app.post("/api/send-pdf")
async def api_send_pdf(request: Request):
    """API接口：手动发送PDF文件（用于测试）"""
    try:
        data = await request.json()
        pdf_base64 = data.get('pdf_base64')
        stock_name = data.get('stock_name', '测试股票')
        at_user_ids = data.get('at_user_ids', [])

        if not pdf_base64:
            raise HTTPException(status_code=400, detail="PDF数据不能为空")

        # 解码Base64
        pdf_binary = base64.b64decode(pdf_base64)

        # 发送PDF
        success = await send_pdf_via_dingtalk(pdf_binary, stock_name, at_user_ids)

        return JSONResponse({
            "success": success,
            "message": "PDF发送请求已处理"
        })

    except Exception as e:
        app_logger.error(f"API发送PDF出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"发送PDF出错: {str(e)}")


@app.get("/test-playwright")
async def test_playwright():
    """测试Playwright异步功能"""
    try:
        # 使用异步方式测试Playwright
        result = await agent_tools.test_playwright_async()
        return {"status": "success", "message": f"Playwright测试成功: {result}"}
    except Exception as e:
        return {"status": "error", "message": f"Playwright测试失败: {str(e)}"}

@app.get("/test-file-upload")
async def test_file_upload():
    """测试文件上传功能"""
    try:
        # 创建一个简单的测试PDF
        from reportlab.pdfgen import canvas
        from io import BytesIO
        
        buffer = BytesIO()
        p = canvas.Canvas(buffer)
        p.drawString(100, 100, "测试PDF文件")
        p.showPage()
        p.save()
        
        pdf_data = buffer.getvalue()
        buffer.close()
        
        # 测试上传
        result = await send_pdf_via_dingtalk(pdf_data, "测试股票", [])
        
        return JSONResponse({
            "success": result,
            "message": "文件上传测试完成",
            "pdf_size": len(pdf_data)
        })
        
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        })

if __name__ == '__main__':
    import uvicorn

    # 使用Render提供的PORT环境变量，如果没有则使用8000
    port = int(os.getenv('PORT', 8000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        workers=1,
        reload=False
    )
