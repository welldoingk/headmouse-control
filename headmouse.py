import cv2
import mediapipe as mp
import pyautogui
import threading
import time
import mouse
import tkinter as tk
from collections import deque
import json
import os
import ctypes
import keyboard
import sys
from time import time as now

SETTINGS_FILE = "headmouse_config.json"

# === 설정 관련 함수 ===
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {
        "cx_threshold": 0.515,
        "left_screen_coords": [-1055, 607],
        "right_screen_coords": [889, 640]
    }

def save_settings():
    settings = {
        "cx_threshold": cx_threshold,
        "left_screen_coords": [int(left_screen_x.get()), int(left_screen_y.get())],
        "right_screen_coords": [int(right_screen_x.get()), int(right_screen_y.get())]
    }
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

# === 화면 정보 ===
def get_virtual_screen_bounds():
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
    width = user32.GetSystemMetrics(78) # SM_CXVIRTUALSCREEN
    height = user32.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN
    return left, top, left + width, top + height

def get_virtual_mouse_position():
    pos = pyautogui.position()
    return (pos.x, pos.y)

# === 로그 출력 ===
def log_message(msg):
    log_text.config(state="normal")
    log_text.insert("end", msg + "\n")
    log_text.see("end")
    log_text.config(state="disabled")

# === 더블클릭 콜백 ===
def on_double_click():
    x, y = get_virtual_mouse_position()
    log_message(f"🖱 더블클릭 감지됨 → 현재 마우스 위치: x={x}, y={y}")

# === cx 슬라이더 콜백 ===
def update_threshold(val):
    global cx_threshold
    cx_threshold = float(val)

# === 시선 추적 쓰레드 ===
def run_tracker():
    log_message("run")
    global smoothed_cx, drag_mode, prev_zone, prev_smoothed_cx, last_known_positions
    mp_face_mesh = mp.solutions.face_mesh
    cap = None
    with mp_face_mesh.FaceMesh(refine_landmarks=True, max_num_faces=1, min_detection_confidence=0.5) as face_mesh:
        while True:
            if is_paused:
                if cap is not None:
                    cap.release()
                    cap = None
                    log_message("카메라 OFF (일시정지)")
                time.sleep(0.1)
                continue
            if cap is None:
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    log_message(f"❌ 0 카메라 열기 실패! 관리자 권한 또는 외장 카메라 연결 확인 필요")
                    cap = cv2.VideoCapture(1)
                    if not cap.isOpened():
                        log_message(f"❌ 1 카메라 열기 실패! 관리자 권한 또는 외장 카메라 연결 확인 필요")
                        time.sleep(1)
                        continue
                log_message("카메라 ON (재개)")
            success, image = cap.read()
            if not success:
                continue

            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(image_rgb)

            if result.multi_face_landmarks:
                face = result.multi_face_landmarks[0]
                cx = face.landmark[1].x
                cx_history.append(cx)
                smoothed_cx = sum(cx_history) / len(cx_history)

                if abs(smoothed_cx - prev_smoothed_cx) < 0.01:
                    continue
                prev_smoothed_cx = smoothed_cx

                try:
                    left_screen = (int(left_screen_x.get()), int(left_screen_y.get()))
                    right_screen = (int(right_screen_x.get()), int(right_screen_y.get()))

                    # 좌우 화면 구분
                    if smoothed_cx >= cx_threshold:
                        zone, default_pos = 'left_screen', left_screen
                    else:
                        zone, default_pos = 'right_screen', right_screen

                    # 화면이 바뀌었을 때만 처리
                    if prev_zone != zone:
                        # 이전 화면의 현재 위치 저장 (같은 화면에 있을 때만)
                        if prev_zone in last_known_positions:
                            current_pos = get_virtual_mouse_position()
                            min_x, min_y, max_x, max_y = get_virtual_screen_bounds()
                            
                            # 화면 중앙점 계산 (좌우 구분용)
                            left_center_x = int(left_screen[0])
                            right_center_x = int(right_screen[0])
                            screen_mid_x = (left_center_x + right_center_x) // 2
                            
                            # 마우스가 이전 화면에 있는지 확인
                            mouse_on_prev_screen = (prev_zone == 'left_screen' and current_pos[0] < screen_mid_x) or \
                                                  (prev_zone == 'right_screen' and current_pos[0] >= screen_mid_x)
                            
                            # 같은 화면에 있을 때만 위치 저장
                            if mouse_on_prev_screen:
                                last_known_positions[prev_zone] = current_pos
                                log_message(f"💾 {prev_zone} 위치 저장: {current_pos}")
                        
                        prev_zone = zone

                        # 드래그 모드 처리
                        if mouse.is_pressed(button='left'):
                            if not drag_mode:
                                pyautogui.mouseDown()
                                drag_mode = True
                            pyautogui.moveTo(*default_pos)
                            log_message(f"🖱 드래그 유지: {zone}, cx={smoothed_cx:.3f}, 좌표={default_pos}")
                        else:
                            if drag_mode:
                                pyautogui.mouseUp()
                                drag_mode = False

                            # 현재 마우스 위치 확인
                            current_pos = get_virtual_mouse_position()
                            min_x, min_y, max_x, max_y = get_virtual_screen_bounds()
                            
                            # 화면 중앙점 계산 (좌우 구분용)
                            left_center_x = int(left_screen[0])
                            right_center_x = int(right_screen[0])
                            screen_mid_x = (left_center_x + right_center_x) // 2
                            
                            # 마우스가 현재 화면에 있는지 확인
                            mouse_on_correct_screen = (zone == 'left_screen' and current_pos[0] < screen_mid_x) or \
                                                     (zone == 'right_screen' and current_pos[0] >= screen_mid_x)
                            
                            # 마우스가 올바른 화면에 있으면 그대로 둠
                            if mouse_on_correct_screen:
                                log_message(f"📍 이미 {zone}에 있음 - 마우스 이동 안함, cx={smoothed_cx:.3f}")
                            else:
                                # 마우스가 다른 화면에 있으면 기본 위치로 이동
                                pyautogui.moveTo(*default_pos)
                                log_message(f"🔄 다른 화면에서 {zone} 기본 위치로 이동: 좌표={default_pos}, cx={smoothed_cx:.3f}")

                except Exception as e:
                    log_message(f"예외 발생: {e}")

            time.sleep(0.1)

