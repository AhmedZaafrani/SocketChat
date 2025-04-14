import textwrap
import threading
import socket
import datetime
from string import whitespace

import dearpygui.dearpygui as dpg
from dearpygui.dearpygui import configure_item
from main import DEFAULT_IP, DEFAULT_PORT, BUFFER_SIZE

dpg.create_context()
dpg.create_viewport(title='Socket Chat', width=950, height=800)

chatlog_lock = threading.Lock()
chatlog = ""
client_socket = None
server_started = False
current_username = ""

# Definisco dimensioni di base per gli elementi
BUTTON_HEIGHT = 40
INPUT_HEIGHT = 45
SPACING = 20
LOGIN_FORM_WIDTH_RATIO = 0.5  # 50% della larghezza della viewport


def register():
    username = dpg.get_value("username")
    password = dpg.get_value("password")

    if not username or not password:
        dpg.set_value("logerr", "Username e password sono obbligatori!")
        return

    try:
        temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_socket.connect((dpg.get_value("ip"), int(DEFAULT_PORT)))
        temp_socket.send(f"REGISTER:{username}:{password}".encode("utf-8"))
        response = temp_socket.recv(BUFFER_SIZE).decode("utf-8")

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
        client_socket.connect((dpg.get_value("ip"), int(DEFAULT_PORT)))

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
            msg = client_socket.recv(BUFFER_SIZE).decode("utf-8")
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
        client_socket.send(formatted_msg.encode("utf-8"))
        with chatlog_lock:
            chatlog = chatlog + "\n" + formatted_msg
        dpg.set_value("input_txt", "")
    except Exception as e:
        dpg.set_value("logerr", f"Errore durante l'invio del messaggio: {str(e)}")


def center_items():
    viewport_width = dpg.get_viewport_width()
    viewport_height = dpg.get_viewport_height()

    # Calcola dimensioni proporzionali al viewport
    form_width = int(viewport_width * LOGIN_FORM_WIDTH_RATIO)
    side_spacer = (viewport_width - form_width) / 2

    # Aumenta la dimensione dei testi
    dpg.set_value("login_title", "LOGIN")
    dpg.configure_item("login_title", color=[255, 255, 255])

    # Aggiorna dimensioni degli elementi di login
    dpg.set_item_width("left_spacer", side_spacer)
    dpg.set_item_width("right_spacer", side_spacer)

    # Ridimensiona i campi di input
    input_width = form_width - 40  # Un po' più piccolo del form per margini
    dpg.set_item_width("ip", input_width)
    dpg.configure_item("ip", height=INPUT_HEIGHT)
    dpg.set_item_width("username", input_width)
    dpg.configure_item("username", height=INPUT_HEIGHT)
    dpg.set_item_width("password", input_width)
    dpg.configure_item("password", height=INPUT_HEIGHT)

    # Ridimensiona pulsanti
    button_width = (input_width - 20) / 2  # Dividi lo spazio disponibile per i due pulsanti con un piccolo gap
    dpg.set_item_width("login_button", button_width)
    dpg.configure_item("login_button", height=BUTTON_HEIGHT)
    dpg.set_item_width("register_button", button_width)
    dpg.configure_item("register_button", height=BUTTON_HEIGHT)

    # Aggiorna i componenti della chat
    chat_width = viewport_width - (SPACING * 2)  # Margine ai lati
    chat_height = viewport_height - 180  # Spazio per inp e altri elementi

    dpg.set_item_width("chatlog_field", chat_width)
    dpg.set_item_height("chatlog_field", chat_height)

    # Aggiorna l'input di testo della chat
    input_chat_width = chat_width - 120  # Spazio per il pulsante Invia
    dpg.set_item_width("input_txt", input_chat_width)
    dpg.configure_item("input_txt", height=INPUT_HEIGHT)

    # Aggiorna dimensione pulsante invio
    dpg.set_item_width("send_button", 100)
    dpg.configure_item("send_button", height=INPUT_HEIGHT)


def create_gui():
    with dpg.window(label="Chat", tag="window"):
        with dpg.tab_bar(tag="tabbar"):
            # Tab Login
            with dpg.tab(label="Login", tag="login"):
                with dpg.group(horizontal=True):
                    dpg.add_spacer(tag="left_spacer", width=300)  # Spaziatore a sinistra

                    with dpg.group():  # Gruppo verticale per gli elementi di login
                        dpg.add_spacer(height=SPACING * 5)  # Spaziatore in alto
                        dpg.add_text("LOGIN", tag="login_title", color=[255, 255, 255])
                        dpg.add_spacer(height=SPACING)
                        dpg.add_input_text(label="IP", tag="ip", default_value="127.0.0.1")
                        dpg.add_spacer(height=SPACING)
                        dpg.add_input_text(label="Username", tag="username")
                        dpg.add_spacer(height=SPACING)
                        dpg.add_input_text(label="Password", tag="password", password=True)
                        dpg.add_spacer(height=SPACING * 2)

                        # Gruppo orizzontale per i pulsanti, centrato
                        with dpg.group(horizontal=True):
                            dpg.add_button(label="Login", tag="login_button", callback=login)
                            dpg.add_spacer(width=SPACING)
                            dpg.add_button(label="Register", tag="register_button", callback=register)

                        dpg.add_spacer(height=SPACING)
                        dpg.add_text("", tag="logerr", color=(255, 0, 0))  # Colore rosso per errori
                        dpg.add_spacer(height=SPACING * 5)  # Spaziatore in basso

                    dpg.add_spacer(tag="right_spacer", width=300)  # Spaziatore a destra

            # Tab Chat
            with dpg.tab(label="Chat", tag="chat", show=False):
                dpg.add_text("CHAT", tag="chat_title", color=[255, 255, 255])
                dpg.add_input_text(
                    tag="chatlog_field", multiline=True, readonly=True, tracked=True,
                    track_offset=1)
                dpg.add_spacer(height=SPACING)
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="input_txt", on_enter=True, callback=send_msg)
                    dpg.add_button(label="Invia", tag="send_button", callback=send_msg)


# Creazione dell'interfaccia
create_gui()

# Aggiungi la callback per il ridimensionamento della viewport
dpg.set_viewport_resize_callback(center_items)

dpg.set_primary_window("window", True)
dpg.setup_dearpygui()
dpg.show_viewport()

# Esegui il centering iniziale dopo aver mostrato la viewport
center_items()

while dpg.is_dearpygui_running():
    if server_started:
        with chatlog_lock:
            if dpg.get_value("chatlog_field") != chatlog:
                dpg.set_value("chatlog_field", chatlog)
    dpg.render_dearpygui_frame()

if server_started:
    try:
        client_socket.send("closed connection")
        client_socket.close()
    except:
        pass

dpg.destroy_context()