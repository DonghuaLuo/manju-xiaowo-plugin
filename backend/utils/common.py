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

def _open_file_manager(args):
    subprocess.Popen(
        args,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def open_in_dir_explorer(file_dir):
    """在系统文件管理器中打开目录。"""
    try:
        if not file_dir:
            return {"success": False, "message": "目录路径不能为空"}

        dir_path = Path(file_dir).expanduser()
        if not dir_path.exists():
            return {"success": False, "message": f"目录不存在: {file_dir}"}

        if not dir_path.is_dir():
            return {"success": False, "message": f"路径不是目录: {file_dir}"}

        absolute_dir = str(dir_path.resolve())
        if sys.platform == "win32":
            _open_file_manager(["explorer", absolute_dir])
        elif sys.platform == "darwin":
            _open_file_manager(["open", absolute_dir])
        else:
            _open_file_manager(["xdg-open", absolute_dir])

        return {
            "success": True,
            "message": "目录已打开",
            "path": absolute_dir,
            "openedPath": absolute_dir,
        }

    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return {"success": False, "message": f"打开目录失败: {str(e)}"}


def open_in_file_explorer(file_path):
    """在系统文件管理器中打开路径；文件会定位选中，目录会直接打开。"""
    try:
        if not file_path:
            return {"success": False, "message": "路径不能为空"}

        path = Path(file_path).expanduser()
        if not path.exists():
            return {"success": False, "message": f"路径不存在: {file_path}"}

        if path.is_dir():
            return open_in_dir_explorer(path)

        if not path.is_file():
            return {"success": False, "message": f"路径不是文件: {file_path}"}

        absolute_file = str(path.resolve())
        parent_dir = str(path.parent.resolve())
        if sys.platform == "win32":
            _open_file_manager(["explorer", "/select,", absolute_file])
        elif sys.platform == "darwin":
            _open_file_manager(["open", "-R", absolute_file])
        else:
            _open_file_manager(["xdg-open", parent_dir])

        return {
            "success": True,
            "message": "已打开文件位置",
            "path": absolute_file,
            "openedPath": parent_dir,
        }

    except Exception as e:
        print(traceback.format_exc(), flush=True)
        return {"success": False, "message": f"打开文件位置失败: {str(e)}"}


def open_file_location(file_path):
    """兼容旧调用：打开文件所在目录并选中文件。"""
    return open_in_file_explorer(file_path)


def open_directory(path):
    """兼容旧调用：在文件管理器中打开指定目录。"""
    return open_in_dir_explorer(path)