# === GUI 업데이트 ===
def update_gui():
    cx_label.config(text=f"cx: {smoothed_cx:.3f}")
    x, y = get_virtual_mouse_position()
    pos_label.config(text=f"mouse: ({x}, {y})")
    
    # 현재 화면 표시
    if smoothed_cx >= cx_threshold:
        screen_label.config(text="📍 현재: 왼쪽 화면", fg="blue")
    else:
        screen_label.config(text="📍 현재: 오른쪽 화면", fg="green")
    
    root.after(100, update_gui)

# === 프로그램 초기화 ===
settings = load_settings()
cx_threshold = settings["cx_threshold"]
left_screen_coords = settings["left_screen_coords"]
right_screen_coords = settings["right_screen_coords"]

smoothed_cx = 0.0
cx_history = deque(maxlen=5)
drag_mode = False
prev_zone = None
prev_smoothed_cx = 0.0
last_known_positions = {"left_screen": (0, 0), "right_screen": (0, 0)}

is_paused = False  # 일시정지 상태 변수 추가

# ESC 단축키 관련 변수
esc_times = []
ESC_INTERVAL = 2  # 2초 이내

def toggle_pause():
    global is_paused
    is_paused = not is_paused
    if is_paused:
        log_message("⏸️ 시선 추적 일시정지됨")
        pause_btn.config(text="재개")
    else:
        log_message("▶️ 시선 추적 재개됨")
        pause_btn.config(text="일시정지")

def on_esc_press(e=None):
    now_time = now()
    esc_times.append(now_time)
    # 최근 ESC 입력만 남김
    esc_times[:] = [t for t in esc_times if now_time - t <= ESC_INTERVAL]
    if len(esc_times) >= 4:
        log_message("ESC 4회 감지, 프로그램 종료")
        root.after(500, root.destroy)
        sys.exit(0)
    elif len(esc_times) == 3:
        toggle_pause()
        esc_times.clear()

def esc_listener():
    keyboard.on_release_key('esc', on_esc_press)
    keyboard.wait()  # 쓰레드가 종료되지 않게 유지

root = tk.Tk()
root.title("시선 마우스 제어 상태 (좌우 화면)")
root.geometry("400x500")

cx_label = tk.Label(root, text="cx: ---", font=("Arial", 14))
cx_label.pack(pady=5)

pos_label = tk.Label(root, text="mouse: (--, --)", font=("Arial", 14))
pos_label.pack(pady=5)

screen_label = tk.Label(root, text="📍 현재: ---", font=("Arial", 12), fg="black")
screen_label.pack(pady=5)

cx_slider = tk.Scale(root, from_=0.4, to=0.8, resolution=0.001,
                     orient=tk.HORIZONTAL, label="↔ cx 기준값", command=update_threshold)
cx_slider.set(cx_threshold)
cx_slider.pack(fill="x", padx=10, pady=5)

frame1 = tk.Frame(root)
frame1.pack(pady=5)
tk.Label(frame1, text="왼쪽 화면 좌표 (x, y)").grid(row=0, column=0, columnspan=2)
left_screen_x = tk.Entry(frame1, width=8)
left_screen_x.insert(0, str(left_screen_coords[0]))
left_screen_x.grid(row=1, column=0, padx=5)
left_screen_y = tk.Entry(frame1, width=8)
left_screen_y.insert(0, str(left_screen_coords[1]))
left_screen_y.grid(row=1, column=1, padx=5)

frame2 = tk.Frame(root)
frame2.pack(pady=5)
tk.Label(frame2, text="오른쪽 화면 좌표 (x, y)").grid(row=0, column=0, columnspan=2)
right_screen_x = tk.Entry(frame2, width=8)
right_screen_x.insert(0, str(right_screen_coords[0]))
right_screen_x.grid(row=1, column=0, padx=5)
right_screen_y = tk.Entry(frame2, width=8)
right_screen_y.insert(0, str(right_screen_coords[1]))
right_screen_y.grid(row=1, column=1, padx=5)

save_btn = tk.Button(root, text="설정 저장", command=save_settings)
save_btn.pack(pady=5)

pause_btn = tk.Button(root, text="일시정지", command=toggle_pause)
pause_btn.pack(pady=5)

log_text = tk.Text(root, height=10, state="disabled", bg="#f0f0f0")
log_text.pack(fill="both", expand=True, padx=10, pady=5)

mouse.on_double_click(lambda: threading.Thread(target=on_double_click).start())

threading.Thread(target=run_tracker, daemon=True).start()
threading.Thread(target=esc_listener, daemon=True).start()
update_gui()
root.mainloop() 