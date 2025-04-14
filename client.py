import textwrap
import threading
import socket
import datetime
import dearpygui.dearpygui as dpg

DEFAULT_IP = "127.0.0.1"
DEFAULT_PORT = "12345"

dpg.create_context()
dpg.create_viewport(title='Socket Chat', width=950, height=800)

chatlog_lock = threading.Lock()
chatlog = ""
client_socket = None
server_started = False
current_username = ""


def register():
    username = dpg.get_value("username")
    password = dpg.get_value("password")

    if not username or not password:
        dpg.set_value("logerr", "Username e password sono obbligatori!")
        return

    try:
        temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_socket.connect((DEFAULT_IP, int(DEFAULT_PORT)))
        temp_socket.send(f"REGISTER:{username}:{password}".encode("utf-8"))

        response = temp_socket.recv(1024).decode("utf-8")
        dpg.set_value("logerr", response)

        temp_socket.close()
    except Exception as e:
        dpg.set_value("logerr", f"Errore durante la registrazione: {str(e)}")


def login():
    global client_socket, server_started, current_username
    username = dpg.get_value("username")
    password = dpg.get_value("password")

    if not username or not password:
        dpg.set_value("logerr", "Username e password sono obbligatori!")
        return

    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        client_socket.connect((DEFAULT_IP, int(DEFAULT_PORT)))

        # Invia comando di login
        client_socket.send(f"LOGIN:{username}:{password}".encode("utf-8"))

        # Ricevi risposta
        response = client_socket.recv(1024).decode("utf-8")

        if response != "Autenticazione riuscita":
            dpg.set_value("logerr", response)
            client_socket.close()
            return

        current_username = username
        listen_thread = threading.Thread(target=listen_to_server)
        listen_thread.daemon = True
        listen_thread.start()

        dpg.configure_item("chat", show=True)
        dpg.set_value("tabbar", "chat")
        dpg.set_value("logerr", "")
        server_started = True

    except Exception as e:
        dpg.set_value("logerr", f"Errore durante il login: {str(e)}")
        if client_socket:
            client_socket.close()


def listen_to_server():
    global client_socket, chatlog
    while True:
        try:
            msg = client_socket.recv(1024).decode("utf-8")
            if not msg:
                break
            with chatlog_lock:
                chatlog = chatlog + "\n" + msg
                dpg.set_value("chatlog_field", chatlog)
        except Exception as e:
            print(f"Error in listen_to_server: {e}")
            break


def send_msg():
    global client_socket, chatlog, current_username
    msg = dpg.get_value("input_txt")
    if not msg:
        return

    timestamp = str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    formatted_msg = f"{timestamp} - {current_username}: {msg}"

    try:
        client_socket.send((timestamp + " - " + msg).encode("utf-8"))
        with chatlog_lock:
            chatlog = chatlog + "\n" + formatted_msg
        dpg.set_value("input_txt", "")
    except Exception as e:
        dpg.set_value("logerr", f"Errore durante l'invio del messaggio: {str(e)}")


with dpg.window(label="Chat", tag="window"):
    with dpg.tab_bar(tag="tabbar"):
        with dpg.tab(label="Login", tag="login"):
            dpg.add_text("Login")
            dpg.add_input_text(label="Username", tag="username")
            dpg.add_input_text(label="Password", tag="password", password=True)
            dpg.add_button(label="Login", callback=login)
            dpg.add_button(label="Register", callback=register)
            dpg.add_text("", tag="logerr")

        with dpg.tab(label="Chat", tag="chat", show=False):
            dpg.add_text("Chat")
            dpg.add_input_text(
                tag="chatlog_field", multiline=True, readonly=True, tracked=True,
                track_offset=1, width=-1, height=600)
            with dpg.group(horizontal=True):
                dpg.add_input_text(width=750, tag="input_txt", on_enter=True, callback=send_msg)
                dpg.add_button(label="Invia", callback=send_msg)

dpg.set_primary_window("window", True)
dpg.setup_dearpygui()
dpg.show_viewport()

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

dpg.destroy_context()