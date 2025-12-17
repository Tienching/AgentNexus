---
name: link-data
description: 专门用于网络链路诊断的技能，封装NOSGPT_LINK MCP工具，支持接入侧和互联侧网络链路故障诊断，自动调用ndb-data获取设备devid。当用户需要进行网络链路诊断、排查网络连接故障、检查设备间连通性时使用此技能。
---

# Link Data 网络链路诊断技能

## 概述

这个技能封装了NOSGPT_LINK MCP工具，提供网络链路诊断功能。支持接入侧（交换机到服务器）和互联侧（设备间）的网络链路故障诊断，能够自动解析设备名称获取devid，并生成详细的诊断报告。

## 核心功能

### 🔍 接入侧链路诊断
诊断交换机到服务器之间的网络连接状态，支持多种参数组合：
- 本地设备信息 + 服务器信息（完整诊断）
- 仅本地设备信息（自动查询拓扑获取服务器信息）
- 仅服务器信息（自动查询拓扑获取设备信息）

### 🔗 互联侧链路诊断
诊断设备与设备之间的网络连接状态，支持多种参数组合：
- 本地设备 + 连接设备（完整诊断）
- 仅本地设备信息
- 仅连接设备信息

### 🆔 自动设备解析
- 自动调用ndb-data技能获取设备devid、类型、角色和管理IP
- 支持设备名称和IP地址自动识别
- 智能参数映射和转换
- **智能接口选择**：根据设备levelName自动选择接入侧或互联侧诊断接口
  - 如果levelName包含"接入"，使用接入侧接口（access）
  - 如果levelName不包含"接入"或为空，使用互联侧接口（interconnect）

## 使用场景

**典型用户请求：**
- "诊断设备CQ-TH-M3103-Z16-TCS84-LA100G-001端口Ethernet4到服务器11.241.48.30的网络链路"
- "检查交换机BJ-TX201-C03U05-IP49050-TCS9500-LC-159和核心交换机之间的连接"
- "服务器192.168.1.100无法访问，请检查网络链路"
- "诊断设备间光纤连接问题"

## 执行流程

### 步骤1: 解析用户请求
识别诊断类型（接入侧/互联侧）和关键参数：
- 设备名称/IP地址
- 端口名称
- 服务器信息
- 网卡名称

### 步骤2: 设备信息解析与接口选择
如果用户提供的是设备名称而非设备ID，需要先调用ndb-data技能获取设备信息：
```
1. 调用 Skill('ndb-data') 获取设备完整信息（id, type, levelName, manageIp）
2. 根据levelName智能选择诊断接口：
   - 如果levelName包含"接入" -> 使用接入侧接口
   - 否则 -> 使用互联侧接口
3. 进行链路诊断
```

### 步骤3: 构建诊断参数
根据用户输入和解析的设备信息，构建相应的MCP调用参数。

### 步骤4: 执行链路诊断
根据诊断类型调用相应的MCP工具：
- 接入侧：`mcp__NOSGPT_LINK__link_diagnosis_with_access_generic`
- 互联侧：`mcp__NOSGPT_LINK__link_diagnosis_with_interconnect_generic`

### 步骤5: 结果处理和报告
格式化诊断结果，生成用户友好的诊断报告。

## MCP工具调用

### 接入侧诊断
```python
mcp__NOSGPT_LINK__link_diagnosis_with_access_generic(
    ticket_create_time="2025-01-21 14:30:00",
    inspect_minutes=30,
    local_device_id=2421658,
    local_port_name="Ethernet4",
    server_ip="11.241.48.30",
    eth_name="eth7"
)
```

### 互联侧诊断
```python
mcp__NOSGPT_LINK__link_diagnosis_with_interconnect_generic(
    ticket_create_time="2025-01-21 14:30:00",
    inspect_minutes=30,
    local_device_id=2421658,
    local_port_name="Ethernet96",
    connect_device_id=2421659,
    connect_port_name="Ethernet32"
)
```

### 系统状态查询
```python
mcp__NOSGPT_LINK__system_status()
```

## 参数说明

### 时间参数
- `ticket_create_time`: 诊断结束时间，格式 "YYYY-MM-DD HH:MM:SS"
- `inspect_minutes`: 诊断时长（分钟），默认30分钟

### 设备参数
- `local_device_name/local_device_id`: 本地设备名称或ID
- `local_port_name`: 本地端口名称，如 "Ethernet4"
- `connect_device_name/connect_device_id`: 连接设备名称或ID
- `connect_port_name`: 连接端口名称

### 服务器参数
- `server_ip`: 服务器管理IP地址
- `server_asset`: 服务器资产编号
- `eth_name`: 服务器网卡名称，如 "eth7"

### 可选参数
- `wechat_id_list`: WeChat ID列表（用于通知）
- `alarm_id`: 告警ID

## 使用方式

当用户请求网络链路诊断时：

1. **识别诊断类型**：根据描述判断是接入侧还是互联侧
2. **提取关键参数**：设备名称、端口、服务器信息等
3. **调用ndb-data**：获取设备完整信息（id, type, levelName, manageIp）
4. **智能接口选择**：
   ```python
   # 根据levelName选择接口
   if "接入" in device_info.get('levelName', ''):
       # 接入侧诊断：适用于接入层交换机
       mcp__NOSGPT_LINK__link_diagnosis_with_access_generic(...)
   else:
       # 互联侧诊断：适用于核心层、汇聚层设备
       mcp__NOSGPT_LINK__link_diagnosis_with_interconnect_generic(...)
   ```
5. **构建MCP调用**：选择合适的工具和参数
6. **执行诊断**：调用MCP工具
7. **格式化结果**：生成易读的诊断报告

## 注意事项

- 设备名称和IP地址会自动识别并转换为devid
- 至少需要提供设备端信息或服务器端信息之一
- 支持部分参数输入，系统会自动查询拓扑补全信息
- **智能接口选择逻辑**：
  - `levelName`包含"接入"（如"万兆内网接入"、"内网GPU接入"）→ 使用接入侧接口
  - `levelName`不包含"接入"（如核心层、汇聚层设备）→ 使用互联侧接口
- 诊断结果包含详细的链路状态、错误信息和建议处理方案
- 建议提供具体的端口名称以提高诊断精度

## 接口选择示例

### 接入侧诊断示例
```python
# 设备信息：levelName="万兆内网接入"
# 使用接入侧接口
mcp__NOSGPT_LINK__link_diagnosis_with_access_generic(
    ticket_create_time="2025-01-21 14:30:00",
    inspect_minutes=30,
    local_device_id=2823200,  # BJ-LS-M106-E04-TCS82H-LA-004
    local_port_name="Ethernet4",
    server_ip="11.241.48.30",
    eth_name="eth7"
)
```

### 互联侧诊断示例
```python
# 设备信息：levelName="核心汇聚"
# 使用互联侧接口
mcp__NOSGPT_LINK__link_diagnosis_with_interconnect_generic(
    ticket_create_time="2025-01-21 14:30:00",
    inspect_minutes=30,
    local_device_id=2146800,  # 核心设备
    local_port_name="Ethernet96",
    connect_device_id=2146801,
    connect_port_name="Ethernet32"
)
```
