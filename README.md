# AI-Test
无聊中写的，大家可以下载自行使用。
用于测试大模型提供的API具体指标。
# 大模型API性能测试工具规则说明

## 1. 配置文件参数定义

### 顶层参数

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|-------|------|------|-------|------|
| `test_id` | 字符串 | 否 | `""` | 测试的唯一标识，用于生成输出文件名 |
| `description` | 字符串 | 否 | `""` | 测试的描述信息 |
| `concurrent_users` | 整数 | 否 | `1` | 普通并发测试模式下的并发用户数 |
| `active_threads` | 整数 | 否 | `0` | 动态线程池模式下同时保持活跃的请求数，大于0时自动启用动态线程池 |
| `duration` | 整数 | 否 | `0` | 动态线程池测试持续时间(秒) |
| `verbose` | 布尔 | 否 | `false` | 是否打印详细日志 |
| `interval` | 浮点数 | 否 | `0.5` | 内部轮询间隔(秒) |
| `prompt_pool_file` | 字符串 | 否 | - | 提示词库文件路径，每行一个提示词 |
| `prompt_pool` | 字符串数组 | 否 | `[]` | 内嵌提示词库 |
| `use_random_prompt` | 布尔 | 否 | `false` | 是否使用随机提示词，设置`prompt_pool_file`时自动设为`true` |
| `use_dynamic_pool` | 布尔 | 否 | `false` | 是否使用动态线程池模式，设置`active_threads`大于0时自动设为`true` |
| `api_config` | 对象 | 是 | - | API配置，详见下方 |

### API配置参数 (api_config)

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|-------|------|------|-------|------|
| `url` | 字符串 | 是 | - | API请求地址 |
| `method` | 字符串 | 否 | `"POST"` | HTTP请求方法 |
| `headers` | 对象 | 否 | `{}` | HTTP请求头 |
| `request_template` | 对象 | 否 | `{}` | 请求体模板，可使用`${prompt}`占位符 |
| `stream` | 布尔 | 否 | `true` | 是否使用流式响应 |
| `timeout` | 整数 | 否 | `60` | 请求超时时间(秒) |
| `token_path` | 字符串 | 否 | `"choices[0].delta.content"` | 从响应中提取token的JSON路径 |
| `session_id_path` | 字符串 | 否 | `"session_id"` | 从响应中提取会话ID的JSON路径 |
| `error_path` | 字符串 | 否 | `"error.message"` | 从响应中提取错误信息的JSON路径 |

## 2. 配置文件示例

### 流式响应配置示例

```json
{
    "test_id": "stream_api_test",
    "description": "流式API接口测试",
    "concurrent_users": 5,
    "active_threads": 10,
    "duration": 60,
    "api_config": {
        "url": "https://your-api-endpoint.com/api/completions",
        "method": "POST",
        "headers": {
            "Authorization": "Bearer YOUR_API_KEY",
            "Content-Type": "application/json"
        },
        "request_template": {
            "model": "your-model-name",
            "messages": [
                {"role": "user", "content": "${prompt}"}
            ],
            "stream": true
        },
        "stream": true,
        "timeout": 60,
        "token_path": "message.content",
        "session_id_path": "id",
        "error_path": "status_code"
    },
    "prompt_pool_file": "prompts.txt",
    "use_random_prompt": true
}
```

### 非流式响应配置示例

```json
{
    "test_id": "nonstream_api_test",
    "description": "非流式API接口测试",
    "concurrent_users": 5,
    "active_threads": 0,
    "api_config": {
        "url": "https://your-api-endpoint.com/api/completions",
        "method": "POST",
        "headers": {
            "Authorization": "Bearer YOUR_API_KEY",
            "Content-Type": "application/json"
        },
        "request_template": {
            "model": "your-model-name",
            "messages": [
                {"role": "user", "content": "${prompt}"}
            ],
            "stream": false
        },
        "stream": false,
        "timeout": 60,
        "token_path": "message.content",
        "session_id_path": "id",
        "error_path": "status_code"
    },
    "prompt_pool": [
        "你好，请介绍一下自己",
        "讲一个有趣的故事",
        "解释一下量子物理的基本原理"
    ],
    "use_random_prompt": true
}
```

## 3. 测试模式区别

| 测试模式 | 触发方式 | 说明 |
|---------|---------|------|
| 单次请求测试 | 命令行参数`--single` | 发送单个请求并收集指标 |
| 普通并发测试 | 无命令行参数且配置文件无动态线程池设置 | 同时发送`concurrent_users`个请求，等待所有请求完成 |
| 动态线程池测试 | 命令行参数`--dynamic`或`--active_threads`>0或配置`active_threads`>0或`use_dynamic_pool`=true | 持续保持`active_threads`个活跃请求，持续`duration`秒 |

