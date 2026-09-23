from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor
from pymysql.err import IntegrityError
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
SESSIONS: dict[str, int] = {}
STREAM_TOKENS: dict[str, tuple[int, int, datetime]] = {}
DEMO_VIDEO = "https://storage.googleapis.com/coverr-main/mp4/Mt_Baker.mp4"
UPLOAD_DIR = ROOT / "uploads" / "videos"
MAX_VIDEO_BYTES = 1024 * 1024 * 1024
mysql_password = os.getenv("MYSQL_PASSWORD", "")
MYSQL = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    # PyMySQL defaults to latin-1 for str passwords. Passing UTF-8 bytes also supports Chinese passwords.
    "password": mysql_password.encode("utf-8") if mysql_password else "",
    "database": os.getenv("MYSQL_DATABASE", "course_platform"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
    "autocommit": False,
}

app = FastAPI(
    title="知学课堂 API",
    version="1.0.0",
    description="录播课程平台接口。除注册与登录外，所有接口均需 Bearer Token。",
    openapi_tags=[
        {"name": "认证", "description": "注册、登录、退出与当前用户信息"},
        {"name": "课程", "description": "学生端课程、目录、播放与学习进度"},
        {"name": "管理后台", "description": "管理员和讲师的统计、用户、课程与授权操作"},
    ],
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def password_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean_chapter_title(value: str) -> str:
    """Store chapter titles without a display sequence; UI generates it from sort_order."""
    return re.sub(r"^第\s*(?:[一二三四五六七八九十百千]+|\d+)\s*章[：:\s]*", "", value.strip())


class Database:
    """Small adapter that keeps SQL parameters safe and returns dictionary rows."""

    def __init__(self, connection: pymysql.Connection):
        self.connection = connection

    def execute(self, sql: str, params: tuple = ()) -> Any:
        cursor = self.connection.cursor()
        cursor.execute(sql.replace("?", "%s"), params)
        return cursor

    def executemany(self, sql: str, params: list[tuple]) -> Any:
        cursor = self.connection.cursor()
        cursor.executemany(sql.replace("?", "%s"), params)
        return cursor

    def commit(self) -> None:
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def db() -> Database:
    return Database(pymysql.connect(**MYSQL))


def init_db() -> None:
    server_config = {key: value for key, value in MYSQL.items() if key not in ("database", "autocommit")}
    server = pymysql.connect(**server_config)
    with server.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL['database']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    server.close()
    conn = db()
    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
          id BIGINT PRIMARY KEY AUTO_INCREMENT, username VARCHAR(64) UNIQUE NOT NULL, name VARCHAR(100) NOT NULL,
          password_hash CHAR(64) NOT NULL, role VARCHAR(20) NOT NULL DEFAULT 'student', status VARCHAR(20) DEFAULT 'active', created_at DATETIME NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS courses (
          id BIGINT PRIMARY KEY AUTO_INCREMENT, title VARCHAR(200) NOT NULL, description TEXT NOT NULL,
          teacher VARCHAR(100) NOT NULL, category VARCHAR(100) NOT NULL, cover VARCHAR(32), status VARCHAR(20) DEFAULT 'published', created_at DATETIME NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS chapters (
          id BIGINT PRIMARY KEY AUTO_INCREMENT, course_id BIGINT NOT NULL, title VARCHAR(200) NOT NULL, sort_order INT NOT NULL,
          CONSTRAINT fk_chapter_course FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS lessons (
          id BIGINT PRIMARY KEY AUTO_INCREMENT, chapter_id BIGINT NOT NULL, title VARCHAR(200) NOT NULL, duration INT NOT NULL,
          sort_order INT NOT NULL, is_preview TINYINT DEFAULT 0, video_id BIGINT NULL,
          CONSTRAINT fk_lesson_chapter FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS videos (
          id BIGINT PRIMARY KEY AUTO_INCREMENT, original_filename VARCHAR(255) NOT NULL, storage_key VARCHAR(255) NOT NULL UNIQUE,
          content_type VARCHAR(100) NOT NULL, file_size BIGINT NOT NULL, created_at DATETIME NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS enrollments (
          id BIGINT PRIMARY KEY AUTO_INCREMENT, user_id BIGINT NOT NULL, course_id BIGINT NOT NULL,
          start_time DATETIME NOT NULL, expire_time DATETIME NULL, status VARCHAR(20) DEFAULT 'active', UNIQUE KEY uq_enrollment(user_id, course_id),
          CONSTRAINT fk_enrollment_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
          CONSTRAINT fk_enrollment_course FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS learning_progress (
          id BIGINT PRIMARY KEY AUTO_INCREMENT, user_id BIGINT NOT NULL, lesson_id BIGINT NOT NULL,
          position_sec INT DEFAULT 0, duration_sec INT DEFAULT 0, completed TINYINT DEFAULT 0,
          last_watch_time DATETIME NOT NULL, UNIQUE KEY uq_progress(user_id, lesson_id),
          CONSTRAINT fk_progress_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
          CONSTRAINT fk_progress_lesson FOREIGN KEY(lesson_id) REFERENCES lessons(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    ]
    for statement in statements:
        conn.execute(statement)
    lesson_has_video = conn.execute("""SELECT 1 FROM information_schema.columns
        WHERE table_schema=? AND table_name='lessons' AND column_name='video_id'""", (MYSQL["database"],)).fetchone()
    if not lesson_has_video:
        conn.execute("ALTER TABLE lessons ADD COLUMN video_id BIGINT NULL")
    if conn.execute("SELECT count(*) AS total FROM users").fetchone()["total"] == 0:
        conn.executemany(
            "INSERT INTO users(username,name,password_hash,role,created_at) VALUES (?,?,?,?,?)",
            [
                ("admin", "平台管理员", password_hash("admin123"), "admin", now()),
                ("student", "李同学", password_hash("123456"), "student", now()),
                ("teacher", "王老师", password_hash("teacher123"), "teacher", now()),
            ],
        )
        conn.executemany(
            "INSERT INTO courses(title,description,teacher,category,cover,created_at) VALUES (?,?,?,?,?,?)",
            [
                ("Python Web 开发入门", "从 Python 基础到 FastAPI 服务开发，建立完整的 Web 应用思维。", "王老师", "编程开发", "#4f46e5", now()),
                ("高效学习方法", "掌握目标拆解、刻意练习与知识复盘，让学习更有成果。", "陈老师", "通识成长", "#0891b2", now()),
                ("数据分析实战", "使用真实业务案例练习数据清洗、分析和可视化表达。", "刘老师", "数据科学", "#ea580c", now()),
            ],
        )
        chapters = [(1, "第一章：认识 FastAPI", 1), (1, "第二章：构建 API", 2), (2, "第一章：学习系统", 1), (3, "第一章：分析流程", 1)]
        conn.executemany("INSERT INTO chapters(course_id,title,sort_order) VALUES (?,?,?)", chapters)
        lessons = [
            (1, "1.1 课程介绍与环境准备", 480, 1, 1), (1, "1.2 路由与请求参数", 720, 2, 0),
            (2, "2.1 Pydantic 数据模型", 660, 1, 0), (2, "2.2 用户认证接口", 840, 2, 0),
            (3, "1.1 制定可执行的目标", 600, 1, 1), (3, "1.2 建立复盘习惯", 540, 2, 0),
            (4, "1.1 从问题到指标", 720, 1, 1), (4, "1.2 数据清洗实操", 900, 2, 0),
        ]
        conn.executemany("INSERT INTO lessons(chapter_id,title,duration,sort_order,is_preview) VALUES (?,?,?,?,?)", lessons)
        conn.execute("INSERT INTO enrollments(user_id,course_id,start_time,status) VALUES (2,1,?, 'active')", (now(),))
        conn.execute("INSERT INTO learning_progress(user_id,lesson_id,position_sec,duration_sec,last_watch_time) VALUES (2,1,168,480,?)", (now(),))
    conn.commit()
    conn.close()


@app.on_event("startup")
def startup() -> None:
    init_db()


def serialize_user(row: dict) -> dict:
    return {"id": row["id"], "username": row["username"], "name": row["name"], "role": row["role"], "status": row["status"]}


def current_user(request: Request) -> dict:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    user_id = SESSIONS.get(token)
    if not user_id:
        raise HTTPException(401, "请先登录")
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE id=? AND status='active'", (user_id,)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(401, "账号不可用")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] not in ("admin", "teacher"):
        raise HTTPException(403, "需要管理权限")
    return user


class LoginPayload(BaseModel):
    username: str
    password: str


class RegisterPayload(BaseModel):
    username: str
    name: str
    password: str


class ProgressPayload(BaseModel):
    position_sec: int
    duration_sec: int
    completed: bool = False


class CoursePayload(BaseModel):
    title: str
    description: str
    teacher: str = "平台讲师"
    category: str = "未分类"


class EnrollmentPayload(BaseModel):
    user_id: int
    course_id: int


class ChapterPayload(BaseModel):
    title: str


class LessonPayload(BaseModel):
    title: str
    duration: int = 0
    is_preview: bool = False


class LessonUpdatePayload(BaseModel):
    title: str
    is_preview: bool = False


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.post("/api/auth/login", tags=["认证"])
def login(payload: LoginPayload) -> dict:
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE username=?", (payload.username.strip(),)).fetchone()
    conn.close()
    if not user or user["password_hash"] != password_hash(payload.password) or user["status"] != "active":
        raise HTTPException(401, "账号或密码错误")
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user["id"]
    return {"token": token, "user": serialize_user(user)}


@app.post("/api/auth/register", status_code=201, tags=["认证"])
def register(payload: RegisterPayload) -> dict:
    username = payload.username.strip().lower()
    name = payload.name.strip()
    if not 3 <= len(username) <= 64 or not username.replace("_", "").isalnum():
        raise HTTPException(422, "账号须为 3 至 64 位字母、数字或下划线")
    if not 2 <= len(name) <= 100:
        raise HTTPException(422, "姓名须为 2 至 100 个字符")
    if len(payload.password) < 6:
        raise HTTPException(422, "密码至少需要 6 位")
    conn = db()
    try:
        cursor = conn.execute(
            "INSERT INTO users(username,name,password_hash,role,status,created_at) VALUES (?,?,?,'student','active',?)",
            (username, name, password_hash(payload.password), now()),
        )
        conn.commit()
        user_id = cursor.lastrowid
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    except IntegrityError:
        raise HTTPException(409, "该账号已被注册")
    finally:
        conn.close()
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user_id
    return {"token": token, "user": serialize_user(user)}


@app.post("/api/auth/logout", tags=["认证"])
def logout(request: Request) -> dict:
    SESSIONS.pop(request.headers.get("Authorization", "").removeprefix("Bearer "), None)
    return {"ok": True}


@app.get("/api/me", tags=["认证"])
def me(user: dict = Depends(current_user)) -> dict:
    return serialize_user(user)


def course_card(conn: Database, row: dict, user_id: Optional[int] = None) -> dict:
    lessons = conn.execute("SELECT count(*) AS total FROM lessons l JOIN chapters ch ON l.chapter_id=ch.id WHERE ch.course_id=?", (row["id"],)).fetchone()["total"]
    result = dict(row)
    result["lesson_count"] = lessons
    result["enrolled"] = False
    result["progress"] = 0
    if user_id:
        result["enrolled"] = bool(conn.execute("SELECT 1 FROM enrollments WHERE user_id=? AND course_id=? AND status='active'", (user_id, row["id"])).fetchone())
        progress = conn.execute("""SELECT coalesce(sum(p.position_sec),0) watched, coalesce(sum(l.duration),0) total
            FROM lessons l JOIN chapters ch ON l.chapter_id=ch.id LEFT JOIN learning_progress p ON p.lesson_id=l.id AND p.user_id=? WHERE ch.course_id=?""", (user_id, row["id"])).fetchone()
        result["progress"] = min(100, round(progress["watched"] * 100 / progress["total"])) if progress["total"] else 0
    return result


@app.get("/api/courses", tags=["课程"])
def courses(user: dict = Depends(current_user)) -> list[dict]:
    conn = db()
    rows = conn.execute("SELECT * FROM courses WHERE status='published' ORDER BY id").fetchall()
    output = [course_card(conn, row, user["id"]) for row in rows]
    conn.close()
    return output


@app.get("/api/courses/{course_id}", tags=["课程"])
def course_detail(course_id: int, user: dict = Depends(current_user)) -> dict:
    conn = db()
    course = conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    if not course:
        raise HTTPException(404, "课程不存在")
    result = course_card(conn, course, user["id"])
    chapters = conn.execute("SELECT * FROM chapters WHERE course_id=? ORDER BY sort_order", (course_id,)).fetchall()
    result["chapters"] = []
    for chapter in chapters:
        lessons = conn.execute("""SELECT l.*, v.original_filename, coalesce(p.position_sec,0) position_sec, coalesce(p.completed,0) completed
            FROM lessons l LEFT JOIN videos v ON v.id=l.video_id LEFT JOIN learning_progress p ON p.lesson_id=l.id AND p.user_id=? WHERE l.chapter_id=? ORDER BY l.sort_order""", (user["id"], chapter["id"])).fetchall()
        result["chapters"].append({"id": chapter["id"], "title": chapter["title"], "lessons": [dict(x) for x in lessons]})
    conn.close()
    return result


def can_watch(conn: Database, user_id: int, lesson_id: int) -> bool:
    row = conn.execute("""SELECT l.is_preview FROM lessons l WHERE l.id=?""", (lesson_id,)).fetchone()
    if not row:
        raise HTTPException(404, "课时不存在")
    if row["is_preview"]:
        return True
    return bool(conn.execute("""SELECT 1 FROM enrollments e JOIN chapters ch ON e.course_id=ch.course_id
        JOIN lessons l ON l.chapter_id=ch.id WHERE e.user_id=? AND l.id=? AND e.status='active'""", (user_id, lesson_id)).fetchone())


@app.get("/api/lessons/{lesson_id}/play", tags=["课程"])
def play(lesson_id: int, user: dict = Depends(current_user)) -> dict:
    conn = db()
    allowed = can_watch(conn, user["id"], lesson_id)
    video = conn.execute("""SELECT v.storage_key FROM lessons l LEFT JOIN videos v ON v.id=l.video_id WHERE l.id=?""", (lesson_id,)).fetchone()
    conn.close()
    if not allowed:
        raise HTTPException(403, "该课时需要先开通课程")
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    url = DEMO_VIDEO
    if video and video["storage_key"]:
        stream_token = secrets.token_urlsafe(24)
        STREAM_TOKENS[stream_token] = (user["id"], lesson_id, expiry)
        url = f"/api/videos/stream/{lesson_id}?token={stream_token}"
    return {"url": url, "expires_at": expiry.isoformat(), "watermark": f"猴子课堂 · {user['name']} · {user['username']}"}


@app.get("/api/videos/stream/{lesson_id}", tags=["课程"])
def stream_video(lesson_id: int, token: str = Query(...)) -> FileResponse:
    grant = STREAM_TOKENS.get(token)
    if not grant or grant[1] != lesson_id or grant[2] < datetime.now(timezone.utc):
        raise HTTPException(403, "播放链接已失效，请重新获取")
    conn = db()
    if not can_watch(conn, grant[0], lesson_id):
        conn.close()
        raise HTTPException(403, "无播放权限")
    video = conn.execute("""SELECT v.storage_key, v.original_filename, v.content_type FROM lessons l
        JOIN videos v ON v.id=l.video_id WHERE l.id=?""", (lesson_id,)).fetchone()
    conn.close()
    if not video:
        raise HTTPException(404, "该课时尚未上传视频")
    path = UPLOAD_DIR / video["storage_key"]
    if not path.is_file():
        raise HTTPException(404, "视频文件不存在")
    return FileResponse(path, media_type=video["content_type"], filename=video["original_filename"])


@app.put("/api/lessons/{lesson_id}/progress", tags=["课程"])
def save_progress(lesson_id: int, payload: ProgressPayload, user: dict = Depends(current_user)) -> dict:
    conn = db()
    if not can_watch(conn, user["id"], lesson_id):
        conn.close()
        raise HTTPException(403, "无学习权限")
    completed = int(payload.completed or payload.position_sec >= max(0, payload.duration_sec - 10))
    conn.execute("""INSERT INTO learning_progress(user_id,lesson_id,position_sec,duration_sec,completed,last_watch_time)
       VALUES (?,?,?,?,?,?) ON DUPLICATE KEY UPDATE position_sec=VALUES(position_sec),
       duration_sec=VALUES(duration_sec),completed=VALUES(completed),last_watch_time=VALUES(last_watch_time)""",
       (user["id"], lesson_id, max(0, payload.position_sec), max(0, payload.duration_sec), completed, now()))
    conn.commit(); conn.close()
    return {"ok": True, "completed": bool(completed)}


@app.get("/api/admin/overview", tags=["管理后台"])
def overview(_: dict = Depends(require_admin)) -> dict:
    conn = db()
    result = {"students": conn.execute("SELECT count(*) AS total FROM users WHERE role='student'").fetchone()["total"],
              "courses": conn.execute("SELECT count(*) AS total FROM courses WHERE status='published'").fetchone()["total"],
              "enrollments": conn.execute("SELECT count(*) AS total FROM enrollments WHERE status='active'").fetchone()["total"],
              "watch_minutes": conn.execute("SELECT coalesce(sum(position_sec),0)/60 AS total FROM learning_progress").fetchone()["total"]}
    conn.close(); return result


@app.get("/api/admin/users", tags=["管理后台"])
def admin_users(_: dict = Depends(require_admin)) -> list[dict]:
    conn = db(); rows = conn.execute("SELECT id,username,name,role,status,created_at FROM users ORDER BY id").fetchall(); conn.close()
    return [dict(row) for row in rows]


@app.get("/api/admin/courses", tags=["管理后台"])
def admin_courses(_: dict = Depends(require_admin)) -> list[dict]:
    conn = db()
    rows = conn.execute("""SELECT c.*,
        (SELECT count(*) FROM chapters ch WHERE ch.course_id=c.id) AS chapter_count,
        (SELECT count(*) FROM lessons l JOIN chapters ch ON l.chapter_id=ch.id WHERE ch.course_id=c.id) AS lesson_count
        FROM courses c ORDER BY c.id DESC""").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/api/admin/courses", tags=["管理后台"])
def create_course(payload: CoursePayload, _: dict = Depends(require_admin)) -> dict:
    conn = db(); cursor = conn.execute("INSERT INTO courses(title,description,teacher,category,cover,created_at) VALUES (?,?,?,?,?,?)", (payload.title, payload.description, payload.teacher, payload.category, "#7c3aed", now())); conn.commit()
    row = conn.execute("SELECT * FROM courses WHERE id=?", (cursor.lastrowid,)).fetchone(); conn.close()
    return dict(row)


@app.post("/api/admin/courses/{course_id}/chapters", tags=["管理后台"])
def create_chapter(course_id: int, payload: ChapterPayload, _: dict = Depends(require_admin)) -> dict:
    title = clean_chapter_title(payload.title)
    if not title:
        raise HTTPException(422, "章节名称不能为空")
    conn = db()
    if not conn.execute("SELECT 1 FROM courses WHERE id=?", (course_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "课程不存在")
    sort_order = conn.execute("SELECT coalesce(max(sort_order),0) AS total FROM chapters WHERE course_id=?", (course_id,)).fetchone()["total"] + 1
    cursor = conn.execute("INSERT INTO chapters(course_id,title,sort_order) VALUES (?,?,?)", (course_id, title, sort_order))
    conn.commit()
    row = conn.execute("SELECT * FROM chapters WHERE id=?", (cursor.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def normalize_chapter_order(conn: Database, course_id: int) -> None:
    chapters = conn.execute("SELECT id FROM chapters WHERE course_id=? ORDER BY sort_order, id", (course_id,)).fetchall()
    for position, chapter in enumerate(chapters, start=1):
        conn.execute("UPDATE chapters SET sort_order=? WHERE id=?", (position, chapter["id"]))


@app.patch("/api/admin/chapters/{chapter_id}", tags=["管理后台"])
def update_chapter(chapter_id: int, payload: ChapterPayload, _: dict = Depends(require_admin)) -> dict:
    title = clean_chapter_title(payload.title)
    if not title:
        raise HTTPException(422, "章节名称不能为空")
    conn = db()
    chapter = conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
    if not chapter:
        conn.close()
        raise HTTPException(404, "章节不存在")
    conn.execute("UPDATE chapters SET title=? WHERE id=?", (title, chapter_id))
    conn.commit()
    row = conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
    conn.close()
    return dict(row)


@app.delete("/api/admin/chapters/{chapter_id}", tags=["管理后台"])
def delete_chapter(chapter_id: int, _: dict = Depends(require_admin)) -> dict:
    conn = db()
    chapter = conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
    if not chapter:
        conn.close()
        raise HTTPException(404, "章节不存在")
    videos = conn.execute("""SELECT v.storage_key FROM lessons l JOIN videos v ON v.id=l.video_id
        WHERE l.chapter_id=?""", (chapter_id,)).fetchall()
    conn.execute("DELETE FROM chapters WHERE id=?", (chapter_id,))
    normalize_chapter_order(conn, chapter["course_id"])
    conn.commit()
    conn.close()
    for video in videos:
        path = UPLOAD_DIR / video["storage_key"]
        if path.is_file():
            path.unlink()
    return {"ok": True}


@app.post("/api/admin/chapters/{chapter_id}/lessons", tags=["管理后台"])
def create_lesson(chapter_id: int, payload: LessonPayload, _: dict = Depends(require_admin)) -> dict:
    title = payload.title.strip()
    if not title or not 0 <= payload.duration <= 8 * 60 * 60:
        raise HTTPException(422, "请填写课时名称；视频时长会在上传后自动读取")
    conn = db()
    if not conn.execute("SELECT 1 FROM chapters WHERE id=?", (chapter_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "章节不存在")
    sort_order = conn.execute("SELECT coalesce(max(sort_order),0) AS total FROM lessons WHERE chapter_id=?", (chapter_id,)).fetchone()["total"] + 1
    cursor = conn.execute("INSERT INTO lessons(chapter_id,title,duration,sort_order,is_preview) VALUES (?,?,?,?,?)", (chapter_id, title, payload.duration, sort_order, int(payload.is_preview)))
    conn.commit()
    row = conn.execute("SELECT * FROM lessons WHERE id=?", (cursor.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


@app.patch("/api/admin/lessons/{lesson_id}", tags=["管理后台"])
def update_lesson(lesson_id: int, payload: LessonUpdatePayload, _: dict = Depends(require_admin)) -> dict:
    title = payload.title.strip()
    if not title:
        raise HTTPException(422, "课时名称不能为空")
    conn = db()
    if not conn.execute("SELECT 1 FROM lessons WHERE id=?", (lesson_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "课时不存在")
    conn.execute("UPDATE lessons SET title=?, is_preview=? WHERE id=?", (title, int(payload.is_preview), lesson_id))
    conn.commit()
    row = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    conn.close()
    return dict(row)


@app.delete("/api/admin/lessons/{lesson_id}", tags=["管理后台"])
def delete_lesson(lesson_id: int, _: dict = Depends(require_admin)) -> dict:
    conn = db()
    lesson = conn.execute("""SELECT l.*, v.storage_key FROM lessons l LEFT JOIN videos v ON v.id=l.video_id WHERE l.id=?""", (lesson_id,)).fetchone()
    if not lesson:
        conn.close()
        raise HTTPException(404, "课时不存在")
    conn.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
    conn.commit()
    conn.close()
    if lesson["storage_key"]:
        path = UPLOAD_DIR / lesson["storage_key"]
        if path.is_file():
            path.unlink()
    return {"ok": True}


@app.post("/api/admin/lessons/{lesson_id}/video", tags=["管理后台"])
def upload_lesson_video(lesson_id: int, file: UploadFile = File(...), duration: int = Form(...), _: dict = Depends(require_admin)) -> dict:
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() != ".mp4" or file.content_type not in {"video/mp4", "application/octet-stream"}:
        raise HTTPException(422, "仅支持 MP4 视频文件")
    if not 1 <= duration <= 8 * 60 * 60:
        raise HTTPException(422, "无法读取有效视频时长，请重新选择 MP4 文件")
    conn = db()
    if not conn.execute("SELECT 1 FROM lessons WHERE id=?", (lesson_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "课时不存在")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    storage_key = f"{uuid.uuid4().hex}.mp4"
    target = UPLOAD_DIR / storage_key
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise HTTPException(413, "视频不能超过 1 GB")
                output.write(chunk)
        cursor = conn.execute("INSERT INTO videos(original_filename,storage_key,content_type,file_size,created_at) VALUES (?,?,?,?,?)", (filename, storage_key, "video/mp4", size, now()))
        conn.execute("UPDATE lessons SET video_id=?, duration=? WHERE id=?", (cursor.lastrowid, duration, lesson_id))
        conn.commit()
    except Exception:
        if target.exists():
            target.unlink()
        conn.connection.rollback()
        raise
    finally:
        file.file.close()
        conn.close()
    return {"ok": True, "filename": filename, "file_size": size, "duration": duration}


@app.post("/api/admin/enrollments", tags=["管理后台"])
def grant_enrollment(payload: EnrollmentPayload, _: dict = Depends(require_admin)) -> dict:
    conn = db()
    conn.execute("INSERT INTO enrollments(user_id,course_id,start_time,status) VALUES (?,?,?,'active') ON DUPLICATE KEY UPDATE status='active',start_time=VALUES(start_time)", (payload.user_id, payload.course_id, now()))
    conn.commit(); conn.close(); return {"ok": True}
