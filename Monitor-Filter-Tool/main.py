import os
os.environ["OPENCV_FFMPEG_LOG_LEVEL"] = "-1"
os.environ["PYAV_LOGGING"] = "off"
os.environ["YOLO_VERBOSE"] = "False"
os.environ["YOLO_OFFLINE"] = "True"
import cv2
import numpy as np
import time
import base64
import math
import re
import urllib.request
from datetime import datetime, timedelta
import threading
from threading import Thread
from PIL import Image, ImageDraw, ImageFont
import eel
import tkinter as tk
from tkinter import filedialog
import av
import traceback
from ultralytics import YOLO

class CONFIG:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    CAPTURES_DIR = os.path.join(BASE_DIR, "captures")
    APP_TITLE = "AG-MONITOR 科技偵查戰術播放器"
    
    SMART_SKIP_SEC = 3.0   
    MOTION_THRESH = 25     
    MOTION_MIN_AREA = 500  

    TARGET_CLASSES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle"}

# Global State
video_queue = []
roi_points = []
scale_info = None 
is_processing = False
stop_requested = False
model = None
list_lock = threading.Lock()
global_live_settings = {}

# Player State
engine_mode = 'auto' # 'auto' or 'manual'
player_state = {
    'playing': False,
    'reverse': False,
    'speed': 1.0,
    'seek_req': None, # 0.0 ~ 100.0 percent
    'step_req': 0,    # frames to step
    'manual_capture_req': False,
    'current_frame': None,
    'current_timecode': "",
    'annotated_frame': None
}
player_lock = threading.Lock()
real_roi_poly = None

@eel.expose
def add_videos_dialog():
    global video_queue
    root = tk.Tk()
    root.attributes("-topmost", True)
    root.withdraw()
    files = filedialog.askopenfilenames(
        title="選擇視訊檔案",
        filetypes=[("視訊檔案", "*.mp4 *.avi *.mkv *.mov *.h264 *.h265 *.264 *.265 *.dav *.flv *.ts *.wmv")]
    )
    root.destroy()
    
    added_paths = []
    if files:
        with list_lock:
            for f in files:
                if f not in video_queue:
                    video_queue.append(f)
                    added_paths.append(f)
            if added_paths and len(video_queue) == len(added_paths):
                # load preview for the first
                Thread(target=load_preview_frame, args=(video_queue[0],), daemon=True).start()
    return added_paths

@eel.expose
def clear_queue():
    global real_roi_poly, video_queue
    with list_lock:
        video_queue.clear()
        real_roi_poly = None

@eel.expose
def open_capture_folder():
    try:
        folder_path = os.path.abspath(CONFIG.CAPTURES_DIR)
        os.makedirs(folder_path, exist_ok=True)
        os.startfile(folder_path)
        eel.appendLog("已開啟截圖資料夾", "info")
    except Exception as e:
        eel.appendLog(f"開啟資料夾失敗: {str(e)}", "error")

@eel.expose
def set_roi_points(pts):
    global roi_points
    roi_points = pts

@eel.expose
def request_stop():
    global stop_requested
    stop_requested = True
    eel.updateStatus("狀態: 正在要求安全終止...", "warn")

@eel.expose
def update_live_setting(key, value):
    global global_live_settings
    global_live_settings[key] = value

@eel.expose
def set_engine_mode(mode):
    global engine_mode, stop_requested
    if is_processing:
        return
    engine_mode = mode
    eel.appendLog(f"已切換至: {'全自動 AI 蒐證' if mode == 'auto' else '即時人眼點視'}", "info")

# --- Player API ---
@eel.expose
def play_pause():
    with player_lock:
        player_state['playing'] = not player_state['playing']
        eel.updatePlayState(player_state['playing'], player_state['reverse'])

@eel.expose
def toggle_reverse():
    with player_lock:
        player_state['reverse'] = not player_state['reverse']
        eel.updatePlayState(player_state['playing'], player_state['reverse'])

@eel.expose
def set_speed(s):
    with player_lock:
        player_state['speed'] = float(s)

@eel.expose
def seek_frame(percent):
    with player_lock:
        player_state['seek_req'] = float(percent)

@eel.expose
def step_frame(steps):
    with player_lock:
        player_state['step_req'] = int(steps)
        player_state['playing'] = False
        eel.updatePlayState(player_state['playing'], player_state['reverse'])

@eel.expose
def manual_capture():
    with player_lock:
        player_state['manual_capture_req'] = True

