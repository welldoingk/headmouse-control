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
import sys
from time import time as now
import keyboard

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

def log_clear():
    log_text.config(state="normal")
    log_text.delete(1.0, "end")
    log_text.config(state="disabled")

# === cx 슬라이더 콜백 ===
def update_threshold(val):
    global cx_threshold
    cx_threshold = float(val)
    cx_value_label.config(text=f"현재값: {cx_threshold:.3f}")

# 로그창 토글
LOG_HEIGHT = 7
NORMAL_HEIGHT = 200
LOG_HEIGHT_PX = 320
NOLOG_HEIGHT_PX = 200

# 로그창 보이기/숨기기 상태에 따라 창 크기 자동 조정
LOG_HIDDEN_SIZE = "420x180"  # 로그창 숨김 상태 크기 (최소화)
LOG_VISIBLE_SIZE = "420x420"

def toggle_log():
    global log_visible
    if log_visible:
        log_frame.pack_forget()
        log_visible = False
        root.update()  # 레이아웃 강제 갱신
        root.geometry(LOG_HIDDEN_SIZE)
        root.minsize(420, 180)
    else:
        log_frame.pack(fill="both", expand=True)
        log_visible = True
        root.update()
        root.geometry(LOG_VISIBLE_SIZE)
        root.minsize(420, 420)

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
    esc_times.append(now())
    # 최근 ESC 입력만 남김
    esc_times[:] = [t for t in esc_times if now() - t <= ESC_INTERVAL]
    if len(esc_times) >= 4:
        log_message("ESC 4회 감지, 프로그램 종료")
        root.after(500, root.destroy)
        sys.exit(0)
    elif len(esc_times) == 3:
        # 2초 후 esc_times 길이 체크해서 1이면 일시정지
        def check_pause():
            if len(esc_times) == 3:
                toggle_pause()
                esc_times.clear()
        root.after(int(ESC_INTERVAL * 1000), check_pause)

def esc_listener():
    keyboard.on_release_key('esc', on_esc_press)
    keyboard.wait()  # 쓰레드가 종료되지 않게 유지

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
                        # 이전 화면을 떠날 때 마지막 위치 저장
                        if prev_zone in last_known_positions:
                            current_pos = get_virtual_mouse_position()
                            min_x, min_y, max_x, max_y = get_virtual_screen_bounds()
                            left_center_x = int(left_screen[0])
                            right_center_x = int(right_screen[0])
                            screen_mid_x = (left_center_x + right_center_x) // 2
                            mouse_on_prev_screen = (prev_zone == 'left_screen' and current_pos[0] < screen_mid_x) or \
                                                  (prev_zone == 'right_screen' and current_pos[0] >= screen_mid_x)
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
                            left_center_x = int(left_screen[0])
                            right_center_x = int(right_screen[0])
                            screen_mid_x = (left_center_x + right_center_x) // 2
                            mouse_on_correct_screen = (zone == 'left_screen' and current_pos[0] < screen_mid_x) or \
                                                     (zone == 'right_screen' and current_pos[0] >= screen_mid_x)
                            if mouse_on_correct_screen:
                                log_message(f"📍 이미 {zone}에 있음 - 마우스 이동 안함, cx={smoothed_cx:.3f}")
                            else:
                                target_pos = last_known_positions.get(zone)
                                if target_pos and (min_x <= target_pos[0] <= max_x and min_y <= target_pos[1] <= max_y):
                                    if (zone == 'left_screen' and target_pos[0] < screen_mid_x) or \
                                       (zone == 'right_screen' and target_pos[0] >= screen_mid_x):
                                        pyautogui.moveTo(target_pos[0], target_pos[1])
                                        last_known_positions[zone] = target_pos
                                        log_message(f"→ {zone} 마지막 위치로 이동: {target_pos}, cx={smoothed_cx:.3f}")
                                    else:
                                        pyautogui.moveTo(*default_pos)
                                        last_known_positions[zone] = default_pos
                                        log_message(f"🔄 {zone} 기본 위치로 이동(다른 화면의 위치): 좌표={default_pos}, cx={smoothed_cx:.3f}")
                                else:
                                    pyautogui.moveTo(*default_pos)
                                    last_known_positions[zone] = default_pos
                                    log_message(f"🔄 {zone} 기본 위치로 이동: 좌표={default_pos}, cx={smoothed_cx:.3f}")

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

# 프로그램 시작 시 ESC 리스너 쓰레드 실행
threading.Thread(target=esc_listener, daemon=True).start()

root = tk.Tk()
root.title("HeadMouse 상태 (좌우 화면)")
root.geometry(LOG_HIDDEN_SIZE)
root.minsize(420, 180)
root.resizable(False, False)

