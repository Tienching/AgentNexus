---
name: ndb-data
description: 专门用于从NDB系统获取设备信息的技能。当需要查询设备信息时调用此技能，支持通过设备名称或IP地址查询设备的ID、类型、角色和管理IP等信息。
---

# NDB Data Skill

## 概述

这个Skill提供了从NDB(网络设备数据库)系统获取设备信息的专用工具。通过设备名称或IP地址查询设备的ID、类型、角色和管理IP等详细信息，为网络运维操作提供完整的设备数据支持。

## 使用场景

当需要获取设备信息时使用此Skill，包括：
- 网络故障诊断中需要设备标识符、类型和IP地址
- 配置管理前获取设备ID、类型、角色和管理IP
- 性能监控和数据采集前的设备识别和角色判断
- 与其他需要设备信息的系统集成（如link_data技能）
- 获取设备完整信息用于网络链路诊断和拓扑分析

## 核心功能

### 1. 认证管理
自动生成HMAC-SHA256认证头，包括：
- GMT时间戳生成
- 请求体SHA256摘要计算
- HMAC签名生成
- 完整的Authorization头部构建

### 2. 设备查询功能
#### 2.1 通过设备名称查询
- 支持单个设备查询
- 支持批量设备查询（逗号分隔）
- 自动返回设备的ID、类型、角色和管理IP

#### 2.2 通过IP地址查询
- 支持单个IP查询
- 支持批量IP查询（逗号分隔）
- 自动映射IP到设备并返回完整设备信息（包含类型和角色）

### 3. 结果处理
- 智能解析API响应
- 提取设备完整信息（ID、类型、角色、管理IP）
- 格式化输出结果
- 错误处理和异常管理

## 使用方法

### 命令行语法

```bash
python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py [options]
```

### 使用示例

#### 1. 通过设备名称查询devid
```bash
# 查询单个设备
python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "BJ-TX201-C03U05-IP49050-TCS9500-LC-159"

# 批量查询设备
python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "switch01,switch02,switch03"
```

#### 2. 通过IP地址查询devid
```bash
# 查询单个IP
python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "29.159.248.25" --ip

# 批量查询IP
python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "29.159.248.25,29.159.248.26" --ip
```

#### 3. 混合查询（不推荐，但支持）
```bash
# 如果某些条目是IP格式，会自动识别
python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "BJ-TX201-C03U05-IP49050-TCS9500-LC-159,29.159.248.25"
```

### 参数说明

#### 通用参数
- `-d, --devices`: 设备列表，用逗号分隔（必需）
- `--ip`: 强制标识设备列表为IP地址格式
- `--output`: 输出格式，支持 `json`（默认）和 `table`
- `--save-to-file`: 将结果保存到指定文件

#### 参数使用说明
- **设备名称模式**（默认）：直接使用设备名称，如 `BJ-TX201-C03U05-IP49050-TCS9500-LC-159`
- **IP地址模式**：添加 `--ip` 参数，如 `29.159.248.25 --ip`
- **批量操作**：多个设备用逗号分隔，如 `"switch01,switch02,switch03"`
- **智能识别**：如果不指定 `--ip`，脚本会尝试自动识别IP格式

### API配置

#### NDB API端点
- 查询设备信息: `http://ndb.ngate.tencent-cloud.com/config/network/device/get_device_info`

#### 请求格式
```json
{
    "devNames": [
        "HL-RB-5108-P10-TCS94R-GPULA-101"
    ],
    "resultColumn": [
        "id",
        "type",
        "levelName",
        "manageIp"
    ]
}
```

#### 响应格式
```json
{
    "returnCode": 0,
    "data": [
        {
            "id": 2146800,
            "type": "交换机",
            "manageIp": "11.243.252.201",
            "levelName": "内网GPU接入"
        }
    ],
    "success": true,
    "traceId": "98b03bd4af929c2d30be3302126fd170"
}
```

## 配置说明

### 认证配置
**重要：必须配置环境变量进行认证**

#### 方法1：配置环境变量（推荐）
```bash
# 设置环境变量
export HMAC_USERNAME='your_username'
export HMAC_SECRET='your_secret'

# 永久配置（添加到 ~/.bashrc 或 ~/.profile）
echo "export HMAC_USERNAME='your_username'" >> ~/.bashrc
echo "export HMAC_SECRET='your_secret'" >> ~/.profile
source ~/.bashrc
```

