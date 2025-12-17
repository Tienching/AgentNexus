---
name: syslog-data
description: 专门用于从NOSGPT_SYSLOG系统获取设备日志信息的技能。该技能通过MCP工具查询SONiC设备的系统日志，支持按时间范围、主机名、进程名、接口名等条件过滤，用于网络故障诊断和问题排查。
---

# Syslog Data Retrieval Skill

这是一个专门用于从NOSGPT_SYSLOG系统获取设备日志信息的技能。该技能**直接使用MCP工具**查询SONiC设备的系统日志，支持按时间范围、主机名、进程名、接口名等条件过滤，用于网络故障诊断和问题排查。

## 重要说明

**本技能使用MCP工具进行日志查询，不使用任何脚本文件。** 所有日志查询操作通过以下MCP工具完成：

- `mcp__NOSGPT_SYSLOG__SearchLog` - 搜索日志（主要工具）
- `mcp__NOSGPT_SYSLOG__GetCurrentTimestamp` - 获取当前时间戳
- `mcp__NOSGPT_SYSLOG__LogClassify` - 日志分类
- `mcp__NOSGPT_SYSLOG__GetEsFields` - 获取ES字段信息
- `mcp__NOSGPT_SYSLOG__QueryClickhouse` - 查询Clickhouse存储
- `mcp__NOSGPT_SYSLOG__ExtractAndAggregate` - 提取并聚合日志数据

## 使用方法

1. **调用技能**，告诉我要查询什么日志
2. **提供查询参数**（时间范围、设备名、进程名等）
3. **直接调用MCP工具获取系统日志信息**

## 核心功能

- **时间范围查询**: 支持精确的时间范围过滤
- **主机过滤**: 按设备主机名过滤日志
- **进程过滤**: 按进程名过滤（如bgpd、teamd、syncd等）
- **接口过滤**: 按网络接口名过滤相关日志
- **关键词搜索**: 支持自定义关键词搜索
- **时间获取**: 使用MCP工具或系统命令获取当前时间

## 支持的日志类型

- **路由协议日志**: BGP、OSPF、ISIS等路由协议相关
- **接口状态日志**: 网络接口up/down、状态变更
- **系统进程日志**: 各系统进程的运行状态和错误信息
- **配置变更日志**: 配置修改、保存、应用等相关日志
- **硬件故障日志**: 硬件故障、告警等相关信息

## 使用示例

```
查询CQ-TH-M3103-Z16-TCS84-LA100G-001设备最近2小时的BGP相关日志
```

```
搜索11.241.48.30设备Ethernet4接口相关的所有日志
```

```
查询昨天下午3点到5点CQ-TH-M3103-Z16-TCS84-LA100G-001设备的bgpd进程日志
```

```
搜索11.241.48.30设备包含"ERR"关键词的最近1小时日志
```

```
查询指定时间范围内teamd进程在CQ-TH-M3103-Z16-TCS84-LA100G-001设备上的日志
```

## 技能工作流程

1. **理解用户查询需求**（时间范围、设备、进程、关键词等）
2. **识别设备标识类型**：
   - 如果用户提供的是设备名称（如CQ-TH-M3103-Z16-TCS84-LA100G-001），使用`devName`字段
   - 如果用户提供的是IP地址（如11.241.48.30），使用`dev_ip`字段
3. 获取当前时间（如需要相对时间查询）
4. 构建ES lucene DSL查询条件
5. 调用NOSGPT_SYSLOG.SearchLog获取日志
6. 格式化并返回查询结果

## 执行指令

当用户请求查询系统日志时：

1. **时间参数处理**:
   - 使用系统命令获取当前时间，如 `date '+%Y-%m-%dT%H:%M:%S+08:00'`
   - 时间格式转换为RFC3339: "2025-08-04T14:16:04+08:00"
   - 处理相对时间描述（如"最近2小时"）

2. **查询条件构建**:
   - 设备名: `{"match":{"devName":"CQ-TH-M3103-Z16-TCS84-LA100G-001"}}`
   - 设备IP: `{"match":{"dev_ip":"11.241.48.30"}}`
   - 进程名: `{"match":{"process_name":"bgpd"}}`
   - 接口名: `{"match":{"interface_name":"Ethernet4"}}`
   - ERR关键词: `{"match":{"rawstring":"ERR"}}`
   - 通用关键词: `{"match":{"rawstring":"error"}}`

3. **ES查询构建**:
   ```json
   // 按设备名查询
   {
     "query": {
       "bool": {
         "must": [
           {"match":{"devName":"CQ-TH-M3103-Z16-TCS84-LA100G-001"}},
           {"match":{"rawstring":"ERR"}}
         ]
       }
     }
   }
   ```
   ```json
   // 按设备IP查询
   {
     "query": {
       "bool": {
         "must": [
           {"match":{"dev_ip":"11.241.48.30"}},
           {"match":{"rawstring":"ERR"}}
         ]
       }
     }
   }
   ```

4. **MCP工具调用**:
   - 使用 `mcp__NOSGPT_SYSLOG__GetCurrentTimestamp` 或系统命令获取当前时间
   - 使用 `mcp__NOSGPT_SYSLOG__SearchLog` 搜索日志

5. **结果格式化**:
   - 时间戳转换和排序
   - 关键信息提取（主机、进程、消息内容）
   - 日志统计和摘要

## 重要参数说明

- **start_time/end_time**: RFC3339格式，如"2025-08-04T14:16:04+08:00"
- **index_name_list**: 固定为"syslog"
- **json_content**: ES lucene DSL查询语句
- **时间处理**: 支持相对时间描述，自动转换为RFC3339格式

## 常用进程名参考

- **bgpd**: BGP路由协议进程
- **teamd**: Link Aggregation Control Protocol进程
- **syncd**: Switch ASIC同步进程
- **swss**: Switch State Service进程
- **orchagent**: Orchestration Agent进程
- **dhcpmon**: DHCP监控进程
- **lldpd**: LLDP协议进程

## 注意事项

- 时间格式必须是RFC3339标准
- index_name_list固定为"syslog"
- **设备查询字段选择**：
  - 设备名称使用`devName`字段，不是`hostname`字段
  - 设备IP地址使用`dev_ip`字段
- **ERR级别日志查询使用rawstring字段匹配"ERR"关键词**
- 支持复杂的ES查询条件组合
- 查询结果按时间倒序排列
- 建议合理设置时间范围以避免查询超时

## 时间范围处理示例

- "最近1小时"：当前时间往前推1小时
- "最近4小时"：当前时间往前推4小时
- "最近1天"：当前时间往前推24小时
- "昨天"：昨天的00:00:00到23:59:59

每次查询前必须先使用系统命令获取准确当前时间（如 `date '+%Y-%m-%dT%H:%M:%S+08:00'`），然后根据用户描述的时间范围计算start_time和end_time。