普通并发测试和动态线程池测试的主要区别：
- 普通并发测试：一次性发送固定数量请求，适合测试系统瞬时负载能力
- 动态线程池测试：持续保持固定活跃请求数，适合测试系统在持续负载下的性能和稳定性

## 4. 性能指标定义和计算公式

### 基础指标（单一请求的指标）

| 指标名 | 单位 | 计算公式 | 说明 |
|-------|-----|---------|------|
| `response_time` | 秒 | 请求结束时间 - 请求开始时间 | 响应时间：从发送请求到收到完整响应的总时间，衡量请求的整体处理耗时 |
| `first_token_latency` | 秒 | 首个token时间 - 请求开始时间 | 首个token延迟：从发送请求到收到第一个token的时间，衡量系统响应速度和初始化处理时间 |
| `total_latency` | 秒 | 最后token时间 - 请求开始时间 | 整句延迟：从发送请求到收到最后一个token的时间，衡量完整响应内容的生成时间 |
| `token_count` | 个 | 累计接收的token数量 | token数量：响应中包含的token总数，衡量生成内容的规模 |
| `tokens_per_second` | 个/秒 | token_count / (最后token时间 - 首个token时间) | 生成速度：每秒生成的token数量，仅计算从第一个token到最后一个token之间的时间，衡量大模型生成内容的效率 |

### 聚合指标（多个请求的统计结果）

| 指标名 | 单位 | 计算公式 | 说明 |
|-------|-----|---------|------|
| `success_count` | 个 | 成功请求数量 | 成功请求数：有效请求的总数，表示成功完成的请求数量 |
| `error_count` | 个 | 失败请求数量 | 失败请求数：无效请求的总数，表示失败、超时或错误的请求数量 |
| `total_time` | 秒 | 测试结束时间 - 测试开始时间 | 总测试时间：整个测试的持续时间，从开始到结束的时间跨度 |
| `qps` | 个/秒 | success_count / total_time | 每秒查询率（QPS）：每秒成功处理的请求数，仅计算有效请求，是系统吞吐能力的重要指标 |
| `avg_response_time` | 秒 | sum(有效请求的response_time) / success_count | 平均响应时间：所有有效请求的平均响应时间，反映系统整体处理请求的速度 |
| `avg_first_token_latency` | 秒 | sum(有效请求的first_token_latency) / success_count | 平均首个token延迟：所有有效请求的平均首个token延迟，反映系统响应速度和用户感知的初始等待时间 |
| `avg_total_latency` | 秒 | sum(有效请求的total_latency) / success_count | 平均整句延迟：所有有效请求的平均整句延迟，衡量系统生成完整响应的平均时间 |
| `avg_tokens_per_second` | 个/秒 | sum(有效请求的tokens_per_second) / success_count | 平均生成速度：所有有效请求的平均token生成速率，衡量大模型生成内容的效率 |
| `max_response_time` | 秒 | max(有效请求的response_time) | 最长响应时间：所有有效请求中响应时间的最大值，反映系统在最坏情况下的性能 |
| `min_response_time` | 秒 | min(有效请求的response_time) | 最短响应时间：所有有效请求中响应时间的最小值，反映系统在最佳情况下的性能 |

## 5. 有效请求判定标准

请求被判定为有效需要满足以下所有条件：
1. 无错误信息 (`error` 字段为空)
2. 有返回内容 (`content` 字段非空)
3. 响应时间大于0 (`response_time` > 0)

如果有任一条件不满足，则请求被判定为无效，但仍会记录在结果文件中。

## 6. 输出文件格式

测试完成后会生成以下文件：

| 文件名 | 格式 | 说明 |
|-------|-----|------|
| `<test_id>.csv` | CSV | 测试结果摘要，包含所有聚合指标 |
| `<test_id>_details.csv` | CSV | 详细请求结果，包含每个请求的所有指标 |
| `<test_id>_errors.csv` | CSV | 错误请求详情，仅包含出错的请求 |
| `<test_id>_conversation_details.md` | Markdown | 对话详情，包含完整的提示词和回复内容 |

## 7. 命令行参数

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|-------|------|------|-------|------|
| `--config` | 字符串 | 是 | - | 配置文件路径 |
| `--output` | 字符串 | 否 | `test_result.csv` | 输出文件路径 |
| `--verbose` | 标志 | 否 | `false` | 打印详细日志 |
| `--single` | 标志 | 否 | `false` | 仅测试单个请求 |
| `--dynamic` | 标志 | 否 | `false` | 使用动态线程池模式 |
| `--active_threads` | 整数 | 否 | `0` | 动态线程池模式下的活跃线程数 |
| `--duration` | 整数 | 否 | `0` | 测试持续时间(秒) |

命令行参数优先级高于配置文件中的相同参数。