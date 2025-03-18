import asyncio
import time
import json
import aiohttp
import csv
import argparse
import os
import uuid
import random
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any, Union
from datetime import datetime

@dataclass
class APIConfig:
    """API配置数据类"""
    url: str
    method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)
    request_template: Dict[str, Any] = field(default_factory=dict)
    response_handlers: Dict[str, str] = field(default_factory=dict)
    stream: bool = True
    timeout: int = 60
    # 新增响应解析配置
    token_path: str = "choices[0].delta.content"  # 用于解析token的JSON路径
    session_id_path: str = "session_id"  # 用于解析会话ID的JSON路径
    error_path: str = "error.message"    # 用于解析错误信息的JSON路径

@dataclass
class TestConfig:
    """测试配置数据类"""
    api_config: APIConfig
    concurrent_users: int = 1
    test_id: str = ""
    description: str = ""
    verbose: bool = False
    duration: int = 0
    interval: float = 0.5
    active_threads: int = 0
    prompt_pool: List[str] = field(default_factory=list)
    use_random_prompt: bool = False
    use_dynamic_pool: bool = False  # 添加是否使用动态线程池的标志

@dataclass
class RequestMetrics:
    """请求指标数据类"""
    response_time: float = 0
    first_token_latency: float = 0
    total_latency: float = 0
    tokens_per_second: float = 0
    token_count: int = 0
    content: str = ""
    error: str = ""
    start_time: str = ""
    end_time: str = ""
    request_id: str = ""
    session_id: str = ""
    prompt: str = ""  # 添加提示词字段，记录请求中使用的提示词

@dataclass
class TestResult:
    """测试结果数据类"""
    test_id: str = ""
    description: str = ""
    concurrent_users: int = 0
    success_count: int = 0
    error_count: int = 0
    total_time: float = 0
    qps: float = 0
    avg_response_time: float = 0
    avg_first_token_latency: float = 0
    avg_total_latency: float = 0
    avg_tokens_per_second: float = 0
    max_response_time: float = 0
    min_response_time: float = 0
    request_metrics: List[RequestMetrics] = field(default_factory=list)

