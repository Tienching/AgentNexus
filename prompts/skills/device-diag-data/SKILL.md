---
name: device-diag-data
description: 当用户请求采集、收集或下载网络设备的诊断信息(diag文件)时使用此技能。diag包包含设备的运行日志、sairedis.rec、swss.rec、dmesg等系统运行记录，可用于故障排查和问题分析。它能够自动化创建诊断任务、监控任务状态，并为指定IP地址或设备名的设备下载结果文件。
---

# Device Diag Data Skill

## 概述

这个Skill提供了完整的设备诊断数据管理工具，支持四种操作模式：创建任务、查询任务、下载任务以及一体化操作。通过命令行参数可以动态切换不同的功能模式，实现灵活的设备诊断信息采集。

## 智能获取策略（重要）

为了避免重复下载和减少不必要的任务创建，**在获取设备诊断数据时必须按以下优先级顺序执行**：

### 优先级 1：检查本地已有文件
首先检查当前工作目录是否已存在该设备的 diag tar 包：

```bash
# 检查本地是否有该设备的 tar.gz 文件
ls -la *<设备名>*.tar.gz 2>/dev/null
```

**如果找到本地文件**：
- 直接使用该文件，无需下载
- 告知用户："已找到本地诊断文件: <文件名>，将直接使用"

### 优先级 2：查询远程今日任务
如果本地没有文件，查询远程是否有今天内完成的任务：

```bash
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py query -d "<设备名>"
```

**检查返回结果中的 `createTime` 字段**：
- 如果任务创建时间是**今天**（与当前日期相同），且有 `resultFileUrl`
- 则使用 `download` 命令下载该文件：
  ```bash
  python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py download -u "<resultFileUrl>"
  ```
- 告知用户："发现今天已有的诊断任务，正在下载..."

### 优先级 3：创建新任务
只有在以下情况才创建新任务：
1. 本地没有该设备的 tar 包
2. 远程没有今天内完成的任务
3. **或者用户明确要求获取最新/实时的诊断数据**（如用户说"重新采集"、"获取最新的"、"刷新diag"等）

```bash
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py all -d "<设备名>"
```

### 判断逻辑流程图

```
开始获取设备 X 的 diag 数据
        │
        ▼
┌─────────────────────────────┐
│ 用户是否要求"最新/重新采集"？ │
└─────────────────────────────┘
        │
    是 ─┼─ 否
        │   │
        ▼   ▼
   创建新任务  检查本地文件
   (all命令)      │
                  ▼
          ┌──────────────┐
          │ 本地有tar包？ │
          └──────────────┘
                  │
              是 ─┼─ 否
                  │   │
                  ▼   ▼
             使用本地  查询远程任务
               文件      │
                         ▼
                 ┌────────────────┐
                 │ 有今日完成任务？│
                 └────────────────┘
                         │
                     是 ─┼─ 否
                         │   │
                         ▼   ▼
                    下载远程  创建新任务
                      文件   (all命令)
```

## 使用场景

当需要批量采集网络设备的诊断信息时使用此Skill，包括：
- 设备故障排查时的信息收集
- 网络运维中的例行检查
- 设备状态监控和数据分析
- 批量设备配置备份前的信息采集

## 核心功能

### 1. 认证管理
自动生成HMAC-SHA256认证头，包括：
- GMT时间戳生成
- 请求体SHA256摘要计算
- HMAC签名生成
- 完整的Authorization头部构建

### 2. 四种操作模式

#### 2.1 创建任务 (create)
- 支持IP地址和设备名称两种设备标识方式
- 自定义工具参数配置
- 自动保存任务ID到本地文件

#### 2.2 查询任务 (query)
- 智能任务状态查询
- 显示任务详细信息（ID、设备、状态、创建时间等）
- 自动提取结果下载链接

#### 2.3 下载任务 (download)
- 通过URL直接下载诊断文件
- 智能文件名处理和URL解码
- 本地路径管理

#### 2.4 一体化操作 (all)
- 完整的诊断信息采集自动化流程
- 创建任务 → 等待完成 → 下载文件
- 智能轮询机制和超时控制

## 使用方法

### 命令行语法

```bash
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py <command> [options]
```

### 可用命令

#### 1. 创建任务
```bash
# 使用IP地址创建任务
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py create -d "29.159.248.25" --ip

# 使用设备名称创建任务（默认方式，无需--name参数）
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py create -d "WH-XHZD-101-B08-TCS94R-GPULC-015"

# 批量设备创建任务
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py create -d "switch01,switch02"

# 带自定义参数创建任务
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py create -d "29.159.248.25" --ip --tool-params '{"key1":"value1"}'
```

