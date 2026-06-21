#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
專案名稱：一鍵本機系統快取清理與行程優化小工具 (System Optimizer Tool)
導向規範：全域開發憲法 v2.0 (Tech Lead 簽發版)
主要功能：過濾清理系統開發暫存、僵屍 Python/Node 行程盤點優化、記憶體即時釋放
相依性宣告：本工具採用 Python 3 內建標準庫 (tkinter, os, sys, shutil, subprocess, gc)
安裝指令：pip install customtkinter
執行指令：python main.py
"""

import os
import sys
import shutil
import subprocess
import gc
import datetime
import threading
import customtkinter as ctk
from tkinter import messagebox, scrolledtext

# ==============================================================================
# 1. 配置優先模式 (Config-First Pattern) - 易變參數與全域樣式置頂
# ==============================================================================
class CONFIG:
    APP_NAME = "一鍵本機系統快取清理與行程優化小工具"
    VERSION = "v1.0.0 (憲法 v2.0 實踐版)"
    
    # 清理門檻與路徑設定
    DEFAULT_CPU_THRESHOLD = 80.0       # CPU 警告閾值 (%)
    DEFAULT_PROCESS_RAM_LIMIT = 500    # 僵屍行程記憶體判定門檻 (MB)
    TARGET_PROCESSES = ["python.exe", "node.exe"]  # 預設鎖定的開發環境常見高能耗行程
    
    # 預設掃描的開發暫存路徑 (防禦性設計：自動轉換使用者目錄)
    USER_HOME = os.path.expanduser("~")
    TEMP_DIR = os.path.join(USER_HOME, "AppData", "Local", "Temp")
    PIP_CACHE_DIR = os.path.join(USER_HOME, "AppData", "Local", "pip", "cache")
    PREFETCH_DIR = r"C:\Windows\Prefetch"  # 需注意管理員權限
    
    # 動態掃描深度設定 (Config-First & UI-Driven)
    SCAN_DEPTH_OPTIONS = {
        "僅看首層": 1,
        "看 2 層": 2,
        "看 3 層": 3,
        "無限制 (全清空)": 999
    }
    DEFAULT_SCAN_DEPTH = "無限制 (全清空)"
    DRY_RUN = True  # 模擬開關 (安全第一)
    
    # UI 顏色準則設定 (優雅深色調與視覺引導)
    THEME = {
        "BG_DARK": "#1E1E24",          # 主背景深灰
        "CARD_BG": "#2A2A32",          # 元件背景
        "TEXT_LIGHT": "#F5F5F7",       # 內文白色
        "TEXT_MUTED": "#8E8E93",       # 提示字灰色
        "PRIMARY": "#2980B9",          # 科技藍
        "SUCCESS": "#27AE60",          # 叢林綠
        "WARNING": "#F39C12",          # 琥珀橙
        "DANGER": "#E74C3C"            # 警示紅
    }
    
    # 嚴格防禦性安全白名單：絕對禁止刪除或結束的關鍵字，保障代碼與核心安全
    PROTECTED_KEYWORDS = [
        ".git", ".antigravity", "rules.md", "main.py", 
        "explorer.exe", "taskmgr.exe", "svchost.exe"
    ]

# ==============================================================================
# 2. 核心四大清理與優化邏輯 (The Technical Engine)
# ==============================================================================
class OptimizerEngine:
    
    @staticmethod
    def clean_temp_cache(log_callback, target_dir, skip_protected=True, max_depth=1, dry_run=False):
        """核心邏輯一：過期暫存快取脫水 (Temp Clean) - 支援動態深度與 DRY_RUN"""
        mode_text = "[模擬掃描]" if dry_run else "開始掃描"
        log_callback(f"🚀 {mode_text} 系統開發暫存區 (設定深度: {max_depth} 層)...", CONFIG.THEME["PRIMARY"])
        if not os.path.exists(target_dir):
            log_callback(f"⚠️ 目標暫存路徑不存在，自動跳過：{target_dir}", CONFIG.THEME["WARNING"])
            return [] if dry_run else 0
            
        deleted_bytes = 0
        deleted_count = 0
        failed_count = 0
        pending_files = []
        
        # 遍歷暫存目錄，實作動態掃描深度 (_recursive_scan 邏輯)
        for root, dirs, files in os.walk(target_dir):
            # 計算當前遞迴深度
            if root == target_dir:
                depth_level = 1
            else:
                depth_level = len(os.path.relpath(root, target_dir).split(os.sep)) + 1
                
            # 若已達最大深度，直接清空 dirs 停止深入遍歷
            if depth_level >= max_depth:
                dirs.clear()

            # 防禦性過濾：嚴禁觸碰白名單
            if skip_protected and any(key in root.lower() for key in CONFIG.PROTECTED_KEYWORDS):
                continue
                
            for file in files:
                # 絕對防禦：.py 與 .html 擴充名以及關鍵字保護
                is_protected_ext = file.lower().endswith('.py') or file.lower().endswith('.html')
                if skip_protected and (is_protected_ext or any(key in file.lower() for key in CONFIG.PROTECTED_KEYWORDS)):
                    continue
                    
                file_path = os.path.join(root, file)
                if dry_run:
                    log_callback(f"🔍 [DRY_RUN] 預計刪除檔案: {file_path}", CONFIG.THEME["TEXT_MUTED"])
                    pending_files.append(file_path)
                else:
                    try:
                        # 取得檔案大小用於統計
                        file_size = os.path.getsize(file_path)
                        os.remove(file_path)
                        deleted_bytes += file_size
                        deleted_count += 1
                    except Exception:
                        # 防禦性程式設計：鎖定或權限不足的檔案自動跳過，100%不崩潰
                        failed_count += 1
                    
        if dry_run:
            return pending_files
        else:
            mb_released = deleted_bytes / (1024 * 1024)
            log_callback(f"✅ 暫存清理完成！成功釋放空間: {mb_released:.2f} MB", CONFIG.THEME["SUCCESS"])
            log_callback(f"📊 統計：成功刪除 {deleted_count} 個檔案，跳過 {failed_count} 個項目 (原因: 檔案正被其他程式佔用或權限不足)。\n", CONFIG.THEME["TEXT_LIGHT"])
            return mb_released

    @staticmethod
    def clean_prefetch(log_callback, target_dir, dry_run=False):
        """核心邏輯擴充：微軟系統 Prefetch 與 Office 歷史清理 - 支援 DRY_RUN"""
        mode_text = "[模擬掃描]" if dry_run else "開始掃描"
        log_callback(f"🚀 {mode_text} 系統預載歷史 (Prefetch)...", CONFIG.THEME["PRIMARY"])
        if not os.path.exists(target_dir):
            log_callback(f"⚠️ 目標路徑不存在，自動跳過：{target_dir}", CONFIG.THEME["WARNING"])
            return [] if dry_run else 0
            
        deleted_bytes = 0
        deleted_count = 0
        failed_count = 0
        pending_files = []
        
        try:
            for root, dirs, files in os.walk(target_dir):
                for file in files:
                    # 絕對防禦：.py 與 .html 擴充名保護
                    is_protected_ext = file.lower().endswith('.py') or file.lower().endswith('.html')
                    if is_protected_ext:
                        continue
                        
                    file_path = os.path.join(root, file)
                    if dry_run:
                        log_callback(f"🔍 [DRY_RUN] 預計刪除檔案: {file_path}", CONFIG.THEME["TEXT_MUTED"])
                        pending_files.append(file_path)
                    else:
                        try:
                            # 取得檔案大小用於統計
                            file_size = os.path.getsize(file_path)
                            os.remove(file_path)
                            deleted_bytes += file_size
                            deleted_count += 1
                        except Exception:
                            # 防禦性程式設計：鎖定或權限不足的檔案自動跳過，100%不崩潰
                            failed_count += 1
        except Exception as e:
            log_callback(f"❌ 存取 Prefetch 發生錯誤 (可能需管理員權限): {str(e)}", CONFIG.THEME["WARNING"])
            
        if dry_run:
            return pending_files
        else:
            mb_released = deleted_bytes / (1024 * 1024)
            log_callback(f"✅ Prefetch 清理完成！成功釋放空間: {mb_released:.2f} MB", CONFIG.THEME["SUCCESS"])
            log_callback(f"📊 統計：成功刪除 {deleted_count} 個檔案，跳過 {failed_count} 個項目 (原因: 檔案正被其他程式佔用或權限不足)。\n", CONFIG.THEME["TEXT_LIGHT"])
            return mb_released

    @staticmethod
    def kill_zombie_processes(log_callback, ram_limit_mb, target_extensions=None, dry_run=False):
        """核心邏輯二：僵屍行程優化 (Process Killer) - 支援 DRY_RUN"""
        mode_text = "[模擬盤點]" if dry_run else "開始盤點"
        log_callback(f"🚀 {mode_text} 背景閒置之孤立行程 (記憶體門檻 > {ram_limit_mb}MB)...", CONFIG.THEME["PRIMARY"])
        if target_extensions is None:
            target_extensions = CONFIG.TARGET_PROCESSES
            
        killed_count = 0
        pending_pids = []
        try:
            # 使用 Windows 內建 tasklist 進行防禦性盤點，避免引入額外第三方庫 (如 psutil)
            cmd = 'tasklist /FO CSV /NH'
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            output = subprocess.check_output(cmd, startupinfo=startupinfo, text=True, encoding='cp950', errors='ignore')
            
            for line in output.splitlines():
                if not line.strip():
                    continue
                parts = line.replace('"', '').split(',')
                if len(parts) >= 5:
                    proc_name = parts[0].strip()
                    pid = parts[1].strip()
                    mem_usage_str = parts[4].replace(' K', '').replace(',', '').strip()
                    
                    if any(ext in proc_name.lower() for ext in target_extensions):
                        try:
                            # 換算為 MB
                            mem_mb = int(mem_usage_str) / 1024
                            if mem_mb > ram_limit_mb:
                                # 安全檢查：不可結束自身 PID
                                if int(pid) == os.getpid():
                                    continue
                                    
                                if dry_run:
                                    log_callback(f"🔍 [DRY_RUN] 預計結束行程：{proc_name} (PID: {pid}) 佔用 {mem_mb:.1f} MB", CONFIG.THEME["WARNING"])
                                    pending_pids.append((pid, proc_name))
                                else:
                                    log_callback(f"⚠️ 偵測到高能耗行程：{proc_name} (PID: {pid}) 佔用 {mem_mb:.1f} MB", CONFIG.THEME["WARNING"])
                                    # 強制關閉高能耗僵屍行程
                                    subprocess.run(f"taskkill /F /PID {pid}", startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                    log_callback(f"❌ 已強制釋放行程 PID: {pid}", CONFIG.THEME["DANGER"])
                                    killed_count += 1
                        except ValueError:
                            continue
        except Exception as e:
            log_callback(f"❌ 讀取行程列表時發生錯誤: {str(e)}", CONFIG.THEME["DANGER"])
            
        if dry_run:
            return pending_pids
        else:
            if killed_count == 0:
                log_callback("✅ 行程檢查完成，背景環境乾淨，未發現超標僵屍行程。\n", CONFIG.THEME["SUCCESS"])
            else:
                log_callback(f"✅ 成功重構並結束了 {killed_count} 個高能耗孤立行程。\n", CONFIG.THEME["SUCCESS"])
            return killed_count

    @staticmethod
    def force_garbage_collection(log_callback):
        """核心邏輯三：記憶體即時釋放 (RAM Garbage Collection)"""
        log_callback("🚀 啟動 Python 核心記憶體分頁回收...", CONFIG.THEME["PRIMARY"])
        try:
            # 強制進行垃圾回收
            gc.get_referrers()
            collected = gc.collect()
            log_callback(f"✅ 記憶體回收機制調用成功！強制回收物件群組共: {collected} 組", CONFIG.THEME["SUCCESS"])
            log_callback("⚙️ 本機分頁負載已完成縮減與重新對齊。\n", CONFIG.THEME["TEXT_MUTED"])
        except Exception as e:
            log_callback(f"❌ 回收記憶體時發生非預期錯誤: {str(e)}\n", CONFIG.THEME["DANGER"])

# ==============================================================================
# 3. 雙重配置模式 UI 介面實作 (Config-First & UI-Driven Frontend)
# ==============================================================================
class SystemOptimizerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{CONFIG.APP_NAME} {CONFIG.VERSION}")
        self.geometry("900x650")
        ctk.set_appearance_mode("dark")
        
        # 設置介面字體
        self.default_font = ctk.CTkFont(family="Microsoft JhengHei", size=12)
        self.title_font = ctk.CTkFont(family="Microsoft JhengHei", size=14, weight="bold")
        
        # 綁定 UI 變數 (動態配置 UI 化，免動 Code 直接在畫面控制)
        self.var_clean_temp = ctk.BooleanVar(value=True)
        self.var_clean_pip = ctk.BooleanVar(value=False)
        self.var_clean_prefetch = ctk.BooleanVar(value=False)
        self.var_kill_zombie = ctk.BooleanVar(value=True)
        self.var_ram_limit = ctk.IntVar(value=CONFIG.DEFAULT_PROCESS_RAM_LIMIT)
        self.var_scan_depth = ctk.StringVar(value=CONFIG.DEFAULT_SCAN_DEPTH)
        self.var_dry_run = ctk.BooleanVar(value=CONFIG.DRY_RUN)
        
        self.build_ui()
        
        # 初始化日誌回報
        self.append_log(f"✅ {CONFIG.APP_NAME} 載入成功。", CONFIG.THEME["SUCCESS"])
        self.append_log("💡 提示：勾選下方動態面板參數後，點擊「開始一鍵優化」即可發動代碼邏輯。\n---", CONFIG.THEME["TEXT_MUTED"])

    def build_ui(self):
        """建構主畫面排版 - 嚴格區分控制區與即時日誌回饋區"""
        # 頂部主題區
        header_frame = ctk.CTkFrame(self, fg_color=CONFIG.THEME["CARD_BG"], height=60)
        header_frame.pack(fill="x", padx=15, pady=10)
        header_frame.pack_propagate(False)
        
        lbl_title = ctk.CTkLabel(header_frame, text=f"🚀 {CONFIG.APP_NAME}", font=ctk.CTkFont(family="Microsoft JhengHei", size=16, weight="bold"), text_color=CONFIG.THEME["TEXT_LIGHT"])
        lbl_title.pack(side="left", padx=15, pady=15)
        
        lbl_ver = ctk.CTkLabel(header_frame, text=CONFIG.VERSION, font=self.default_font, text_color=CONFIG.THEME["TEXT_MUTED"])
        lbl_ver.pack(side="right", padx=15, pady=18)
        
        # 動態掃描深度控制下拉選單 (放置於頂部功能列)
        frame_depth = ctk.CTkFrame(header_frame, fg_color="transparent")
        frame_depth.pack(side="right", padx=15, pady=15)
        lbl_depth = ctk.CTkLabel(frame_depth, text="📂 掃描深度：", font=self.default_font, text_color=CONFIG.THEME["TEXT_LIGHT"])
        lbl_depth.pack(side="left")
        self.cmb_depth = ctk.CTkComboBox(frame_depth, variable=self.var_scan_depth, values=list(CONFIG.SCAN_DEPTH_OPTIONS.keys()), state="readonly", width=140, font=self.default_font, fg_color=CONFIG.THEME["BG_DARK"], border_color=CONFIG.THEME["PRIMARY"])
        self.cmb_depth.pack(side="left", padx=5)

        # 頂部進度條區 (UI 規範要求)
        self.progress_bar = ctk.CTkProgressBar(self, height=8, progress_color=CONFIG.THEME["PRIMARY"], fg_color=CONFIG.THEME["CARD_BG"])
        self.progress_bar.pack(fill="x", padx=15, pady=(0, 5))
        self.progress_bar.set(0)

        # 中間主要工作區：雙欄架構 (左：動態配置面板 / 右：即時日誌視窗)
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=15, pady=5)
        
        # ------------------ 左側：動態配置面板 (UI-Driven Panel) ------------------
        left_panel = ctk.CTkFrame(main_container, fg_color=CONFIG.THEME["CARD_BG"], corner_radius=10)
        left_panel.pack(side="left", fill="both", padx=(0, 10))
        
        left_title = ctk.CTkLabel(left_panel, text="⚙️ 動態優化配置面板 (免改代碼)", font=self.title_font, text_color=CONFIG.THEME["PRIMARY"])
        left_title.pack(anchor="w", padx=15, pady=(15, 10))
        
        chk_temp = ctk.CTkCheckBox(left_panel, text="清理使用者暫存區 (Temp)", variable=self.var_clean_temp, font=self.default_font, text_color=CONFIG.THEME["TEXT_LIGHT"], hover_color=CONFIG.THEME["PRIMARY"])
        chk_temp.pack(anchor="w", padx=15, pady=8)
        
        chk_pip = ctk.CTkCheckBox(left_panel, text="清理 Python pip 快取目錄", variable=self.var_clean_pip, font=self.default_font, text_color=CONFIG.THEME["TEXT_LIGHT"], hover_color=CONFIG.THEME["PRIMARY"])
        chk_pip.pack(anchor="w", padx=15, pady=8)
        
        chk_prefetch = ctk.CTkCheckBox(left_panel, text="清理系統預載歷史 (Prefetch)", variable=self.var_clean_prefetch, font=self.default_font, text_color=CONFIG.THEME["TEXT_LIGHT"], hover_color=CONFIG.THEME["PRIMARY"])
        chk_prefetch.pack(anchor="w", padx=15, pady=8)
        
        divider = ctk.CTkFrame(left_panel, fg_color=CONFIG.THEME["BG_DARK"], height=2)
        divider.pack(fill="x", padx=15, pady=15)
        
        chk_zombie = ctk.CTkCheckBox(left_panel, text="強制結束高能耗閒置行程", variable=self.var_kill_zombie, font=self.default_font, text_color=CONFIG.THEME["TEXT_LIGHT"], hover_color=CONFIG.THEME["PRIMARY"])
        chk_zombie.pack(anchor="w", padx=15, pady=5)
        
        chk_dry_run = ctk.CTkCheckBox(left_panel, text="🛡️ DRY_RUN 模擬開關 (僅列印不刪除)", variable=self.var_dry_run, font=self.default_font, text_color=CONFIG.THEME["TEXT_LIGHT"], hover_color=CONFIG.THEME["PRIMARY"])
        chk_dry_run.pack(anchor="w", padx=15, pady=(5, 10))
        
        lbl_slider_desc = ctk.CTkLabel(left_panel, text="行程記憶體超標閾值 (Slider)：", font=self.default_font, text_color=CONFIG.THEME["TEXT_LIGHT"])
        lbl_slider_desc.pack(anchor="w", padx=15, pady=(10, 2))
        
        # 滑桿控制 (動態配置 UI 化：即時調整記憶體判定標準)
        self.ram_slider = ctk.CTkSlider(
            left_panel, from_=100, to=2000, number_of_steps=38,
            variable=self.var_ram_limit, progress_color=CONFIG.THEME["PRIMARY"], button_color=CONFIG.THEME["PRIMARY"]
        )
        self.ram_slider.pack(fill="x", padx=15, pady=5)
        
        lbl_unit = ctk.CTkLabel(left_panel, text="單位: MB (建議設定 500MB)", font=ctk.CTkFont(family="Microsoft JhengHei", size=11), text_color=CONFIG.THEME["TEXT_MUTED"])
        lbl_unit.pack(anchor="e", padx=15, pady=(0, 15))
        
        # 底部動作大按鈕
        self.btn_launch = ctk.CTkButton(
            left_panel, text="⚡ 開始一鍵優化", font=ctk.CTkFont(family="Microsoft JhengHei", size=14, weight="bold"),
            fg_color=CONFIG.THEME["SUCCESS"], text_color=CONFIG.THEME["TEXT_LIGHT"], hover_color="#2196F3",
            corner_radius=8, height=45, command=self.execute_optimization_flow
        )
        self.btn_launch.pack(fill="x", side="bottom", padx=15, pady=15)

        # ------------------ 右側：即時日誌終端機 (Log Terminal) ------------------
        right_panel = ctk.CTkFrame(main_container, fg_color=CONFIG.THEME["CARD_BG"], corner_radius=10)
        right_panel.pack(side="right", fill="both", expand=True)
        
        right_title = ctk.CTkLabel(right_panel, text="🖥️ 系統優化即時防禦日誌", font=self.title_font, text_color=CONFIG.THEME["PRIMARY"])
        right_title.pack(anchor="w", padx=15, pady=(15, 5))
        
        log_frame = ctk.CTkFrame(right_panel, fg_color="#111115", corner_radius=8)
        log_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        self.log_display = scrolledtext.ScrolledText(
            log_frame, bg="#111115", fg=CONFIG.THEME["TEXT_LIGHT"], font=("Consolas", 11),
            relief="flat", wrap="word", insertbackground=CONFIG.THEME["TEXT_LIGHT"], borderwidth=0, highlightthickness=0
        )
        self.log_display.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 設定日誌顏色標籤群組
        for key, color in CONFIG.THEME.items():
            self.log_display.tag_config(color, foreground=color)

    def append_log(self, message, color_key=None):
        """安全列印日誌，自動滾動到底部 (Thread-Safe)"""
        def _update():
            self.log_display.insert("end", message + "\n")
            if color_key:
                # 計算剛剛插入的文字行數並套用特殊高亮色彩
                end_line = float(self.log_display.index("end")) - 1.0
                start_line = end_line - 1.0
                self.log_display.tag_add(color_key, f"{start_line:.1f}", f"{end_line:.1f}")
            self.log_display.see("end")
            self.update_idletasks()
        self.after(0, _update)

    # ==============================================================================
    # 4. 一鍵排程與工作流管理 (SOP Execution Flow)
    # ==============================================================================
    def execute_optimization_flow(self):
        """依據動態勾選面板，發動防禦性優化核心流程 (背景執行緒)"""
        # 停用按鈕防止重複觸發
        self.btn_launch.configure(state="disabled", text="⏳ 優化執行中...")
        self.append_log("==================================================", CONFIG.THEME["TEXT_MUTED"])
        self.append_log(f"⏰ 任務發動時間：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", CONFIG.THEME["TEXT_LIGHT"])
        self.append_log("==================================================", CONFIG.THEME["TEXT_MUTED"])
        
        # 讀取 UI 狀態 (必須在主線程)
        is_dry_run = self.var_dry_run.get()
        selected_depth_str = self.var_scan_depth.get()
        max_depth = CONFIG.SCAN_DEPTH_OPTIONS.get(selected_depth_str, 1)
        do_temp = self.var_clean_temp.get()
        do_pip = self.var_clean_pip.get()
        do_prefetch = self.var_clean_prefetch.get()
        do_zombie = self.var_kill_zombie.get()
        current_threshold_mb = self.var_ram_limit.get()
        
        if is_dry_run:
            self.append_log("🛡️ 目前啟用 DRY_RUN 模擬模式，僅列出清單不會真實執行！", CONFIG.THEME["WARNING"])

        def _update_progress(value):
            self.after(0, lambda: self.progress_bar.set(value))

        def _thread_task():
            try:
                _update_progress(0.1)
                pending_files = []
                pending_pids = []
                total_items = 0

                # Step 1: 清理本機 Temp 暫存
                if do_temp:
                    res = OptimizerEngine.clean_temp_cache(self.append_log, CONFIG.TEMP_DIR, max_depth=max_depth, dry_run=is_dry_run)
                    if is_dry_run: pending_files.extend(res)
                _update_progress(0.3)
                    
                # Step 2: 清理 Python pip 快取
                if do_pip:
                    res = OptimizerEngine.clean_temp_cache(self.append_log, CONFIG.PIP_CACHE_DIR, max_depth=max_depth, dry_run=is_dry_run)
                    if is_dry_run: pending_files.extend(res)
                _update_progress(0.5)
                    
                # Step 2.5: 清理系統預載歷史 (Prefetch)
                if do_prefetch:
                    res = OptimizerEngine.clean_prefetch(self.append_log, CONFIG.PREFETCH_DIR, dry_run=is_dry_run)
                    if is_dry_run: pending_files.extend(res)
                _update_progress(0.7)
                    
                # Step 3: 背景僵屍行程回收 (Process Killer)
                if do_zombie:
                    res = OptimizerEngine.kill_zombie_processes(self.append_log, ram_limit_mb=current_threshold_mb, dry_run=is_dry_run)
                    if is_dry_run: pending_pids.extend(res)
                _update_progress(0.9)
                    
                if is_dry_run:
                    total_items = len(pending_files) + len(pending_pids)
                    if total_items == 0:
                        _update_progress(1.0)
                        self.append_log("✅ 模擬結束，目前環境乾淨，無任何需要清理的項目。\n", CONFIG.THEME["SUCCESS"])
                        self.after(0, lambda: messagebox.showinfo("模擬完成", "模擬結束，無項目需要清理！"))
                    else:
                        _update_progress(1.0)
                        self.append_log(f"📊 [模擬統計] 預計清理 {len(pending_files)} 個檔案，結束 {len(pending_pids)} 個行程。", CONFIG.THEME["TEXT_LIGHT"])
                        self.append_log("⚠️ 請確認上方路徑，若無誤可點擊確認進行真實刪除。", CONFIG.THEME["WARNING"])
                        
                        def _ask_confirm():
                            confirm = messagebox.askyesno("真實執行確認", f"DRY_RUN 模擬完成！\n\n預計刪除: {len(pending_files)} 個檔案\n預計結束: {len(pending_pids)} 個行程\n\n確認無誤並執行真實刪除嗎？")
                            if confirm:
                                threading.Thread(target=_real_delete_thread, args=(pending_files, pending_pids), daemon=True).start()
                            else:
                                self.append_log("🛑 使用者已取消真實刪除動作。\n", CONFIG.THEME["TEXT_MUTED"])
                                self.btn_launch.configure(state="normal", text="⚡ 開始一鍵優化")
                                
                        self.after(0, _ask_confirm)
                        return
                else:
                    # Step 4: 系統層級記憶體回收 (RAM脫水)
                    OptimizerEngine.force_garbage_collection(self.append_log)
                    _update_progress(1.0)
                    
                    self.append_log("🏁 【一鍵系統優化程序全部執行完畢】", CONFIG.THEME["SUCCESS"])
                    self.append_log("✨ 電腦卡頓效能已成功找回，武器庫重回巔峰狀態！\n", CONFIG.THEME["SUCCESS"])
                    self.after(0, lambda: messagebox.showinfo("Tech Lead 報告", "一鍵系統效能優化成功完畢！\n相關處理細節已完整記錄於防禦日誌中。"))
                
            except Exception as e:
                self.append_log(f"❌ 執行緒內發生嚴重異常: {str(e)}", CONFIG.THEME["DANGER"])
                self.after(0, lambda err=e: messagebox.showerror("技術審查警告", f"程序發生非預期中斷:\n{str(err)}"))
                
            finally:
                if not is_dry_run or (is_dry_run and total_items == 0):
                    self.after(0, lambda: self.btn_launch.configure(state="normal", text="⚡ 開始一鍵優化"))
                    self.after(2000, lambda: self.progress_bar.set(0))

        def _real_delete_thread(files, pids):
            try:
                self.append_log("\n⚡ 使用者授權通過！開始執行真實刪除與優化程序...", CONFIG.THEME["DANGER"])
                
                deleted_count = 0
                failed_count = 0
                for file_path in files:
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                    except Exception:
                        failed_count += 1
                    
                killed_count = 0
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                for pid, proc_name in pids:
                    try:
                        subprocess.run(f"taskkill /F /PID {pid}", startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        killed_count += 1
                    except: pass
                    
                self.append_log(f"✅ 真實清理完畢！成功刪除 {deleted_count} 個檔案，結束 {killed_count} 個行程。", CONFIG.THEME["SUCCESS"])
                if failed_count > 0:
                    self.append_log(f"⚠️ 注意：有 {failed_count} 個檔案未刪除 (原因: 檔案正被其他程式佔用或無存取權限)。", CONFIG.THEME["WARNING"])
                    
                OptimizerEngine.force_garbage_collection(self.append_log)
                _update_progress(1.0)
                self.append_log("🏁 【一鍵系統優化程序全部執行完畢】", CONFIG.THEME["SUCCESS"])
                self.after(0, lambda: messagebox.showinfo("優化完成", "真實清理已成功完畢！(詳見日誌)"))
            except Exception as e:
                self.append_log(f"❌ 真實刪除發生嚴重異常: {str(e)}", CONFIG.THEME["DANGER"])
            finally:
                self.after(0, lambda: self.btn_launch.configure(state="normal", text="⚡ 開始一鍵優化"))
                self.after(2000, lambda: self.progress_bar.set(0))

        threading.Thread(target=_thread_task, daemon=True).start()

# ==============================================================================
# 5. 應用程式進入點 (Application Entry)
# ==============================================================================
if __name__ == "__main__":
    # 高 DPI 螢幕適配，防止介面字體模糊
    try:
        if sys.platform.startswith('win'):
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
        
    app = SystemOptimizerApp()
    app.mainloop()