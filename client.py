import textwrap
import threading
import socket
from turtledemo.nim import COLOR

import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title='Socket Chat', width=950, height=800)

chatlog_lock = threading.Lock()
chatlog = ""
client_socket = None

def login():
    global client_socket
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    client_socket.bind((dpg.get_value("ip"), int(dpg.get_value("port"))))

with dpg.window(label="Chat", tag="window"):
    with dpg.tab_bar(label="Tab"):
        with dpg.tab(tag="login", label="Login"):
            dpg.add_text("Login")
            dpg.add_input_text(label="Username", tag="username")
            dpg.add_input_text(label="Indirizzo IP", tag="ip")
            dpg.add_input_text(label="Porta", tag="port")
            dpg.add_button(label="Login", callback=login)
        with dpg.tab(tag="Chat", label="Chat"):
            dpg.add_text("Chat")
            dpg.add_input_text(
                tag="log_field", multiline=True, readonly=True, tracked=True, track_offset=1, width=-1, height=600)
            with dpg.group(horizontal=True):
                dpg.add_input_text(width=750)
                dpg.add_button(label="Invia")

dpg.set_primary_window("window", True)

while dpg.is_dearpygui_running():
    dpg.render_dearpygui_frame()

dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()

dpg.destroy_context()