@eel.expose
def start_processing(settings):
    global is_processing, stop_requested, global_live_settings
    if not video_queue:
        eel.updateStatus("狀態: 清單為空，無法開始", "danger")
        eel.processingFinished()
        return
    is_processing = True
    stop_requested = False
    global_live_settings = settings.copy()
    
    with player_lock:
        player_state['playing'] = True if engine_mode == 'manual' else False
        player_state['reverse'] = False
        player_state['speed'] = 1.0
        player_state['seek_req'] = None
        player_state['step_req'] = 0
        player_state['manual_capture_req'] = False
    
    if engine_mode == 'manual':
        eel.updatePlayState(player_state['playing'], player_state['reverse'])
        
    Thread(target=batch_processing_worker, args=(settings,), daemon=True).start()

def load_preview_frame(video_path):
    global scale_info
    fh = None
    container = None
    try:
        ext = os.path.splitext(video_path)[1].lower()
        fmt = None
        if ext in ['.265', '.h265']:
            fmt = 'hevc'
        elif ext in ['.264', '.h264', '.dav']:
            fmt = 'h264'
        elif ext in ['.ts']:
            fmt = 'mpegts'
        
        fh = open(video_path, 'rb')
        try:
            container = av.open(fh, format=fmt, metadata_errors='ignore')
        except Exception:
            # If PyAV throws UnicodeDecodeError or any other error, fallback to probing
            container = av.open(video_path, format=fmt, metadata_errors='ignore')
        stream = container.streams.video[0]
        for frame in container.decode(stream):
            img = frame.to_ndarray(format='bgr24')
            
            canvas_w = 800
            canvas_h = 600
            
            frame_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img_h, img_w, _ = frame_rgb.shape
            scale = min(canvas_w / img_w, canvas_h / img_h)
            new_w, new_h = int(img_w * scale), int(img_h * scale)
            
            pad_x = (canvas_w - new_w) // 2
            pad_y = (canvas_h - new_h) // 2
            scale_info = (scale, pad_x, pad_y, img_w, img_h)
            
            img_resized = cv2.resize(frame_rgb, (new_w, new_h))
            
            canvas_img = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
            canvas_img[pad_y:pad_y+new_h, pad_x:pad_x+new_w] = img_resized
            
            _, buffer = cv2.imencode('.jpg', cv2.cvtColor(canvas_img, cv2.COLOR_RGB2BGR))
            b64_str = base64.b64encode(buffer).decode('utf-8')
            
            info_obj = {
                "scale": scale, "pad_x": pad_x, "pad_y": pad_y, 
                "canvas_w": canvas_w, "canvas_h": canvas_h
            }
            eel.setPreviewImage(b64_str, info_obj)()
            break
        container.close()
    except Exception as e:
        print(f"Failed to load preview: {e}")
    finally:
        if container:
            try:
                container.close()
            except Exception:
                pass
        if fh:
            fh.close()

def get_real_roi_polygon():
    if not scale_info or not roi_points:
        return None
    scale, pad_x, pad_y, img_w, img_h = scale_info
    real_pts = []
    for pt in roi_points:
        rx = max(0, min(int((pt[0] - pad_x) / scale), img_w - 1))
        ry = max(0, min(int((pt[1] - pad_y) / scale), img_h - 1))
        real_pts.append([rx, ry])
    return np.array(real_pts, dtype=np.int32)

def batch_processing_worker(settings):
    global is_processing, model
    try:
        if model is None:
            eel.updateStatus("狀態: 正在載入 YOLO 大腦...", "ok")
            model = YOLO("yolov8n.pt")  

        with list_lock:
            q = list(video_queue)
        total_v = len(q)

        for idx, video_path in enumerate(q):
            if stop_requested:
                break
            v_name = os.path.basename(video_path)
            eel.updateStatus(f"狀態: 正在分析 ({idx + 1}/{total_v}) {v_name}", "ok")
            eel.appendLog(f"開始載入影片: {v_name}", "info")
            process_single_video(video_path, v_name, settings)

        if stop_requested:
            eel.updateStatus("狀態: 已由使用者手動中止", "danger")
            eel.appendLog("任務被中斷", "warn")
        else:
            eel.updateProgress(100, "")
            eel.updateStatus("狀態: 全部完成！", "ok")
            eel.appendLog("所有佇列影片處理完成", "success")

    except Exception as e:
        err_msg = traceback.format_exc()
        eel.updateStatus("系統崩潰", "danger")
        eel.appendLog(f"系統崩潰: {str(e)}", "error")
        print(err_msg)
    finally:
        is_processing = False
        eel.processingFinished()

