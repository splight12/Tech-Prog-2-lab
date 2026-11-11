import json
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 8000
DB = Path(__file__).with_name("database.db")
STORAGE = Path(__file__).with_name("files")
SESSIONS = {}


def init_db():
    STORAGE.mkdir(exist_ok=True)
    with sqlite3.connect(DB) as con: #первичное создание бд
        con.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, password TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS folders (id INTEGER PRIMARY KEY, name TEXT, owner_id INTEGER)")
        con.execute("CREATE TABLE IF NOT EXISTS permissions (folder_id INTEGER, user_id INTEGER, permission TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, folder_id INTEGER, name TEXT)")

        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            con.execute("INSERT INTO users (username, password) VALUES ('admin', 'admin-pass')")
            con.execute("INSERT INTO users (username, password) VALUES ('guest', 'guest-pass')")
            con.execute("INSERT INTO folders (name, owner_id) VALUES ('Shared', 1)")
            con.execute("INSERT INTO folders (name, owner_id) VALUES ('admins Private', 1)")
            con.execute("INSERT INTO permissions VALUES (1, 2, 'READ')")
            sample = STORAGE / "private_sample.txt"
            sample.write_text(
                "админ любит чебуреки с сыром, но об этом никто не должен знать :0",
                encoding="utf-8"
            )
            con.execute(
                "INSERT INTO files (folder_id, name) VALUES (2, ?)", (sample.name,))
            print("база данных создана")

def get_permission(user_id, folder_id):
    with sqlite3.connect(DB) as con:
        folder = con.execute("SELECT owner_id FROM folders WHERE id=?", (folder_id,)).fetchone()
        if folder is None: #на случай если папки нет
            return None
        if folder[0] == user_id: #чек владельца
            return "FULL"
        grant = con.execute("SELECT permission FROM permissions WHERE folder_id=? AND user_id=?", (folder_id, user_id)).fetchone()
    if grant: #смотрим есть ли права на папку
        return grant[0] #возвращаем прочитанные права если они вообще есть
    return None

class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body, headers=None, content_type="text/plain; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data) #отправляем данные клиенту

    def current_user(self): #типикал строка куки: Cookie: session_id=abc123xyz; theme=dark
        for part in self.headers.get("Cookie", ""  '''на случай если нет кукисов''').split(";"): 
            name, _, value = part.strip().partition("=")
            if name == "storage_session":
                return SESSIONS.get(value)
        return None

    def do_POST(self):
        if self.path != "/login":
            return self.reply(404, "неизвестный запрос")

        length = int(self.headers.get("Content-Length", "0"))
        data = parse_qs(self.rfile.read(length).decode("utf-8")) #принимаем байты в словарь
        username = data.get("username", [""])[0]
        password = data.get("password", [""])[0]
        with sqlite3.connect(DB) as con:
            user = con.execute(
                "SELECT id FROM users WHERE username=? AND password=?", (username, password)).fetchone()
        if user is None:
            return self.reply(401, "неверный логин или пароль")

        token = secrets.token_hex(16)
        SESSIONS[token] = user[0] #типикал сет куки строка Set-Cookie: session_id=abc123xyz
        return self.reply(200, "вход выполнен", {
            "Set-Cookie": "storage_session=" + token
        })

    def do_GET(self):
        user_id = self.current_user() #проверка автоизации
        if user_id is None:
            return self.reply(401, "войдите в систему")

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query) #извдекаем запрос

        if parsed.path == "/api/cd": #запрос на доступ к папке
            name = params.get("name", [""])[0] #смотрим имя папки

            #!!! имя папки напрямую попадает в SQL-запрос
            sql = "SELECT id, name, owner_id FROM folders WHERE name='" + name + "'"
            with sqlite3.connect(DB) as con:
                rows = con.execute(sql).fetchall()

            result = [
                {"id": row[0], "name": row[1]}
                for row in rows if get_permission(user_id, row[0]) is not None #только те папки берем, к каким есть доступ
            ]
            if not result:
                return self.reply(403, "папка не найдена или нет доступа")
            return self.reply(200, json.dumps(result), content_type="application/json") #отправляем этот список папок

        if parsed.path == "/download": #скачивание и чтение содержимого
            file_id = params.get("id", [""])[0]
            with sqlite3.connect(DB) as con:
                row = con.execute("SELECT folder_id, name FROM files WHERE id=?", (file_id,)).fetchone()
            if row is None:
                return self.reply(404, "файл не найден")

            #!!! нет проверки права на чтение папки
            path = STORAGE / row[1] #row[1] - имя файла
            if not path.is_file():
                return self.reply(404, "файл не найден")
            return self.reply(200, path.read_text(encoding="utf-8"))

        return self.reply(404, "неизвестный запрос")

init_db()
print("Storage запущен на http://" + HOST + ":" + str(PORT), flush=True)
HTTPServer((HOST, PORT), Handler).serve_forever()