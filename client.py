import textwrap
import threading
import socket
import datetime

import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title='Socket Chat', width=950, height=800)

chatlog_lock = threading.Lock()
chatlog = ""
client_socket : socket.socket
server_started = False

def login():
    global client_socket, server_started
    # Creazione del socket
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        client_socket.connect((dpg.get_value("ip"), int(dpg.get_value("port"))))
        client_socket.send(dpg.get_value("username").encode("utf-8"))

        # Crea thread per ascolto dei messaggi dal server
        listen_thread = threading.Thread(target=listen_to_server, )
        listen_thread.daemon = True
        listen_thread.start()

        # Cambia schermata se non ci sono stati errori
        dpg.configure_item("chat", show=True)
        dpg.set_value("tabbar", "chat")

        server_started = True
    except Exception as e:
        # In caso di errori li stampa sotto al tasto login
        dpg.set_value("logerr", str(e))


def listen_to_server():
    global chatlog
    while True:
        try:
            msg = client_socket.recv(1024).decode("utf-8")
            if not msg:
                break
            with chatlog_lock:
                chatlog += "\n" + msg  # Aggiunge il messaggio già formattato dal server
        except Exception as e:
            print(f"Errore di connessione: {e}")
            break


def send_msg():
    global client_socket, chatlog
    msg = dpg.get_value("input_txt").strip()
    if not msg:
        return
    client_socket.send(msg.encode("utf-8"))
    dpg.set_value("input_txt", "")

with dpg.window(label="Chat", tag="window"):
    with dpg.tab_bar(label="Tab", tag="tabbar"):
        with dpg.tab(tag="login", label="Login"):
            dpg.add_text("Login")
            dpg.add_input_text(label="Username", tag="username")
            dpg.add_input_text(label="Indirizzo IP", tag="ip")
            dpg.add_input_text(label="Porta", tag="port")
            dpg.add_button(label="Login", callback=login)
            dpg.add_text("", tag="logerr")
        with dpg.tab(tag="chat", label="Chat", show=False):
            dpg.add_text("Chat")
            dpg.add_input_text(
                tag="chatlog_field", multiline=True, readonly=True, tracked=True, track_offset=1, width=-1, height=600)
            with dpg.group(horizontal=True):
                dpg.add_input_text(width=750, tag="input_txt", on_enter=True, callback=send_msg)
                dpg.add_button(label="Invia", callback=send_msg)

dpg.set_primary_window("window", True)

dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()

while dpg.is_dearpygui_running():
    if server_started:
        with chatlog_lock:
            if dpg.get_value("chatlog_field") != chatlog:
                dpg.set_value("chatlog_field", chatlog)
    dpg.render_dearpygui_frame()

if server_started:
    try:
        client_socket.send(b"closed connection")
        client_socket.close()
    except:
        pass