# -*- coding: utf-8 -*-
"""
进程管理器

负责 PID 文件管理、进程启动/停止、状态检查。
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Dict, Any


class ProcessManager:
    """进程管理器
    
    管理 anexus 服务进程的启动、停止和状态检查。
    """
    
    DEFAULT_PID_FILE = "logs/anexus.pid"
    DEFAULT_LOG_FILE = "logs/anexus.log"
    
    def __init__(
        self,
        pid_file: Optional[Path] = None,
        log_file: Optional[Path] = None,
        base_dir: Optional[Path] = None,
    ):
        """初始化进程管理器
        
        Args:
            pid_file: PID 文件路径，默认为 logs/anexus.pid
            log_file: 日志文件路径，默认为 logs/anexus.log
            base_dir: 项目根目录，默认为当前工作目录
        """
        self.base_dir = base_dir or Path.cwd()
        self.pid_file = pid_file or (self.base_dir / self.DEFAULT_PID_FILE)
        self.log_file = log_file or (self.base_dir / self.DEFAULT_LOG_FILE)
        
        # 确保日志目录存在
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
    
    def get_pid(self) -> Optional[int]:
        """获取 PID 文件中的进程 ID
        
        Returns:
            进程 ID，如果不存在或无效则返回 None
        """
        if not self.pid_file.exists():
            return None
        
        try:
            content = self.pid_file.read_text().strip()
            return int(content) if content else None
        except (ValueError, OSError):
            return None
    
    def write_pid(self, pid: int) -> None:
        """写入 PID 到文件
        
        Args:
            pid: 进程 ID
        """
        self.pid_file.write_text(str(pid))
    
    def remove_pid(self) -> None:
        """删除 PID 文件"""
        if self.pid_file.exists():
            self.pid_file.unlink()
    
    def is_running(self) -> bool:
        """检查服务是否正在运行
        
        Returns:
            True 如果服务正在运行
        """
        pid = self.get_pid()
        if pid is None:
            return False
        
        return self._process_exists(pid)
    
    def _process_exists(self, pid: int) -> bool:
        """检查进程是否存在
        
        Args:
            pid: 进程 ID
            
        Returns:
            True 如果进程存在
        """
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    
    def get_process_info(self, pid: int) -> Optional[Dict[str, Any]]:
        """获取进程详细信息
        
        Args:
            pid: 进程 ID
            
        Returns:
            包含进程信息的字典，如果进程不存在返回 None
        """
        if not self._process_exists(pid):
            return None
        
        info = {"pid": pid}
        
        try:
            # 尝试使用 psutil 获取更详细的信息
            import psutil
            proc = psutil.Process(pid)
            info.update({
                "name": proc.name(),
                "status": proc.status(),
                "cpu_percent": proc.cpu_percent(),
                "memory_mb": proc.memory_info().rss / 1024 / 1024,
                "create_time": proc.create_time(),
                "cmdline": " ".join(proc.cmdline()),
            })
        except ImportError:
            # psutil 不可用，使用 /proc 文件系统（Linux）
            proc_dir = Path(f"/proc/{pid}")
            if proc_dir.exists():
                # 读取命令行
                cmdline_file = proc_dir / "cmdline"
                if cmdline_file.exists():
                    cmdline = cmdline_file.read_bytes().decode().replace("\x00", " ").strip()
                    info["cmdline"] = cmdline
                
                # 读取状态
                status_file = proc_dir / "status"
                if status_file.exists():
                    for line in status_file.read_text().splitlines():
                        if line.startswith("State:"):
                            info["status"] = line.split(":")[1].strip()
                        elif line.startswith("VmRSS:"):
                            # 内存使用（KB）
                            mem_kb = int(line.split(":")[1].strip().split()[0])
                            info["memory_mb"] = mem_kb / 1024
        except Exception:
            pass
        
        return info
    
    def start_foreground(
        self,
        host: str = "0.0.0.0",
        port: int = 8081,
        reload: bool = False,
    ) -> int:
        """前台启动服务
        
        Args:
            host: 绑定地址
            port: 监听端口
            reload: 是否启用热重载
            
        Returns:
            退出码
        """
        cmd = [
            sys.executable, "-m", "uvicorn",
            "src.server.app:app",
            "--host", host,
            "--port", str(port),
        ]
        
        if reload:
            cmd.append("--reload")
        
        # 前台运行，使用 exec 替换当前进程
        try:
            os.chdir(self.base_dir)
            os.execvp(cmd[0], cmd)
        except OSError as e:
            print(f"❌ 启动失败: {e}")
            return 1
        
        return 0  # 不会执行到这里
    
    def start_background(
        self,
        host: str = "0.0.0.0",
        port: int = 8081,
        workers: int = 1,
        env: Optional[Dict[str, str]] = None,
    ) -> int:
        """后台启动服务
        
        Args:
            host: 绑定地址
            port: 监听端口
            workers: Worker 进程数
            env: 额外的环境变量
            
        Returns:
            启动的进程 PID，失败返回 -1
        """
        if self.is_running():
            pid = self.get_pid()
            print(f"⚠️  服务已在运行中 (PID: {pid})")
            return -1
        
        cmd = [
            sys.executable, "-m", "uvicorn",
            "src.server.app:app",
            "--host", host,
            "--port", str(port),
            "--workers", str(workers),
        ]
        
        # 准备环境变量
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        
        # 确保日志目录存在
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # 后台启动，重定向输出到日志文件
            with open(self.log_file, "a") as log_f:
                process = subprocess.Popen(
                    cmd,
                    cwd=self.base_dir,
                    env=process_env,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,  # 脱离终端
                )
            
            # 写入 PID
            self.write_pid(process.pid)
            
            # 等待一小段时间确认进程启动成功
            time.sleep(0.5)
            if not self._process_exists(process.pid):
                self.remove_pid()
                return -1
            
            return process.pid
            
        except Exception as e:
            print(f"❌ 启动失败: {e}")
            return -1
    
    def stop_process(self, force: bool = False, timeout: int = 10) -> bool:
        """停止服务进程
        
        Args:
            force: 是否强制停止（SIGKILL）
            timeout: 等待超时时间（秒）
            
        Returns:
            True 如果成功停止
        """
        pid = self.get_pid()
        if pid is None:
            print("⚠️  没有找到正在运行的服务")
            return False
        
        if not self._process_exists(pid):
            print(f"⚠️  PID 文件存在但进程 {pid} 不存在，清理 PID 文件")
            self.remove_pid()
            return True
        
        try:
            # 发送信号
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)
            
            # 等待进程结束
            for _ in range(timeout * 10):
                if not self._process_exists(pid):
                    break
                time.sleep(0.1)
            else:
                # 超时，强制杀死
                if not force:
                    print(f"⚠️  优雅停止超时，强制终止进程 {pid}")
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.5)
            
            # 清理 PID 文件
            self.remove_pid()
            return True
            
        except ProcessLookupError:
            # 进程已不存在
            self.remove_pid()
            return True
        except PermissionError:
            print(f"❌ 没有权限停止进程 {pid}")
            return False
        except Exception as e:
            print(f"❌ 停止进程失败: {e}")
            return False
    
    def find_processes_by_name(self, name: str = "uvicorn") -> List[Dict[str, Any]]:
        """按名称查找进程
        
        Args:
            name: 进程名称关键字
            
        Returns:
            匹配进程的信息列表
        """
        processes = []
        
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    if name.lower() in proc.name().lower():
                        processes.append({
                            "pid": proc.pid,
                            "name": proc.name(),
                            "cmdline": " ".join(proc.cmdline() or []),
                        })
                    elif proc.cmdline() and any(name.lower() in arg.lower() for arg in proc.cmdline()):
                        processes.append({
                            "pid": proc.pid,
                            "name": proc.name(),
                            "cmdline": " ".join(proc.cmdline() or []),
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            # psutil 不可用，使用 pgrep
            try:
                result = subprocess.run(
                    ["pgrep", "-f", name],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    for pid_str in result.stdout.strip().split("\n"):
                        if pid_str:
                            pid = int(pid_str)
                            info = self.get_process_info(pid)
                            if info:
                                processes.append(info)
            except Exception:
                pass
        
        return processes
