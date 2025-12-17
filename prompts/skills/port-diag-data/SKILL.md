---
name: port-diag-data
description: 专门用于端口诊断数据采集的技能。该技能可以对指定设备的端口进行诊断数据获取，返回数据包含：端口映射信息、端口邻居信息、端口diag信息、光模块信息、端口在位信息、端口linkchange信息等。用于网络端口故障排查和性能分析。注意：分析日志中的端口问题时，需要先获取端口映射信息来关联BCM/PHY层的端口号。
---

# Port Diag Data Skill

## 功能说明

该技能用于调用 SCF (Serverless Cloud Function) API 对网络设备端口进行诊断数据采集。支持：

- 对指定设备和端口进行诊断数据 dump
- 支持同步和异步请求模式
- 自动处理 HMAC-SHA512 签名认证

## 环境变量配置

在使用前，请确保以下环境变量已配置：

- `SCF_APPKEY`: SCF API 的应用密钥
- `SCF_URL`: SCF API 的服务地址
- `SCF_SYSTEM`: 系统ID

## 使用方法

### 基本用法

```bash
python ~/.codebuddy-code/skills/port-diag-data/scripts/port_diag_data.py -d <设备IP或名称> -i <接口名称>
```

### 参数说明

| 参数 | 简写 | 必填 | 说明 |
|------|------|------|------|
| --device | -d | 是 | 设备IP地址或设备名称 |
| --interface | -i | 是 | 接口名称，如 Eth200GE128 |
| --business | -b | 否 | 业务标识，默认为 "diag" |
| --operator | -o | 否 | 操作者名称，默认为 "claude" |
| --mode | -m | 否 | 请求模式：sync（同步）或 async（异步），默认为 sync |
| --type | -t | 否 | 输出类型：simple/normal/deep，默认为 normal |

### 输出类型说明

| 类型 | 说明 |
|------|------|
| simple | 仅返回 port_mappings 部分 |
| normal | 返回 port_mappings 和 diagnosis_results（排除 bcm_phy 和 hexdump_eeprom） |
| deep | 返回完整数据（包含 bcm_phy 和 hexdump_eeprom） |

### 示例

```bash
# 同步诊断端口（默认 normal 类型）
python ~/.codebuddy-code/skills/port-diag-data/scripts/port_diag_data.py -d 10.253.49.151 -i Eth200GE128

# 仅获取端口映射信息（simple 类型）
python ~/.codebuddy-code/skills/port-diag-data/scripts/port_diag_data.py -d 10.253.49.151 -i Eth200GE128 -t simple

# 获取完整诊断数据（deep 类型，包含 bcm_phy 和 hexdump_eeprom）
python ~/.codebuddy-code/skills/port-diag-data/scripts/port_diag_data.py -d 10.253.49.151 -i Eth200GE128 -t deep

# 异步诊断端口，指定业务和操作者
python ~/.codebuddy-code/skills/port-diag-data/scripts/port_diag_data.py -d 10.253.49.151 -i Eth200GE128 -b test -o jonaszchen -m async

# 使用设备名称
python ~/.codebuddy-code/skills/port-diag-data/scripts/port_diag_data.py -d "SH-FX-2202-F15-TCS84R-LA100G-015" -i Ethernet0
```

## 返回结果

脚本会输出 API 的响应结果，包括诊断任务的状态和数据。

## 端口映射说明

### 不同层次的端口命名

在 SONiC 设备中，不同层次使用不同的端口命名方式：

| 层次 | 端口标识 | 示例 | 说明 |
|------|---------|------|------|
| 用户层 | port_name | Ethernet0, Eth200GE128 | 用户可见的接口名称 |
| SDK/BCM 层 | logical_port | Port 87 | BCM/BRCM 日志中使用 |
| PHY 层 | physical_port | phy 85 | 物理层诊断信息中使用 |

### logical_port - BCM/BRCM 日志

当在 BCM/BRCM 相关日志中看到端口号时，对应的是 `logical_port`：

```
# BCM 日志示例
Port 87 link down
```

这里的 `Port 87` 对应 `port_mappings` 中 `logical_port` 为 `87` 的端口。

### physical_port - PHY 层诊断

当在 PHY 层诊断信息中看到端口号时，对应的是 `physical_port`：

```
# PHY 诊断示例（本技能返回结果）
phy 85 *
```

这里的 `phy 85` 对应 `port_mappings` 中 `physical_port` 为 `85` 的端口。

### 如何查找端口对应关系

1. 使用 `simple` 类型获取端口映射：
   ```bash
   python ~/.codebuddy-code/skills/port-diag-data/scripts/port_diag_data.py -d <设备> -i <接口> -t simple
   ```

2. 在返回的 `port_mappings` 中查找对应关系：
   ```json
   {
     "logical_port": 87,
     "physical_port": 85,
     "port_name": "Ethernet0"
   }
   ```

3. 端口对应关系示例：
   - BCM 日志 `Port 87 link down` → `logical_port: 87` → `Ethernet0`
   - PHY 诊断 `phy 85 *` → `physical_port: 85` → `Ethernet0`