#### 2. 查询任务
```bash
# 查询IP地址的任务状态
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py query -d "29.159.248.25" --ip

# 查询设备名称的任务状态（默认方式）
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py query -d "WH-XHZD-101-B08-TCS94R-GPULC-015"

# 查询所有成功任务
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py query
```

#### 3. 下载文件
```bash
# 下载最新任务的文件（推荐）
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py download

# 下载特定设备的任务文件
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py download -d "WH-XHZD-101-B08-TCS94R-GPULC-015"

# 下载IP地址设备的任务文件
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py download -d "29.159.248.25" --ip
```

#### 4. 一体化操作
```bash
# 使用设备名称进行完整采集（推荐，默认方式）
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py all -d "WH-XHZD-101-B08-TCS94R-GPULC-015"

# 使用IP地址进行完整采集
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py all -d "29.159.248.25" --ip

# 批量设备完整采集
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py all -d "switch01,switch02"

# 带自定义参数的完整采集
python ~/.codebuddy-code/skills/device-diag-data/scripts/device_diag_manager.py all -d "29.159.248.25" --ip --tool-params '{"custom":"value"}'
```

### 参数说明

#### 通用参数
- `-d, --devices`: 设备列表，用逗号分隔（必需）
- `--ip`: 标识设备列表为IP地址（默认为设备名称，无需指定--name）
- `--tool-params`: 工具参数JSON字符串（可选）

#### 参数使用说明
- **设备名称模式**（默认）：直接使用设备名称，如 `WH-XHZD-101-B08-TCS94R-GPULC-015`
- **IP地址模式**：添加 `--ip` 参数，如 `29.159.248.25 --ip`
- **批量操作**：多个设备用逗号分隔，如 `"switch01,switch02,switch03"`

### 宏定义配置

脚本已预定义以下配置，无需手动指定：
- 默认工具类型: `diag信息采集`
- 默认操作员: `jonaszchen`
- 默认输出路径: `./` (当前目录)
- 默认查询状态: `成功`
- 默认分页: 第1页，每页10条
- 默认最大等待时间: 300秒

## 配置说明

### 认证配置
**重要：不再使用硬编码认证信息，必须配置环境变量**

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
collector = DeviceDiagCollector(
    username="your_username",
    secret="your_secret"
)
```

#### 环境变量优先级
1. 优先从环境变量 `HMAC_USERNAME` 和 `HMAC_SECRET` 读取
2. 如果环境变量未设置，使用参数传递的值
3. 如果都未设置，会抛出明确的错误提示

### API端点配置
- 创建任务: `http://operus.ngate.tencent-cloud.com/operus/operation/tools/createTask`
- 查询任务: `http://operus.ngate.tencent-cloud.com/operus/operation/tools/queryTask`

## 错误处理

Skill包含完整的错误处理机制：
- 参数验证错误
- 网络请求异常
- 任务超时处理
- 文件下载失败
- 认证错误处理

所有错误都会抛出包含详细信息的异常，便于调试和问题定位。

## 输出文件

### 任务ID文件
创建任务成功后，会自动生成 `task_id_<任务ID>.txt` 文件保存任务ID，方便后续查询操作。

### 诊断文件
下载的诊断文件会保存在当前目录（或指定目录），文件名格式为：
- `<设备名>_<时间戳>.tar.gz` (如果能从URL解析)
- `diag_result_<时间戳>.tar.gz` (默认格式)

## 注意事项

1. **执行方式**: 必须使用完整路径执行脚本，不支持cd切换目录后执行
2. **设备标识**: 只能使用IP或设备名中的一种，不能同时提供
3. **网络连接**: 确保能够访问API端点
4. **权限要求**: 需要相应的设备访问权限
5. **存储空间**: 确保有足够的磁盘空间存储下载的诊断文件
6. **并发控制**: 避免同时创建过多任务导致系统负载过高

## 故障排查

### 常见问题

1. **认证失败**
   - 检查用户名和密钥是否正确
   - 验证系统时间是否同步
   - 确认请求格式是否正确

2. **系统繁忙错误 (SYSTEM ERROR: system busy)**
   - 检查网络连接是否正常
   - 等待片刻后重试
   - 确保请求头中只包含必要的认证信息

3. **任务超时**
   - 检查网络连接稳定性
   - 确认目标设备状态正常
   - 默认等待时间为300秒，如需更长等待时间可修改代码中的 `DEFAULT_MAX_WAIT` 常量

4. **下载失败**
   - 检查结果URL是否有效
   - 确认本地存储路径权限
   - 验证磁盘空间是否充足

### 调试模式

可以通过查看详细输出来进行调试，脚本会自动打印详细的执行过程和错误信息。

## 性能优化

- 批量处理多个设备时，建议分批执行
- 合理设置轮询间隔，避免过于频繁的查询
- 对于大型网络，考虑使用异步处理提高效率