#### 方法2：通过参数传递（临时使用）
```python
collector = NDBDataCollector(
    username="your_username",
    secret="your_secret"
)
```

#### 环境变量优先级
1. 优先从环境变量 `HMAC_USERNAME` 和 `HMAC_SECRET` 读取
2. 如果环境变量未设置，使用参数传递的值
3. 如果都未设置，会抛出明确的错误提示

## 输出格式

### JSON格式（默认）
```json
{
    "success": true,
    "devices": [
        {
            "device": "HL-RB-5108-P10-TCS94R-GPULA-101",
            "id": 2146800,
            "type": "交换机",
            "levelName": "内网GPU接入",
            "manageIp": "11.243.252.201",
            "status": "found"
        }
    ],
    "total": 1,
    "traceId": "98b03bd4af929c2d30be3302126fd170",
    "timestamp": "2024-01-01 12:00:00"
}
```

### 表格格式
```
设备名称                            设备ID      类型      角色            管理IP           状态        TraceId
HL-RB-5108-P10-TCS94R-GPULA-101     2146800    交换机    内网GPU接入     11.243.252.201  found    98b03bd4af929c2d30be3302126fd170
```

## 错误处理

Skill包含完整的错误处理机制：
- 参数验证错误
- 网络请求异常
- 认证错误处理
- 设备未找到处理
- API响应格式错误

### 常见错误类型

1. **设备未找到**
   ```
   设备 'BJ-TX201-C03U05-IP49050-TCS9500-LC-159' 在系统中不存在
   ```

2. **认证失败**
   ```
   HMAC认证失败，请检查用户名和密钥
   ```

3. **网络连接错误**
   ```
   无法连接到NDB服务器，请检查网络连接
   ```

4. **API响应错误**
   ```
   API返回错误: returnCode=1, success=false
   ```

## 使用技巧

### 1. 批量查询优化
```bash
# 推荐：一次查询多个设备，减少API调用
python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "device1,device2,device3"
```

### 2. 结果保存
```bash
# 保存查询结果到文件
python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "switch01" --save-to-file device_ids.json
```

### 3. 脚本集成
```bash
# 在其他脚本中使用查询结果
DEVID=$(python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "switch01" --output json | jq -r '.devices[0].id')
DEVICE_TYPE=$(python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "switch01" --output json | jq -r '.devices[0].type')
DEVICE_LEVEL=$(python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "switch01" --output json | jq -r '.devices[0].levelName')
MANAGE_IP=$(python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "switch01" --output json | jq -r '.devices[0].manageIp')
echo "设备ID: $DEVID, 类型: $DEVICE_TYPE, 角色: $DEVICE_LEVEL, 管理IP: $MANAGE_IP"
```

## 注意事项

1. **执行方式**: 必须使用完整路径执行脚本
2. **设备标识**: 建议统一使用设备名称或IP地址，避免混合
3. **网络连接**: 确保能够访问NDB API端点
4. **权限要求**: 需要相应的设备查询权限
5. **批量限制**: 建议单次查询不超过50个设备
6. **缓存机制**: 可以考虑本地缓存设备信息（ID、名称、IP）以提高性能

## 故障排查

### 常见问题

1. **认证失败**
   - 检查环境变量是否正确设置
   - 验证用户名和密钥是否有效
   - 确认系统时间是否同步

2. **设备未找到**
   - 验证设备名称拼写是否正确
   - 确认设备是否已录入NDB系统
   - 尝试使用IP地址查询

3. **API响应错误**
   - 检查网络连接是否正常
   - 验证API端点是否可访问
   - 确认请求格式是否正确
   - 检查returnCode和success字段

4. **批量查询失败**
   - 减少单次查询的设备数量
   - 检查设备列表格式是否正确
   - 确认所有设备都存在于系统中

### 调试模式

可以通过添加 `--debug` 参数启用详细日志输出：
```bash
python ~/.claude-internal/skills/ndb-data/scripts/ndb_data_manager.py -d "switch01" --debug
```

## 性能优化

- 批量查询时建议合理分组，避免单次查询过多设备
- 可以考虑实现本地缓存机制
- 对于频繁查询的设备，建议缓存设备完整信息（ID、名称、IP）
- 合理设置请求超时时间，避免长时间等待
- 获取到的设备信息可以直接用于link_data技能的网络链路诊断