def parse_start_time(filename):
    match = re.search(r'(\d{14})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        except Exception:
            pass
    return None

def format_timecode(milliseconds, start_time=None):
    if start_time:
        dt = start_time + timedelta(milliseconds=milliseconds)
        ms = int(milliseconds % 1000)
        return dt.strftime("%Y/%m/%d %H:%M:%S") + f".{ms // 100:01d}"
    
    seconds = int(milliseconds / 1000)
    ms = int(milliseconds % 1000)
    mins = seconds // 60
    secs = seconds % 60
    hrs = mins // 60
    mins = mins % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{ms // 100:01d}"

def process_single_video(video_path, video_name, settings):
    global stop_requested, real_roi_poly
    
    clean_v_name = "".join([c for c in video_name if c.isalnum() or c in (".", "_", "-")]).rstrip()
    output_dir = os.path.join(CONFIG.CAPTURES_DIR, clean_v_name)
    os.makedirs(output_dir, exist_ok=True)
    real_roi_poly = get_real_roi_polygon()
    start_time_dt = parse_start_time(video_name)

    fh = None
    container = None
    try:
        ext = os.path.splitext(video_path)[1].lower()
        fmt = None
        if ext in ['.265', '.h265']:
            fmt = 'hevc'
        elif ext in ['.264', '.h264', '.dav']:
            fmt = 'h264'
        elif ext in ['.ts']:
            fmt = 'mpegts'

        # PyAV 記憶體解碼，0 秒直通，透過 Python handle 避開 Windows 中文路徑解碼問題
        fh = open(video_path, 'rb')
        try:
            container = av.open(fh, format=fmt, metadata_errors='ignore')
        except Exception:
            container = av.open(video_path, format=fmt, metadata_errors='ignore')
        stream = container.streams.video[0]
        stream.thread_type = "NONE"
        
        fps = float(stream.average_rate) if stream.average_rate else 30.0
        if fps <= 0:
            fps = 30.0
        
        total_frames = stream.frames
        if total_frames <= 0:
            if stream.duration:
                total_frames = int(float(stream.duration * stream.time_base) * fps)
            else:
                total_frames = 1000

        # Dynamically update scale_info for the current video dimensions
        global scale_info
        img_w = stream.width if stream.width else 800
        img_h = stream.height if stream.height else 600
        canvas_w = 800
        canvas_h = 600
        scale = min(canvas_w / img_w, canvas_h / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)
        pad_x = (canvas_w - new_w) // 2
        pad_y = (canvas_h - new_h) // 2
        scale_info = (scale, pad_x, pad_y, img_w, img_h)

        conf_thresh = settings['confThresh']
        capture_mode = settings.get('captureMode', '')
        class_vars = settings['classes']
        fast_mode = settings.get('fastMode', True)
        skip_sec = float(settings.get('skipSec', 0.20))

        dynamic_step = int(fps * 3.0)  # 3秒跳格
        static_skip_step = int(fps * skip_sec)
        
        track_states = {}
        id_alias_map = {}
        
        anchor_gray = None
        target_frame_idx = 0
        decoded_frame_idx = -1
        is_dynamic_mode = False
        dynamic_lock_until = 0
        no_target_frames = 0
        
        stream.codec_context.skip_frame = 'NONKEY'
        frame_iter = container.decode(stream)
        current_av_frame = None
        
        def get_frame(target_idx):
            nonlocal current_av_frame, decoded_frame_idx, frame_iter
            
            if target_idx < decoded_frame_idx or (target_idx - decoded_frame_idx) > 30:
                pts = int(target_idx / fps / float(stream.time_base))
                container.seek(pts, stream=stream, backward=True)
                frame_iter = container.decode(stream)
                for f in frame_iter:
                    current_av_frame = f
                    t_idx = int(float(f.pts * stream.time_base) * fps) if f.pts else decoded_frame_idx + 1
                    decoded_frame_idx = t_idx
                    if t_idx >= target_idx:
                        return f.to_ndarray(format='bgr24')
                return None
            else:
                while current_av_frame is None or decoded_frame_idx < target_idx:
                    try:
                        current_av_frame = next(frame_iter)
                        decoded_frame_idx = int(float(current_av_frame.pts * stream.time_base) * fps) if current_av_frame.pts else decoded_frame_idx + 1
                    except StopIteration:
                        return None
                
                if current_av_frame:
                    return current_av_frame.to_ndarray(format='bgr24')
                return None

        last_ui_update = time.time()
        
        while True:
            if stop_requested:
                break
            
            with player_lock:
                req_seek = player_state['seek_req']
                req_step = player_state['step_req']
                is_play = player_state['playing']
                is_rev = player_state['reverse']
                p_speed = player_state['speed']
                req_capture = player_state['manual_capture_req']
                player_state['seek_req'] = None
                player_state['step_req'] = 0
                player_state['manual_capture_req'] = False

            if engine_mode == 'manual':
                if stream.codec_context.skip_frame != 'DEFAULT':
                    stream.codec_context.skip_frame = 'DEFAULT'
                target_idx = target_frame_idx
                
                if req_seek is not None:
                    target_idx = int((req_seek / 100.0) * total_frames)
                elif req_step != 0:
                    target_idx = max(0, target_idx + req_step)
                elif is_play:
                    if is_rev:
                        target_idx = max(0, target_idx - int(1 * p_speed))
                    else:
                        target_idx = target_idx + int(1 * p_speed)

                if target_idx != decoded_frame_idx or current_av_frame is None:
                    frame = get_frame(target_idx)
                    if frame is None and is_play:
                        with player_lock:
                            player_state['playing'] = False
                            eel.updatePlayState(False, player_state['reverse'])
                        continue
                else:
                    frame = current_av_frame.to_ndarray(format='bgr24') if current_av_frame else None

                target_frame_idx = target_idx

                if frame is not None:
                    milliseconds = (target_idx / fps) * 1000
                    time_code_str = format_timecode(milliseconds, start_time_dt)
                    
                    annotated = frame.copy()
                    if real_roi_poly is not None:
                        cv2.polylines(annotated, [real_roi_poly], True, (0, 255, 0), 2)
                    
                    if req_capture:
                        save_legal_screenshot(annotated, output_dir, time_code_str, ["Manual Capture"])
                        eel.appendLog(f"[{time_code_str}] 📸 手動快門擷取成功", "success")

                    # Draw OSD Timecode
                    frame_h, frame_w = annotated.shape[:2]
                    osd_text = f"AG-MONITOR | {time_code_str}"
                    (tw, th), _ = cv2.getTextSize(osd_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                    cv2.rectangle(annotated, (5, frame_h - th - 15), (5 + tw + 10, frame_h - 5), (0, 0, 0), -1)
                    cv2.putText(annotated, osd_text, (10, frame_h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                    now = time.time()
                    if not is_play or (now - last_ui_update > 0.03):
                        push_frame_to_ui(annotated)
                        eel.updateProgress(min(100, (target_idx / total_frames) * 100), time_code_str)
                        last_ui_update = now

                if is_play:
                    time.sleep(1.0 / (fps * p_speed) if p_speed < 8 else 0.01)
                else:
                    time.sleep(0.01)


            else:
                conf_thresh = global_live_settings.get('confThresh', conf_thresh)
                fast_mode = global_live_settings.get('fastMode', fast_mode)
                skip_sec = float(global_live_settings.get('skipSec', skip_sec))
                static_skip_step = int(fps * skip_sec)
                
                # 依據動態狀態切換解碼模式
                if not is_dynamic_mode:
                    stream.codec_context.skip_frame = 'NONKEY'  # 靜態空景：只解碼關鍵影格
                    try:
                        while True:
                            current_av_frame = next(frame_iter)
                            decoded_frame_idx = int(float(current_av_frame.pts * stream.time_base) * fps) if current_av_frame.pts else decoded_frame_idx + 1
                            if decoded_frame_idx >= target_frame_idx:
                                target_frame_idx = decoded_frame_idx
                                frame = current_av_frame.to_ndarray(format='bgr24')
                                break
                    except StopIteration:
                        break
                else:
                    stream.codec_context.skip_frame = 'DEFAULT'  # 動態追蹤：逐幀完整解碼
                    frame = get_frame(target_frame_idx)
                    if frame is None:
                        break

                milliseconds = (target_frame_idx / fps) * 1000
                time_code_str = format_timecode(milliseconds, start_time_dt)
                
                now = time.time()
                if now - last_ui_update > 0.1:
                    eel.updateProgress(min(100, (target_frame_idx / total_frames) * 100), time_code_str)
                    last_ui_update = now

                # ---------------- YOLO Detection ----------------
                results = model.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False)[0]
                boxes = results.boxes
                annotated_frame = frame.copy()
                valid_targets = []

                if boxes is not None:
                    for box in boxes:
                        if box.id is None:
                            continue
                        conf = float(box.conf[0])
                        if conf < conf_thresh:
                            continue
                        cls_id = int(box.cls[0])
                        if cls_id not in CONFIG.TARGET_CLASSES or not class_vars.get(str(cls_id), True):
                            continue

                        raw_tid = int(box.id[0])
                        tid = id_alias_map.get(raw_tid, raw_tid)
                        xyxy = box.xyxy[0].cpu().numpy()
                        x1, y1, x2, y2 = map(int, xyxy)
                        centroid = ((x1 + x2) / 2, y2)

                        inside_roi = True
                        if real_roi_poly is not None:
                            dist = cv2.pointPolygonTest(real_roi_poly, centroid, False)
                            inside_roi = dist >= 0

                        if inside_roi:
                            valid_targets.append({'tid': tid, 'raw_tid': raw_tid, 'conf': conf, 'cls_id': cls_id, 'xyxy': (x1, y1, x2, y2)})
                            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 0, 255), 1)
                            cv2.putText(annotated_frame, f"ID:{tid} {CONFIG.TARGET_CLASSES[cls_id]} {conf:.2f}",
                                (x1, max(15, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

                if real_roi_poly is not None:
                    cv2.polylines(annotated_frame, [real_roi_poly], True, (0, 255, 0), 1)

                # ---------------- Motion & Skip Logic ----------------
                motion_detected = len(valid_targets) > 0

                if motion_detected:
                    no_target_frames = 0
                else:
                    no_target_frames += 1

                if is_dynamic_mode:
                    if no_target_frames < int(fps * 1.5):
                        motion_detected = True

                if is_dynamic_mode and target_frame_idx < dynamic_lock_until:
                    motion_detected = True

                if not is_dynamic_mode:
                    if motion_detected:
                        dynamic_lock_until = target_frame_idx
                        target_frame_idx = max(0, target_frame_idx - static_skip_step)
                        is_dynamic_mode = True
                        
                        stream.codec_context.skip_frame = 'DEFAULT'
                        pts = int(target_frame_idx / fps / float(stream.time_base))
                        container.seek(pts, stream=stream, backward=True)
                        frame_iter = container.decode(stream)
                        decoded_frame_idx = -1
                        current_av_frame = None
                        continue
                    else:
                        _run_grace_period_gc(milliseconds, track_states, capture_mode, output_dir)
                        target_frame_idx += static_skip_step
                        continue
                else:
                    if not motion_detected and target_frame_idx >= dynamic_lock_until:
                        is_dynamic_mode = False
                        target_frame_idx += static_skip_step
                        _run_grace_period_gc(milliseconds, track_states, capture_mode, output_dir)
                        continue

                # ---------------- Track States Management ----------------
                for target in valid_targets:
                    raw_tid = target['raw_tid']
                    tid = target['tid']
                    conf = target['conf']
                    cls_name = CONFIG.TARGET_CLASSES[target['cls_id']]
                    summary_str = f"ID:{tid} {cls_name}"
                    x1, y1, x2, y2 = target['xyxy']
                    w, h = x2 - x1, y2 - y1
                    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                    
                    if tid not in track_states:
                        matched_old_tid = None
                        for old_tid, old_state in track_states.items():
                            if old_state['class_name'] != cls_name:
                                continue
                            if old_state['last_seen_msec'] == milliseconds:
                                continue
                            
                            time_diff = milliseconds - old_state['last_seen_msec']
                            if 0 < time_diff <= 1500:
                                old_cx, old_cy = old_state.get('last_centroid', (cx, cy))
                                dist = math.hypot(cx - old_cx, cy - old_cy)
                                last_w, last_h = old_state.get('last_box_size', (w, h))
                                radius = max(80, min(200, max(last_w, last_h) * 1.2))
                                if dist <= radius:
                                    matched_old_tid = old_tid
                                    break
                        
                        if matched_old_tid is not None:
                            id_alias_map[raw_tid] = matched_old_tid
                            tid = matched_old_tid
                            summary_str = f"ID:{tid} {cls_name}"
                        else:
                            track_states[tid] = {
                                'class_name': cls_name,
                                'best_conf': conf,
                                'best_frame': annotated_frame.copy(),
                                'best_timecode': time_code_str,
                                'best_summary': [f"{summary_str}({conf:.2f} Peak)"],
                                'last_frame': annotated_frame.copy(),
                                'last_timecode': time_code_str,
                                'last_seen_msec': milliseconds,
                                'last_continuous_capture_msec': milliseconds,
                                'last_centroid': (cx, cy),
                                'last_box_size': (w, h)
                            }
                            if capture_mode in ["雙格蒐證模式 (起點+最清晰)", "事件起訖模式"]:
                                save_legal_screenshot(annotated_frame, output_dir, time_code_str, [f"{summary_str}(Entry)"])
                                eel.appendLog(f"[{time_code_str}] 擷取 {summary_str}(Entry)", "success")
                            elif capture_mode == "持續追蹤模式 (預設)":
                                save_legal_screenshot(annotated_frame, output_dir, time_code_str, [f"{summary_str}(Track-Entry)"])
                                eel.appendLog(f"[{time_code_str}] 擷取 {summary_str}(Track-Entry)", "success")
                    else:
                        state = track_states[tid]
                        state['last_seen_msec'] = milliseconds
                        state['last_frame'] = annotated_frame.copy()
                        state['last_timecode'] = time_code_str
                        state['last_centroid'] = (cx, cy)
                        state['last_box_size'] = (w, h)
                        
                        if conf > state['best_conf']:
                            state['best_conf'] = conf
                            state['best_frame'] = annotated_frame.copy()
                            state['best_timecode'] = time_code_str
                            state['best_summary'] = [f"{summary_str}({conf:.2f} Peak)"]
                    
                    if capture_mode == "持續追蹤模式 (預設)":
                        state = track_states[tid]
                        if (milliseconds - state['last_continuous_capture_msec']) >= 3000:
                            state['last_continuous_capture_msec'] = milliseconds
                            save_legal_screenshot(annotated_frame, output_dir, time_code_str, [f"{summary_str}(Track)"])
                            eel.appendLog(f"[{time_code_str}] 擷取 {summary_str}(Track)", "success")

                if engine_mode == 'auto' and is_dynamic_mode:
                    current_targets_str = ", ".join([f"ID:{t['tid']} {CONFIG.TARGET_CLASSES[t['cls_id']]}" for t in valid_targets])
                    if current_targets_str:
                        eel.updateStatus(f"狀態: 正在分析 (發現目標: {current_targets_str})", "ok")
                    else:
                        eel.updateStatus(f"狀態: 正在分析 (追蹤中...)", "ok")

                # Draw OSD Timecode
                frame_h, frame_w = annotated_frame.shape[:2]
                osd_text = f"AG-MONITOR | {time_code_str}"
                (tw, th), _ = cv2.getTextSize(osd_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                cv2.rectangle(annotated_frame, (5, frame_h - th - 15), (5 + tw + 10, frame_h - 5), (0, 0, 0), -1)
                cv2.putText(annotated_frame, osd_text, (10, frame_h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                if not fast_mode:
                    push_frame_to_ui(annotated_frame)
                    
                _run_grace_period_gc(milliseconds, track_states, capture_mode, output_dir)

                target_frame_idx += 1 

        if engine_mode == 'auto':
            _flush_all_track_states(track_states, capture_mode, output_dir)
        container.close()

    except Exception as e:
        err_msg = traceback.format_exc()
        eel.appendLog(f"[{video_name}] 解碼毀損診斷: {str(e)}", "error")
        eel.appendLog("處置建議: 可能是編碼異常或檔案殘缺，請重新提取原始檔案。", "warn")
        print(f"Exception for {video_name}:\n{err_msg}")
    finally:
        if container:
            try:
                container.close()
            except Exception:
                pass
        if fh:
            fh.close()

def push_frame_to_ui(frame):
    canvas_w, canvas_h = 800, 600
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img_h, img_w, _ = frame_rgb.shape
    scale = min(canvas_w / img_w, canvas_h / img_h)
    new_w, new_h = int(img_w * scale), int(img_h * scale)
    pad_x = (canvas_w - new_w) // 2
    pad_y = (canvas_h - new_h) // 2
    img_resized = cv2.resize(frame_rgb, (new_w, new_h))
    canvas_img = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    canvas_img[pad_y:pad_y+new_h, pad_x:pad_x+new_w] = img_resized
    _, buffer = cv2.imencode('.jpg', cv2.cvtColor(canvas_img, cv2.COLOR_RGB2BGR))
    b64_str = base64.b64encode(buffer).decode('utf-8')
    info_obj = {"scale": scale, "pad_x": pad_x, "pad_y": pad_y, "canvas_w": canvas_w, "canvas_h": canvas_h}
    eel.setPreviewImage(b64_str, info_obj)()

def _run_grace_period_gc(curr_msec, track_states, capture_mode, output_dir):
    expired_ids = []
    for tid, state in track_states.items():
        if (curr_msec - state['last_seen_msec']) > 1500:
            expired_ids.append(tid)
    for tid in expired_ids:
        state = track_states[tid]
        if capture_mode in ["雙格蒐證模式 (起點+最清晰)", "單次最清晰模式 (推薦)"]:
            if state['best_frame'] is not None:
                save_legal_screenshot(state['best_frame'], output_dir, state['best_timecode'], state['best_summary'])
                eel.appendLog(f"[{state['best_timecode']}] 擷取 {state['best_summary'][0]}", "success")
        elif capture_mode == "事件起訖模式":
            if state['last_frame'] is not None:
                save_legal_screenshot(state['last_frame'], output_dir, state['last_timecode'], [f"ID:{tid} {state['class_name']}(Exit)"])
                eel.appendLog(f"[{state['last_timecode']}] 擷取 ID:{tid} {state['class_name']}(Exit)", "success")
        del track_states[tid]

def _flush_all_track_states(track_states, capture_mode, output_dir):
    for tid, state in track_states.items():
        if capture_mode in ["雙格蒐證模式 (起點+最清晰)", "單次最清晰模式 (推薦)"]:
            if state['best_frame'] is not None:
                save_legal_screenshot(state['best_frame'], output_dir, state['best_timecode'], state['best_summary'])
                eel.appendLog(f"[{state['best_timecode']}] 擷取 {state['best_summary'][0]}", "success")
        elif capture_mode == "事件起訖模式":
            if state['last_frame'] is not None:
                save_legal_screenshot(state['last_frame'], output_dir, state['last_timecode'], [f"ID:{tid} {state['class_name']}(Exit)"])
                eel.appendLog(f"[{state['last_timecode']}] 擷取 ID:{tid} {state['class_name']}(Exit)", "success")
    track_states.clear()

def save_legal_screenshot(frame, output_dir, time_code, objects_list):
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(frame_rgb)
    draw = ImageDraw.Draw(pil_img)

    try:
        font = ImageFont.truetype("msjh.ttc", 16)
        small_font = ImageFont.truetype("msjh.ttc", 12)
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", 16)
            small_font = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            font = ImageFont.load_default()
            small_font = ImageFont.load_default()

    w, h = pil_img.size
    watermark_text = f"AG-MONITOR | Timecode: {time_code}"
    detail_text = f"Target: {', '.join(objects_list)}"

    text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
    tw = text_bbox[2] - text_bbox[0]
    
    det_bbox = draw.textbbox((0, 0), detail_text, font=small_font)
    dw = det_bbox[2] - det_bbox[0]
    
    box_w = max(tw, dw) + 30
    box_h = 45
    
    bx1 = 15
    by1 = h - box_h - 15
    bx2 = bx1 + box_w
    by2 = by1 + box_h
    
    overlay = Image.new('RGBA', pil_img.size, (255, 255, 255, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    
    # 120 is roughly 47% opacity for the background
    overlay_draw.rectangle([(bx1, by1), (bx2, by2)], fill=(0, 0, 0, 120))
    overlay_draw.text((bx1 + 15, by1 + 5), watermark_text, fill=(255, 255, 0, 255), font=font)
    overlay_draw.text((bx1 + 15, by1 + 25), detail_text, fill=(255, 255, 255, 255), font=small_font)

    pil_img = pil_img.convert("RGBA")
    pil_img = Image.alpha_composite(pil_img, overlay)
    pil_img = pil_img.convert("RGB")

    safe_time_str = time_code.replace("/", "-").replace(":", "-").replace(".", "-")
    filename = f"evidence_{safe_time_str}.jpg"
    final_path = os.path.join(output_dir, filename)

    final_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    try:
        is_success, buffer = cv2.imencode('.jpg', final_bgr)
        if is_success:
            with open(final_path, 'wb') as f:
                f.write(buffer)
        else:
            print(f"[DEBUG] cv2.imencode failed for {final_path}")
    except Exception as e:
        print(f"[DEBUG] save_legal_screenshot exception: {e}")

# ==========================================
# 數位鑑識 AI 影像超解析工作站 (Super-Resolution)
# ==========================================
SR_MODEL_PATH = os.path.join(CONFIG.BASE_DIR, 'ESPCN_x2.pb')
SR_MODEL_URL = 'https://raw.githubusercontent.com/fannymonori/TF-ESPCN/master/export/ESPCN_x2.pb'

sr_abort_flag = False

def check_and_download_sr_model():
    global sr_abort_flag
    if not os.path.exists(SR_MODEL_PATH):
        print(">>> [系統預檢] 偵測到本機缺乏 AI 超解析權重檔 (ESPCN_x2.pb)")
        print(">>> [系統動作] 正在背景非同步下載輕量化鑑識模型，請稍候...")
        try:
            req = urllib.request.urlopen(SR_MODEL_URL, timeout=15)
            with open(SR_MODEL_PATH, 'wb') as f:
                while True:
                    if sr_abort_flag:
                        print(">>> [系統動作] 使用者已強制中止 AI 模型下載！")
                        return False
                    chunk = req.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
            print(">>> [系統動作] AI 模型下載完成！")
        except Exception as e:
            print(f"❌ [數位鑑識崩潰]：模型權重檔下載失敗 ({e})")
            print("💡 [系統處置建議]：請確認對外網路連線，或手動將 ESPCN_x2.pb 放置於專案根目錄。")
            if os.path.exists(SR_MODEL_PATH):
                os.remove(SR_MODEL_PATH)
            return False
    return True

@eel.expose
def abort_ai_super_resolution():
    global sr_abort_flag
    sr_abort_flag = True
    print(">>> [系統動作] 已接收前端中止信號，準備強制斬斷修復進程...")

@eel.expose
def run_ai_super_resolution(base64_str, mode='plate'):
    global sr_abort_flag
    sr_abort_flag = False

    def _run_sr():
        try:
            img_data = base64.b64decode(base64_str)
            np_arr = np.frombuffer(img_data, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            
            if img is None:
                eel.on_super_res_finished(None, "❌ 影像解碼失敗，請確認檔案格式是否正確。")()
                return

            if mode == 'face':
                print(">>> [系統動作] 發動人像五官模式前置處理：套用 Non-Local Means Denoising 抹除壓縮區塊...")
                # 在放大之前先強制去噪，避免 ESPCN 或是 Lanczos 把雜訊與馬賽克當作「邊緣」強化
                img = cv2.fastNlMeansDenoisingColored(img, None, h=10, hColor=10, templateWindowSize=7, searchWindowSize=21)

            fallback_triggered = False
            warning_msg = None

            if hasattr(cv2, 'dnn_superresolution'):
                if not check_and_download_sr_model():
                    if sr_abort_flag:
                        return
                    print(">>> [系統動作] 下載失敗或超時，進入第二軌備援流程！")
                    warning_msg = "⚠️ [資安警告] 網路連線超時或失敗，AI已自動平滑降級為第二軌高階銳化鑑識模態！"
                    fallback_triggered = True
                else:
                    if sr_abort_flag:
                        return
                    try:
                        sr = cv2.dnn_superresolution.DnnSuperResolutionImpl_create()
                        sr.readModel(SR_MODEL_PATH)
                        sr.setModel("espcn", 2)
                        result = sr.upsample(img)
                    except Exception as dnn_err:
                        print(f">>> [系統警告] DNN 超解析執行失敗 ({dnn_err})，自動切換至第二軌備援流程！")
                        warning_msg = "⚠️ [備援提示] AI 核心模組運算異常，已自動切換為第二軌高階銳化鑑識模態。"
                        fallback_triggered = True
            else:
                fallback_triggered = True

            if fallback_triggered:
                if sr_abort_flag:
                    return
                print(">>> [系統動作] 發動第二軌備援：傳統最高階 Lanczos 內插法與 CLAHE 直方圖均衡化...")
                h, w = img.shape[:2]
                scaled = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_LANCZOS4)
                
                ycrcb = cv2.cvtColor(scaled, cv2.COLOR_BGR2YCrCb)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                ycrcb[:,:,0] = clahe.apply(ycrcb[:,:,0])
                result = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)
            
            if sr_abort_flag:
                return

            if mode == 'face':
                print(">>> [系統動作] 發動人像五官模式後置處理：套用高階雙邊濾鏡 (Bilateral Filter) 進行平滑降噪...")
                # 加大參數 d=15, 增強 sigma, 確保徹底抹除殘餘的馬賽克感但保留五官輪廓
                result = cv2.bilateralFilter(result, d=15, sigmaColor=100, sigmaSpace=100)

            # 通訊封包瘦身：傳送給前端預覽時使用 90 壓縮率，大幅降低 WebSocket 負載
            _, buffer = cv2.imencode('.jpg', result, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            res_b64 = base64.b64encode(buffer).decode('utf-8')
            eel.on_super_res_finished(res_b64, warning_msg)()
            
        except Exception as e:
            print(f"❌ [數位鑑識崩潰]：超解析引擎運算錯誤 ({e})")
            print("💡 [系統處置建議]：請確認 OpenCV dnn 模組支援，或嘗試重新選擇圖片。")
            eel.on_super_res_finished(None, f"❌ 運算發生錯誤：{e}")()
            
    Thread(target=_run_sr, daemon=True).start()

@eel.expose
def save_enhanced_evidence(base64_str, mode='plate'):
    try:
        enhanced_dir = os.path.join(CONFIG.BASE_DIR, "enhanced_evidence")
        os.makedirs(enhanced_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = "Enhanced_Face" if mode == 'face' else "Enhanced_Plate"
        filename = f"{prefix}_{timestamp}.png"
        filepath = os.path.join(enhanced_dir, filename)
        
        img_data = base64.b64decode(base64_str)
        with open(filepath, 'wb') as f:
            f.write(img_data)
            
        print(f">>> [系統動作] 鑑識修復照片已儲存至: {filepath}")
        
        # Windows only: open folder and select file
        try:
            import subprocess
            subprocess.run(['explorer', '/select,', os.path.normpath(filepath)])
        except Exception:
            pass
            
        return True
    except Exception as e:
        print(f"❌ [數位鑑識崩潰]：修復檔案寫入失敗 ({e})")
        print("💡 [系統處置建議]：請確認 enhanced_evidence 目錄未被防毒軟體或隨身碟唯讀保護。")
        return False

if __name__ == "__main__":
    os.makedirs(CONFIG.CAPTURES_DIR, exist_ok=True)
    try:
        web_dir = os.path.join(CONFIG.BASE_DIR, 'web')
        eel.init(web_dir)
        print("==================================================")
        print("AG-MONITOR Forensic Player Engine Online!")
        print("http://localhost:8000/index.html")
        print("==================================================")
        eel.start('index.html', size=(1280, 950), mode='edge', port=8000)
    except Exception as e:
        print("Eel Boot Failed:", e)
