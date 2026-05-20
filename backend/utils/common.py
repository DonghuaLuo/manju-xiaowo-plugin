#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
公共函数文件
"""
import os
import subprocess
import sys
import traceback
from pathlib import Path
from charset_normalizer import detect
def readfile(file_path, default_encoding=None):
    content=_readfile(file_path, default_encoding)
    if content.startswith('\ufeff'):
        content = content[1:]
    return content

def _readfile(file_path, default_encoding=None):
    if not os.path.exists(file_path):
        return None
    if default_encoding:
        encoding = default_encoding
    else:
        #先使用默认打开
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
            #print('是uft-8')
            return content
        except:
            pass
        try:
            with open(file_path, 'r', encoding='gbk') as file:
                content = file.read()
            #print('是gbk')
            return content
        except:
            pass
        with open(file_path, 'rb') as file:
            raw_data = file.read()
        result = detect(raw_data)
        encoding = result['encoding']
        if encoding is None:
            encoding = 'utf-8'
    #print('自动识别')
    try:
        with open(file_path, 'r', encoding=encoding, errors='ignore') as file:
            content = file.read()
            return content
    except:
        return ''
def format_size(size_bytes):
    """格式化文件大小"""
    if size_bytes < 0:
        return "未知"

    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"

def open_file_location(file_path):
    """
    在文件管理器中打开文件所在目录并选中该文件

    Args:
        file_path: 文件路径

    Returns:
        dict: 操作结果
    """
    try:
        path = Path(file_path)

        if not path.exists():
            return {"success": False, "message": "文件不存在"}

        if not path.is_file():
            return {"success": False, "message": "路径不是文件"}

        # 根据操作系统选择打开方式
        if sys.platform == "win32":
            # Windows - 使用 explorer /select 命令选中文件
            subprocess.Popen(["explorer", "/select,", os.path.abspath(file_path)])
        elif sys.platform == "darwin":
            # macOS - 使用 open -R 命令选中文件
            subprocess.Popen(["open", "-R", str(path)])
        else:
            # Linux - 大多数文件管理器不支持选中文件，只能打开目录
            # 尝试使用 dbus 调用文件管理器（适用于支持的桌面环境）
            subprocess.Popen(["xdg-open", str(path.parent)])

        return {"success": True, "message": "已打开文件位置"}

    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return {"success": False, "message": f"打开文件位置失败: {str(e)}"}

def open_directory(path):
    """
    在文件管理器中打开指定目录

    Args:
        path: 要打开的目录路径

    Returns:
        dict: 包含 success 和 message 的字典
    """
    try:
        # 确保路径存在
        dir_path = Path(path)
        if not dir_path.exists():
            return {"success": False, "message": f"目录不存在: {path}"}

        if not dir_path.is_dir():
            return {"success": False, "message": f"路径不是目录: {path}"}

        # 根据操作系统选择打开方式
        if sys.platform == "win32":
            # Windows - 使用 explorer 命令在前台打开
            # 使用 Popen 而不是 run，避免等待进程结束
            subprocess.Popen(["explorer", os.path.abspath(path)])
        elif sys.platform == "darwin":
            # macOS
            subprocess.Popen(["open", path], check=True)
        else:
            # Linux
            subprocess.Popen(["xdg-open", path], check=True)

        return {"success": True, "message": "目录已打开"}

    except Exception as e:
        print(traceback.format_exc(),flush=True)
        return {"success": False, "message": f"打开目录失败: {str(e)}"}