class APITester:
    """API测试核心类"""
    def __init__(self, config: TestConfig):
        self.config = config
        self.api_config = config.api_config
        self.verbose = config.verbose

    def get_json_value(self, json_obj: Dict, path: str) -> Any:
        """从JSON对象中获取指定路径的值"""
        try:
            parts = path.replace('][', '.').replace('[', '.').replace(']', '').split('.')
            value = json_obj
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                elif isinstance(value, list) and part.isdigit():
                    value = value[int(part)]
                else:
                    return None
                if value is None:
                    return None
            return value
        except Exception:
            return None

    def prepare_request_data(self, prompt: str) -> Dict[str, Any]:
        """准备请求数据"""
        request_data = self.api_config.request_template.copy()
        
        # 递归替换模板中的占位符
        def replace_placeholders(obj: Any, prompt: str) -> Any:
            if isinstance(obj, dict):
                return {k: replace_placeholders(v, prompt) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_placeholders(item, prompt) for item in obj]
            elif isinstance(obj, str):
                return obj.replace("${prompt}", prompt)
            return obj
        
        return replace_placeholders(request_data, prompt)

    async def process_stream_response(self, response: aiohttp.ClientResponse, start_time: float) -> RequestMetrics:
        """处理流式响应"""
        first_token_time = None
        last_token_time = None
        content = ""
        token_count = 0
        session_id = None

        try:
            async for line in response.content:
                current_time = time.time()
                line_str = line.decode('utf-8').strip()
                
                if not line_str:
                    continue
                    
                if line_str.startswith('data: '):
                    try:
                        json_str = line_str[5:].strip()
                        if json_str:
                            data = json.loads(json_str)
                            
                            # 使用配置的路径提取token
                            token = self.get_json_value(data, self.api_config.token_path)
                            
                            # 添加对特定格式的支持
                            if not token and "message" in data and "content" in data["message"]:
                                token = data["message"]["content"]
                                
                            if token:
                                if first_token_time is None:
                                    first_token_time = current_time
                                last_token_time = current_time
                                content += token
                                token_count += 1
                            
                            # 提取会话ID
                            if not session_id:
                                session_id = self.get_json_value(data, self.api_config.session_id_path)
                                if not session_id and "id" in data:
                                    session_id = data["id"]
                                
                    except json.JSONDecodeError:
                        if self.verbose:
                            print(f"JSON解析错误: {line_str}")
                        continue

        except Exception as e:
            return RequestMetrics(
                error=f"流处理错误: {str(e)}",
                start_time=datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S"),
                end_time=datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S"),
                prompt=prompt
            )

        end_time = time.time()
        response_time = end_time - start_time
        first_token_latency = (first_token_time - start_time) if first_token_time else 0
        total_latency = (last_token_time - start_time) if last_token_time else 0
        
        # 计算生成速度
        if first_token_time and last_token_time and last_token_time > first_token_time:
            generation_time = last_token_time - first_token_time
            tokens_per_second = token_count / generation_time
        else:
            tokens_per_second = 0

        return RequestMetrics(
            response_time=response_time,
            first_token_latency=first_token_latency,
            total_latency=total_latency,
            tokens_per_second=tokens_per_second,
            token_count=token_count,
            content=content,
            start_time=datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S"),
            end_time=datetime.fromtimestamp(end_time).strftime("%Y-%m-%d %H:%M:%S"),
            request_id=str(uuid.uuid4()),
            session_id=session_id,
            prompt=prompt
        )

    async def single_request(self, prompt: str) -> RequestMetrics:
        """执行单次请求并测量性能指标"""
        start_time = time.time()
        start_time_str = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S")
        request_data = self.prepare_request_data(prompt)
        
        # 验证请求数据的有效性
        if not self.is_valid_request(request_data):
            return RequestMetrics(
                error=f"无效请求: 请求数据验证失败",
                start_time=start_time_str,
                end_time=datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S"),
                request_id=str(uuid.uuid4()),
                prompt=prompt
            )
        
        if self.verbose:
            print(f"请求URL: {self.api_config.url}")
            print(f"请求数据: {json.dumps(request_data, ensure_ascii=False)[:200]}...")
        
        try:
            async with aiohttp.ClientSession() as session:
                # 根据配置的HTTP方法发送请求
                method = getattr(session, self.api_config.method.lower())
                
                async with method(
                    self.api_config.url,
                    json=request_data,
                    headers=self.api_config.headers,
                    timeout=self.api_config.timeout,
                    ssl=False  # 禁用SSL验证
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        error_type = "服务器错误" if response.status >= 500 else "客户端错误"
                        return RequestMetrics(
                            error=f"{error_type}: 状态码 {response.status}, 错误: {error_text}",
                            start_time=start_time_str,
                            end_time=datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S"),
                            request_id=str(uuid.uuid4()),
                            prompt=prompt
                        )
                    
                    # 处理流式响应
                    if self.api_config.stream:
                        metrics = await self.process_stream_response(response, start_time)
                        metrics.prompt = prompt  # 添加提示词到指标中
                        return metrics
                    else:
                        # 处理非流式响应
                        response_time = time.time() - start_time
                        response_json = await response.json()
                        
                        # 尝试从响应中提取错误信息
                        error = self.get_json_value(response_json, self.api_config.error_path)
                        if error:
                            return RequestMetrics(
                                error=f"API错误: {error}",
                                response_time=response_time,
                                start_time=start_time_str,
                                end_time=datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S"),
                                request_id=str(uuid.uuid4()),
                                prompt=prompt
                            )
                        
                        # 从响应中提取内容
                        content = ""
                        # 尝试查找内容字段
                        for path in ["content", "message.content", "choices[0].message.content"]:
                            content_value = self.get_json_value(response_json, path)
                            if content_value:
                                content = content_value
                                break
                        
                        # 特殊处理特定格式
                        if not content and "message" in response_json and isinstance(response_json["message"], dict) and "content" in response_json["message"]:
                            content = response_json["message"]["content"]
                        
                        # 提取会话ID
                        session_id = self.get_json_value(response_json, self.api_config.session_id_path)
                        if not session_id and "id" in response_json:
                            session_id = response_json["id"]
                        
                        return RequestMetrics(
                            response_time=response_time,
                            first_token_latency=response_time,  # 非流式响应，首个token延迟等于响应时间
                            total_latency=response_time,        # 非流式响应，总延迟等于响应时间
                            token_count=len(content.split()),   # 简单估算token数
                            content=content,
                            start_time=start_time_str,
                            end_time=datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S"),
                            request_id=str(uuid.uuid4()),
                            session_id=session_id,
                            prompt=prompt
                        )
                        
        except asyncio.TimeoutError:
            return RequestMetrics(
                error="超时错误: 请求超时",
                start_time=start_time_str,
                end_time=datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S"),
                request_id=str(uuid.uuid4()),
                prompt=prompt
            )
        except aiohttp.ClientError as e:
            return RequestMetrics(
                error=f"网络错误: {str(e)}",
                start_time=start_time_str,
                end_time=datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S"),
                request_id=str(uuid.uuid4()),
                prompt=prompt
            )
        except Exception as e:
            return RequestMetrics(
                error=f"未知错误: {str(e)}",
                start_time=start_time_str,
                end_time=datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S"),
                request_id=str(uuid.uuid4()),
                prompt=prompt
            )

    def is_valid_response(self, metrics: RequestMetrics) -> bool:
        """验证响应是否有效"""
        # 如果有错误，则响应无效
        if metrics.error:
            return False
        
        # 如果是流式响应，至少应有一些内容返回
        if self.api_config.stream and metrics.token_count == 0:
            if self.verbose:
                print("流式响应没有返回任何内容")
            return False
        
        # 如果没有内容返回，则响应无效
        if not metrics.content:
            if self.verbose:
                print("响应没有返回任何内容")
            return False
        
        # 正常情况下，必须有响应时间
        if metrics.response_time <= 0:
            if self.verbose:
                print("响应时间异常")
            return False
        
        return True

    async def concurrent_test(self) -> TestResult:
        """执行并发测试"""
        start_time = time.time()
        tasks = []
        valid_requests = 0
        invalid_requests = 0
        
        # 创建并发任务
        for _ in range(self.config.concurrent_users):
            # 选择提示词
            if self.config.use_random_prompt and self.config.prompt_pool:
                prompt = random.choice(self.config.prompt_pool)
            else:
                # 如果request_template中有prompt字段，使用它
                prompt = self.get_json_value(self.api_config.request_template, "prompt")
                if not prompt:
                    # 否则从请求模板中找可能的提示词
                    prompt = "这是一个测试提示词"
            
            tasks.append(self.single_request(prompt))
        
        # 执行所有任务
        results = await asyncio.gather(*tasks)
        end_time = time.time()
        
        # 统计结果
        valid_results = []
        invalid_results = []
        
        for result in results:
            if self.is_valid_response(result):
                valid_results.append(result)
                valid_requests += 1
            else:
                invalid_results.append(result)
                invalid_requests += 1
        
        if self.verbose:
            print(f"有效请求数: {valid_requests}, 无效请求数: {invalid_requests}")
        
        # 计算有效请求的指标
        total_time = end_time - start_time
        success_count = len(valid_results)
        error_count = len(invalid_results)
        
        if success_count > 0:
            avg_response_time = sum(r.response_time for r in valid_results) / success_count
            avg_first_token_latency = sum(r.first_token_latency for r in valid_results) / success_count
            avg_total_latency = sum(r.total_latency for r in valid_results) / success_count
            avg_tokens_per_second = sum(r.tokens_per_second for r in valid_results) / success_count
            
            max_response_time = max(r.response_time for r in valid_results)
            min_response_time = min(r.response_time for r in valid_results)
        else:
            avg_response_time = avg_first_token_latency = avg_total_latency = avg_tokens_per_second = 0
            max_response_time = min_response_time = 0
        
        qps = success_count / total_time if total_time > 0 else 0
        
        # 使用所有结果，无论成功与否
        all_results = results  # 直接使用所有结果，不区分有效无效
        
        return TestResult(
            test_id=self.config.test_id,
            description=self.config.description,
            concurrent_users=self.config.concurrent_users,
            success_count=success_count,
            error_count=error_count,
            total_time=total_time,
            qps=qps,
            avg_response_time=avg_response_time,
            avg_first_token_latency=avg_first_token_latency,
            avg_total_latency=avg_total_latency,
            avg_tokens_per_second=avg_tokens_per_second,
            max_response_time=max_response_time,
            min_response_time=min_response_time,
            request_metrics=all_results  # 包含所有请求结果
        )

    async def dynamic_thread_pool_test(self, active_threads: int, duration: int) -> TestResult:
        """动态线程池测试
        在指定的测试时间内，保持固定数量的活跃请求，一旦有请求完成就立即启动新请求。
        
        Args:
            active_threads: 同时活跃的线程数量
            duration: 测试持续时间(秒)
            
        Returns:
            测试结果
        """
        print(f"开始动态线程池测试，活跃线程数: {active_threads}，持续时间: {duration}秒")
        
        start_time = time.time()
        end_time = start_time + duration
        all_results = []  # 所有请求的结果
        active_tasks = set()  # 当前活跃的任务
        request_count = 0  # 总请求计数
        valid_requests = 0  # 有效请求计数
        invalid_requests = 0  # 无效请求计数
        
        # 创建任务完成回调函数
        def task_done_callback(task):
            nonlocal valid_requests, invalid_requests
            try:
                if task.done() and not task.cancelled():
                    result = task.result()
                    all_results.append(result)
                    
                    # 验证响应是否有效
                    if self.is_valid_response(result):
                        valid_requests += 1
                    else:
                        invalid_requests += 1
                        
                active_tasks.discard(task)
            except Exception as e:
                if self.verbose:
                    print(f"处理任务结果时出错: {str(e)}")
        
        # 创建任务管理器
        async def task_manager():
            nonlocal request_count
            
            while time.time() < end_time:
                # 检查是否需要添加新任务
                while len(active_tasks) < active_threads and time.time() < end_time:
                    # 选择提示词
                    if self.config.use_random_prompt and self.config.prompt_pool:
                        prompt = random.choice(self.config.prompt_pool)
                    else:
                        # 从请求模板中找可能的提示词
                        prompt = self.get_json_value(self.api_config.request_template, "prompt")
                        if not prompt:
                            prompt = "这是一个测试提示词"
                    
                    # 创建新请求任务
                    task = asyncio.create_task(self.single_request(prompt))
                    task.add_done_callback(task_done_callback)
                    active_tasks.add(task)
                    request_count += 1
                    
                    # 显示当前状态
                    elapsed = time.time() - start_time
                    remaining = end_time - time.time()
                    progress = elapsed / duration * 100
                    active_count = len(active_tasks)
                    print(f"\r测试进度: {progress:.1f}% - 已发送 {request_count} 请求, 已完成 {len(all_results)} 请求, 有效 {valid_requests} 请求, 无效 {invalid_requests} 请求, 当前活跃 {active_count} 请求, 剩余 {remaining:.1f}秒", end="")
                
                # 短暂等待，避免CPU占用过高
                await asyncio.sleep(0.1)
        
        # 启动任务管理器
        task_manager_task = asyncio.create_task(task_manager())
        
        try:
            # 等待测试时间结束
            await asyncio.sleep(duration)
            
            # 等待任务管理器完成
            await task_manager_task
            
            # 等待所有活跃任务完成或者超时
            if active_tasks:
                wait_timeout = min(10, self.api_config.timeout)  # 等待最多10秒让活跃任务完成
                done, pending = await asyncio.wait(active_tasks, timeout=wait_timeout)
                
                # 取消未完成的任务
                for task in pending:
                    task.cancel()
                
        except Exception as e:
            print(f"\n测试出现异常: {str(e)}")
            # 取消所有活跃任务
            for task in active_tasks:
                task.cancel()
            raise
        
        finally:
            # 确保任务管理器被取消
            if not task_manager_task.done():
                task_manager_task.cancel()
        
        total_elapsed = time.time() - start_time
        print(f"\n动态线程池测试完成，总计 {request_count} 个请求，完成 {len(all_results)} 个请求，有效 {valid_requests} 个请求，无效 {invalid_requests} 个请求，实际持续时间 {total_elapsed:.1f}秒")
        
        # 分离有效和无效请求，仅用于计算性能指标
        valid_results = [r for r in all_results if self.is_valid_response(r)]
        
        # 计算指标
        success_count = len(valid_results)
        error_count = len(all_results) - success_count
        
        if success_count > 0:
            avg_response_time = sum(r.response_time for r in valid_results) / success_count
            avg_first_token_latency = sum(r.first_token_latency for r in valid_results) / success_count
            avg_total_latency = sum(r.total_latency for r in valid_results) / success_count
            avg_tokens_per_second = sum(r.tokens_per_second for r in valid_results) / success_count
            
            max_response_time = max(r.response_time for r in valid_results)
            min_response_time = min(r.response_time for r in valid_results)
        else:
            avg_response_time = avg_first_token_latency = avg_total_latency = avg_tokens_per_second = 0
            max_response_time = min_response_time = 0
        
        qps = success_count / total_elapsed if total_elapsed > 0 else 0
        
        return TestResult(
            test_id=self.config.test_id,
            description=f"{self.config.description} - 动态线程池(活跃线程数: {active_threads})",
            concurrent_users=active_threads,
            success_count=success_count,
            error_count=error_count,
            total_time=total_elapsed,
            qps=qps,
            avg_response_time=avg_response_time,
            avg_first_token_latency=avg_first_token_latency,
            avg_total_latency=avg_total_latency,
            avg_tokens_per_second=avg_tokens_per_second,
            max_response_time=max_response_time,
            min_response_time=min_response_time,
            request_metrics=all_results  # 包含所有请求结果，无论成功失败
        )

    def is_valid_request(self, request_data: Dict[str, Any]) -> bool:
        """验证请求数据是否有效"""
        try:
            # 检查请求数据是否为非空字典
            if not request_data or not isinstance(request_data, dict):
                if self.verbose:
                    print("请求数据为空或不是字典")
                return False
            
            # 检查消息是否存在且格式是否正确
            messages = request_data.get("messages", [])
            if not messages or not isinstance(messages, list):
                if self.verbose:
                    print("消息为空或格式不正确")
                return False
            
            # 检查至少有一条消息，且每条消息都有角色和内容
            for msg in messages:
                if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                    if self.verbose:
                        print("消息缺少角色或内容")
                    return False
                
                # 检查内容不为空
                if not msg.get("content"):
                    if self.verbose:
                        print("消息内容为空")
                    return False
            
            # 检查模型参数是否存在
            if "model" not in request_data:
                if self.verbose:
                    print("缺少模型参数")
                return False
            
            return True
        except Exception as e:
            if self.verbose:
                print(f"验证请求数据时出错: {str(e)}")
            return False

def save_result_to_csv(result: TestResult, output_file: str):
    """将测试结果保存到CSV文件"""
    # 确保输出目录存在
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    
    # 生成文件名前缀
    if result.test_id and result.test_id in output_file:
        file_prefix = output_file.replace('.csv', '')
    elif result.test_id:
        file_prefix = os.path.join(os.path.dirname(output_file), result.test_id)
    else:
        file_prefix = output_file.replace('.csv', '')
    
    # 保存总体结果
    with open(f"{file_prefix}.csv", 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['指标', '值'])
        writer.writerow(['测试ID', result.test_id])
        writer.writerow(['描述', result.description])
        writer.writerow(['并发数', result.concurrent_users])
        writer.writerow(['成功请求数', result.success_count])
        writer.writerow(['失败请求数', result.error_count])
        writer.writerow(['总耗时(秒)', f"{result.total_time:.3f}"])
        writer.writerow(['QPS', f"{result.qps:.3f}"])
        writer.writerow(['平均响应时间(秒)', f"{result.avg_response_time:.3f}"])
        writer.writerow(['平均首个token延迟(秒)', f"{result.avg_first_token_latency:.3f}"])
        writer.writerow(['平均整句延迟(秒)', f"{result.avg_total_latency:.3f}"])
        writer.writerow(['平均生成速度(tokens/秒)', f"{result.avg_tokens_per_second:.3f}"])
        writer.writerow(['最大响应时间(秒)', f"{result.max_response_time:.3f}"])
        writer.writerow(['最小响应时间(秒)', f"{result.min_response_time:.3f}"])
    
    # 保存详细请求结果
    details_file = f"{file_prefix}_details.csv"
    with open(details_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        headers = ['请求ID', '会话ID', '提示词', '开始时间', '结束时间', '响应时间(秒)', '首个token延迟(秒)',
                  '整句延迟(秒)', '每秒生成速度(tokens/秒)', '返回token数', 'AI生成内容', '错误详情', '是否有效']
        writer.writerow(headers)
        
        for i, req in enumerate(result.request_metrics):
            # 判断请求是否有效
            is_valid = not bool(req.error) and bool(req.content) and req.response_time > 0
            
            row = [
                req.request_id,
                req.session_id if req.session_id else "",
                req.prompt[:100] + "..." if len(req.prompt) > 100 else req.prompt,
                req.start_time,
                req.end_time,
                f"{req.response_time:.3f}",
                f"{req.first_token_latency:.3f}", 
                f"{req.total_latency:.3f}", 
                f"{req.tokens_per_second:.3f}", 
                req.token_count,
                req.content[:200] + "..." if len(req.content) > 200 else req.content,
                req.error,
                "是" if is_valid else "否"
            ]
            writer.writerow(row)
    
    # 创建错误请求专用CSV文件
    error_details_file = f"{file_prefix}_errors.csv"
    with open(error_details_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        headers = ['请求ID', '提示词', '错误详情', '开始时间', '结束时间']
        writer.writerow(headers)
        
        # 只保存有错误的请求
        error_requests = [req for req in result.request_metrics if req.error]
        for req in error_requests:
            row = [
                req.request_id,
                req.prompt[:200] + "..." if len(req.prompt) > 200 else req.prompt,
                req.error,
                req.start_time,
                req.end_time
            ]
            writer.writerow(row)
    
    # 创建内容详情文件 - 包含完整的问题和回复
    content_details_file = f"{file_prefix}_conversation_details.md"
    with open(content_details_file, 'w', encoding='utf-8') as f:
        f.write(f"# 测试ID: {result.test_id}\n\n")
        f.write(f"## 测试描述\n{result.description}\n\n")
        f.write(f"## 测试结果摘要\n")
        f.write(f"- 并发数: {result.concurrent_users}\n")
        f.write(f"- 成功请求数: {result.success_count}\n")
        f.write(f"- 失败请求数: {result.error_count}\n")
        f.write(f"- 总耗时: {result.total_time:.2f}秒\n")
        f.write(f"- QPS: {result.qps:.2f}\n")
        f.write(f"- 平均响应时间: {result.avg_response_time:.3f}秒\n")
        f.write(f"- 平均首个token延迟: {result.avg_first_token_latency:.3f}秒\n")
        f.write(f"- 平均整句延迟: {result.avg_total_latency:.3f}秒\n")
        f.write(f"- 平均生成速度: {result.avg_tokens_per_second:.3f} tokens/秒\n\n")
        
        # 按会话ID分组
        sessions = {}
        for req in result.request_metrics:
            session_id = req.session_id if req.session_id else "无会话ID"
            if session_id not in sessions:
                sessions[session_id] = []
            sessions[session_id].append(req)
        
        # 输出每个会话的对话内容
        for session_id, reqs in sessions.items():
            f.write(f"## 会话ID: {session_id}\n\n")
            
            for req in reqs:
                f.write(f"**开始时间**: {req.start_time}\n")
                f.write(f"**结束时间**: {req.end_time}\n\n")
                
                f.write(f"**提示词**:\n```\n{req.prompt}\n```\n\n")
                
                if req.error:
                    f.write(f"**错误**:\n```\n{req.error}\n```\n\n")
                
                if req.content:
                    f.write(f"**回复**:\n```\n{req.content}\n```\n\n")
                
                f.write(f"**指标**:\n")
                f.write(f"- 响应时间: {req.response_time:.3f}秒\n")
                f.write(f"- 首个token延迟: {req.first_token_latency:.3f}秒\n")
                f.write(f"- 整句延迟: {req.total_latency:.3f}秒\n")
                f.write(f"- 返回token数: {req.token_count}\n")
                f.write(f"- 每秒生成速度: {req.tokens_per_second:.3f} tokens/秒\n\n")
                f.write("---\n\n")
    
    print(f"结果已保存到：{file_prefix}.csv")
    print(f"详细结果已保存到：{details_file}")
    if error_requests:
        print(f"错误请求已保存到：{error_details_file}")
    print(f"对话详情已保存到：{content_details_file}")

def print_result(result: TestResult):
    """打印测试结果到控制台"""
    print(f"\n并发测试结果:")
    if result.test_id:
        print(f"测试ID: {result.test_id}")
    if result.description:
        print(f"描述: {result.description}")
    print(f"并发数: {result.concurrent_users}")
    print(f"成功请求数: {result.success_count}")
    print(f"失败请求数: {result.error_count}")
    print(f"总耗时: {result.total_time:.2f}秒")
    print(f"QPS: {result.qps:.2f}")
    print(f"平均响应时间: {result.avg_response_time:.3f}秒")
    print(f"平均首个token延迟: {result.avg_first_token_latency:.3f}秒")
    print(f"平均整句延迟: {result.avg_total_latency:.3f}秒")
    print(f"平均生成速度: {result.avg_tokens_per_second:.3f} tokens/秒")
    print(f"最大响应时间: {result.max_response_time:.3f}秒")
    print(f"最小响应时间: {result.min_response_time:.3f}秒")

def load_config_from_file(file_path: str) -> TestConfig:
    """从JSON文件加载测试配置"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            
            # 处理API配置
            api_config_data = config_data.pop("api_config", {})
            api_config = APIConfig(**api_config_data)
            
            # 处理提示词池
            if "prompt_pool_file" in config_data:
                pool_file = config_data.pop("prompt_pool_file")
                try:
                    with open(pool_file, 'r', encoding='utf-8') as pool_f:
                        config_data["prompt_pool"] = [line.strip() for line in pool_f if line.strip()]
                        config_data["use_random_prompt"] = True
                except Exception as e:
                    print(f"加载提示词池文件失败: {str(e)}")
            
            # 判断是否配置了动态线程池
            if not "use_dynamic_pool" in config_data:
                if "active_threads" in config_data and config_data["active_threads"] > 0:
                    config_data["use_dynamic_pool"] = True
                else:
                    config_data["use_dynamic_pool"] = False
            
            # 创建测试配置
            config_data["api_config"] = api_config
            return TestConfig(**config_data)
    except Exception as e:
        print(f"加载配置文件失败: {str(e)}")
        return None

async def main():
    parser = argparse.ArgumentParser(description='通用大模型API接口性能测试工具')
    parser.add_argument('--config', type=str, required=True, help='配置文件路径')
    parser.add_argument('--output', type=str, default='test_result.csv', help='输出文件路径')
    parser.add_argument('--verbose', action='store_true', help='打印详细日志')
    parser.add_argument('--single', action='store_true', help='仅测试单个请求')
    parser.add_argument('--dynamic', action='store_true', help='使用动态线程池模式')
    parser.add_argument('--active_threads', type=int, default=0, help='动态线程池模式下的活跃线程数')
    parser.add_argument('--duration', type=int, default=0, help='测试持续时间(秒)')
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config_from_file(args.config)
    if not config:
        print("配置加载失败，退出测试")
        return
    
    # 设置输出文件
    if config.test_id:
        output_file = os.path.join(os.path.dirname(args.output), f"{config.test_id}.csv")
    else:
        output_file = args.output
    
    # 应用命令行参数，优先级高于配置文件
    config.verbose = args.verbose or config.verbose
    
    # 创建测试实例
    api_tester = APITester(config)
    
    # 选择测试模式
    if args.single:
        # 单个请求测试
        print("开始单个请求测试...")
        # 从配置中获取提示词
        if config.use_random_prompt and config.prompt_pool:
            prompt = random.choice(config.prompt_pool)
        else:
            prompt = "这是一个测试提示词"
        
        print(f"使用提示词: {prompt}")
        metrics = await api_tester.single_request(prompt)
        
        # 验证响应是否有效
        is_valid = api_tester.is_valid_response(metrics)
        
        print(f"响应有效: {'是' if is_valid else '否'}")
        print(f"响应时间: {metrics.response_time:.3f}秒")
        print(f"首个token延迟: {metrics.first_token_latency:.3f}秒")
        print(f"整句延迟: {metrics.total_latency:.3f}秒")
        print(f"每秒生成速度: {metrics.tokens_per_second:.3f} tokens/秒")
        print(f"返回token数: {metrics.token_count}")
        
        if metrics.session_id:
            print(f"会话ID: {metrics.session_id}")
        
        if metrics.content:
            print(f"\nAI生成内容:\n{metrics.content}")
        
        if metrics.error:
            print(f"\n错误:\n{metrics.error}")
            
        # 将单个请求结果也保存到CSV
        single_result = TestResult(
            test_id=f"{config.test_id}_single",
            description=f"{config.description} - 单个请求测试",
            concurrent_users=1,
            success_count=1 if is_valid else 0,
            error_count=0 if is_valid else 1,
            total_time=metrics.response_time,
            qps=1/metrics.response_time if metrics.response_time > 0 else 0,
            avg_response_time=metrics.response_time,
            avg_first_token_latency=metrics.first_token_latency,
            avg_total_latency=metrics.total_latency,
            avg_tokens_per_second=metrics.tokens_per_second,
            max_response_time=metrics.response_time,
            min_response_time=metrics.response_time,
            request_metrics=[metrics]
        )
        save_result_to_csv(single_result, output_file.replace('.csv', '_single.csv'))
    
    # 支持从配置文件或命令行读取动态线程池设置
    elif args.dynamic or args.active_threads > 0 or config.use_dynamic_pool:
        # 动态线程池测试
        # 命令行参数优先于配置文件
        active_threads = args.active_threads if args.active_threads > 0 else config.active_threads
        if active_threads <= 0:
            active_threads = config.concurrent_users
        
        # 命令行参数优先于配置文件
        duration = args.duration if args.duration > 0 else config.duration
        if duration <= 0:
            duration = 60  # 默认60秒
        
        print(f"开始动态线程池测试，活跃线程数: {active_threads}，持续时间: {duration}秒")
        
        result = await api_tester.dynamic_thread_pool_test(active_threads, duration)
        print_result(result)
        save_result_to_csv(result, output_file)
        
    else:
        # 普通并发测试
        print(f"开始并发测试，并发数: {config.concurrent_users}...")
        result = await api_tester.concurrent_test()
        print_result(result)
        save_result_to_csv(result, output_file)

if __name__ == "__main__":
    asyncio.run(main())

# # 非流式响应测试
# python test.py --config practical_api_config.json --output results/api_test.csv

# # 流式响应测试
# python test.py --config stream_api_config.json --dynamic --active_threads 5 --duration 60

# # 单个请求测试
# python test.py --config practical_api_config.json --single --verbose