# 상단 상태 프레임
status_frame = tk.Frame(root)
status_frame.pack(pady=3, fill="x")

cx_label = tk.Label(status_frame, text="cx: ---", font=("Arial", 11))
cx_label.pack(side="left", padx=5)

pos_label = tk.Label(status_frame, text="mouse: (--, --)", font=("Arial", 11))
pos_label.pack(side="left", padx=5)

screen_label = tk.Label(status_frame, text="? 현재: ---", font=("Arial", 11), fg="black")
screen_label.pack(side="right", padx=5)

# 슬라이더 프레임
slider_frame = tk.Frame(root)
slider_frame.pack(pady=2, fill="x")
cx_slider = tk.Scale(slider_frame, from_=0.4, to=0.8, resolution=0.001,
                     orient=tk.HORIZONTAL, label="cx", command=update_threshold, showvalue=False, length=120)
cx_slider.set(cx_threshold)
cx_slider.pack(side="left", padx=2)
cx_value_label = tk.Label(slider_frame, text=f"현재값: {cx_threshold:.3f}", font=("Arial", 9))
cx_value_label.pack(side="left", padx=8)

# L(x,y) + [설정 저장][일시정지] 프레임 (grid로 정렬)
lrow = tk.Frame(root)
lrow.pack(pady=1, fill="x")
lrow.grid_columnconfigure(0, weight=0)
lrow.grid_columnconfigure(1, weight=0)
lrow.grid_columnconfigure(2, weight=0)
lrow.grid_columnconfigure(3, weight=1)
lrow.grid_columnconfigure(4, weight=0)
lrow.grid_columnconfigure(5, weight=0)
left_label = tk.Label(lrow, text="L(x,y)", font=("Arial", 9))
left_label.grid(row=0, column=0, padx=1, sticky="w")
left_screen_x = tk.Entry(lrow, width=7)
left_screen_x.insert(0, str(left_screen_coords[0]))
left_screen_x.grid(row=0, column=1, padx=1)
left_screen_y = tk.Entry(lrow, width=7)
left_screen_y.insert(0, str(left_screen_coords[1]))
left_screen_y.grid(row=0, column=2, padx=1)
save_btn = tk.Button(lrow, text="설정 저장", width=10, command=save_settings)
save_btn.grid(row=0, column=3, padx=8, sticky="e")
pause_btn = tk.Button(lrow, text="일시정지", width=10, command=toggle_pause)
pause_btn.grid(row=0, column=4, padx=2, sticky="e")

# R(x,y) + [로그 보기][로그 삭제] 프레임 (grid로 정렬)
rrow = tk.Frame(root)
rrow.pack(pady=1, fill="x")
rrow.grid_columnconfigure(0, weight=0)
rrow.grid_columnconfigure(1, weight=0)
rrow.grid_columnconfigure(2, weight=0)
rrow.grid_columnconfigure(3, weight=1)
rrow.grid_columnconfigure(4, weight=0)
rrow.grid_columnconfigure(5, weight=0)
right_label = tk.Label(rrow, text="R(x,y)", font=("Arial", 9))
right_label.grid(row=0, column=0, padx=1, sticky="w")
right_screen_x = tk.Entry(rrow, width=7)
right_screen_x.insert(0, str(right_screen_coords[0]))
right_screen_x.grid(row=0, column=1, padx=1)
right_screen_y = tk.Entry(rrow, width=7)
right_screen_y.insert(0, str(right_screen_coords[1]))
right_screen_y.grid(row=0, column=2, padx=1)
log_toggle_btn = tk.Button(rrow, text="로그 보기", width=10, command=toggle_log)
log_toggle_btn.grid(row=0, column=3, padx=8, sticky="e")
clear_log_btn = tk.Button(rrow, text="로그 삭제", width=10, command=log_clear)
clear_log_btn.grid(row=0, column=4, padx=2, sticky="e")

# 로그창 (처음엔 숨김)
log_visible = False  # 로그창 표시 상태 변수
# log_text를 감싸는 log_frame 생성
log_frame = tk.Frame(root)
log_frame.pack_propagate(False)  # 프레임이 자식 위젯 크기에 맞춰지지 않게
log_text = tk.Text(log_frame, height=LOG_HEIGHT, state="disabled", bg="#f0f0f0", font=("Arial", 9))
log_text.pack(fill="both", expand=True, padx=5, pady=2)
# log_frame.pack()은 처음엔 호출하지 않음 (숨김)

threading.Thread(target=run_tracker, daemon=True).start()
update_gui()
root.mainloop()