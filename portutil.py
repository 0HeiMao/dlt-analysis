"""端口与进程工具：纯标准库，无外部命令依赖。

在 Windows 上用 ctypes 直接调用 iphlpapi.dll / kernel32.dll，避免依赖
PATH 中的 netstat / taskkill 等外部命令（Git Bash 环境下继承的 PATH 是
POSIX 风格，Windows 的 CreateProcess 不识别，会导致 netstat 找不到而误报
端口无监听）。

非 Windows 平台（sys.platform != "win32"）下，listener_pids 返回 []，
kill_pids 为空操作，port_open 照常可用，import / 调用均不会炸 ctypes 错误。
"""

import ctypes
import socket
import sys

__all__ = ["listener_pids", "port_open", "kill_pids"]

AF_INET = 2
TCP_TABLE_OWNER_PID_ALL = 5
MIB_TCP_STATE_LISTEN = 2
PROCESS_TERMINATE = 0x0001


class _MIB_TCPROW_OWNER_PID(ctypes.Structure):
    # 6 个 DWORD，结构体大小 24 字节，与 GetExtendedTcpTable 返回的表布局一致。
    _fields_ = [
        ("dwState", ctypes.wintypes.DWORD),
        ("dwLocalAddr", ctypes.wintypes.DWORD),
        ("dwLocalPort", ctypes.wintypes.DWORD),
        ("dwRemoteAddr", ctypes.wintypes.DWORD),
        ("dwRemotePort", ctypes.wintypes.DWORD),
        ("dwOwningPid", ctypes.wintypes.DWORD),
    ]


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    """用 socket connect_ex 探测端口是否在监听（无需任何外部命令）。"""
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def listener_pids(port: int) -> list:
    """返回正在 LISTEN 指定端口的 PID 列表（去重、升序）。

    通过 ctypes 调用 iphlpapi.dll 的 GetExtendedTcpTable 实现，纯标准库、
    零外部依赖、不受 PATH 与编码影响。非 Windows 平台优雅返回 []。
    """
    if sys.platform != "win32":
        return []
    try:
        dll = ctypes.WinDLL("iphlpapi.dll", use_last_error=True)
        dll.GetExtendedTcpTable.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.DWORD),
            ctypes.wintypes.BOOL,
            ctypes.wintypes.ULONG,
            ctypes.c_ulong,
            ctypes.wintypes.ULONG,
        ]
        dll.GetExtendedTcpTable.restype = ctypes.wintypes.DWORD

        # 第一次调用拿所需缓冲区大小，返回 122 (ERROR_INSUFFICIENT_BUFFER) 是正常的。
        size = ctypes.wintypes.DWORD(0)
        rc = dll.GetExtendedTcpTable(
            None, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0
        )
        if rc not in (0, 122):
            return []
        buf = ctypes.create_string_buffer(size.value)
        rc = dll.GetExtendedTcpTable(
            ctypes.byref(buf), ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0
        )
        if rc != 0:
            return []

        # 缓冲区头 4 字节是条目数 dwNumEntries，之后每行 24 字节。
        n = ctypes.cast(buf, ctypes.POINTER(ctypes.wintypes.DWORD))[0]
        row_size = ctypes.sizeof(_MIB_TCPROW_OWNER_PID)
        base = ctypes.cast(buf, ctypes.c_void_p).value + 4

        found = set()
        for i in range(n):
            row = _MIB_TCPROW_OWNER_PID.from_address(base + i * row_size)
            # 本地端口为网络字节序，需要 ntohs 转回主机字节序。
            local_port = socket.ntohs(row.dwLocalPort & 0xFFFF)
            if local_port == port and row.dwState == MIB_TCP_STATE_LISTEN:
                found.add(row.dwOwningPid)
        return sorted(found)
    except Exception:
        return []


def kill_pids(pids) -> None:
    """通过 ctypes 调用 kernel32 终止给定 PID，不使用 taskkill（同有 PATH 风险）。

    忽略「进程已不存在 / 无权限」这类错误，尽力而为。非 Windows 或空列表为空操作。
    """
    if sys.platform != "win32" or not pids:
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            ctypes.wintypes.DWORD,
            ctypes.wintypes.BOOL,
            ctypes.wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.UINT,
        ]
        kernel32.TerminateProcess.restype = ctypes.wintypes.BOOL
        kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        kernel32.CloseHandle.restype = ctypes.wintypes.BOOL

        for pid in pids:
            try:
                handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
                if not handle:
                    continue
                kernel32.TerminateProcess(handle, 1)
                kernel32.CloseHandle(handle)
            except Exception:
                # 进程可能已退出（句柄无效），忽略。
                pass
    except Exception:
        pass
