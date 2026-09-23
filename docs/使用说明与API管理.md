# 知学课堂使用说明与 API 管理

本文面向平台部署者、课程管理员和学员，说明本地运行、MySQL 配置、日常操作及 API 管理方法。

## 1. 系统能力

平台目前支持学员注册与登录、课程浏览、试听和已授权课程学习、学习进度保存，以及管理员创建课程、查看用户和开通课程权限。用户、课程、授权与学习进度保存在 MySQL 中。

## 2. 部署前准备

- Python 3.11 或更高版本
- MySQL 8.0 或更高版本，服务监听在可访问的主机和端口
- Windows PowerShell（以下命令以 Windows 为例）

安装依赖：

```powershell
cd E:\network
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. 配置 MySQL

复制环境变量示例文件：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填写实际 MySQL 账号。不要把 `.env` 提交到 Git 仓库。

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=替换为真实密码
MYSQL_DATABASE=course_platform
```

应用启动时会自动创建 `course_platform` 数据库及下列表：

| 表名 | 用途 |
| --- | --- |
| `users` | 用户账号、密码摘要、角色和状态 |
| `courses` | 课程基础信息 |
| `chapters`、`lessons` | 课程目录和课时 |
| `enrollments` | 学员课程授权 |
| `learning_progress` | 学员观看位置和完成状态 |

建议生产环境专门创建低权限账号，而不是使用 root：

```sql
CREATE USER 'course_app'@'localhost' IDENTIFIED BY '请替换为强密码';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX ON course_platform.* TO 'course_app'@'localhost';
FLUSH PRIVILEGES;
```

首次运行若账号没有建库权限，请由数据库管理员先执行：

```sql
CREATE DATABASE course_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

## 4. 启动与访问

启动开发服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 59322
```

浏览器入口：<http://127.0.0.1:59322>

默认演示账号：

| 角色 | 账号 | 密码 | 用途 |
| --- | --- | --- | --- |
| 学员 | `student` | `123456` | 学习、试听、保存进度 |
| 管理员 | `admin` | `admin123` | 创建课程、开通学员权限、查看统计 |

首次部署后应立即修改或停用演示账号。

## 5. 学员操作

1. 在登录页选择“没有账号？立即注册”。
2. 输入姓名、3 至 64 位账号和至少 6 位密码；注册成功后会自动登录。
3. 在“全部课程”浏览课程，标有“可试听”的课程可直接打开试听课时。
4. 已开通课程会出现在“我的课程”，点击“继续学习”即可恢复最近进度。
5. 视频播放时系统每 15 秒保存一次进度，播放结束也会更新完成状态。

## 6. 管理员操作

1. 用管理员账号登录，顶部会出现“管理后台”。
2. 在后台查看学员数量、已发布课程、有效授权和总学习时长。
3. 点击“新建课程”录入课程名称、简介和讲师。
4. 在“课程内容管理”中点击“统一编辑课程内容”，进入单独的课程编辑器页面。
5. 在同一编辑器中创建章节，选择所属章节，填写课时名称和是否试听，再选择 MP4 视频。
6. 系统会自动读取 MP4 的实际时长，创建课时并上传视频后，把时长写入 MySQL。单个视频上限为 1 GB，文件会保存到项目的 `uploads/videos`；MySQL 的 `videos` 表仅保存文件名、路径键和大小。
7. 在用户列表中点击“开通课程”，输入课程 ID，为指定学员授权。

本地上传版适合开发验证。服务器部署时，`uploads/videos` 必须使用持久化磁盘或改为对象存储；多台应用服务器不能各自保存一份视频。

## 7. API 文档与调试

服务启动后，FastAPI 自动生成以下文档：

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:59322/docs` | Swagger UI：浏览、填写参数并调试接口 |
| `http://127.0.0.1:59322/redoc` | ReDoc：适合阅读接口说明 |
| `http://127.0.0.1:59322/openapi.json` | OpenAPI 标准 JSON，可导入 Apifox、Postman 等工具 |

建议使用 Swagger UI 调试：先调用 `POST /api/auth/login` 或 `POST /api/auth/register`，复制响应中的 `token`；然后点击右上角 **Authorize**，输入 `Bearer 空格 token`，即可调试需登录的接口。

## 8. 当前接口清单

### 认证

| 方法 | 地址 | 是否鉴权 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | 否 | 注册学员并自动登录 |
| POST | `/api/auth/login` | 否 | 登录并获得 Token |
| POST | `/api/auth/logout` | 是 | 注销当前 Token |
| GET | `/api/me` | 是 | 查询当前登录用户 |

注册示例：

```json
{
  "username": "zhangsan",
  "name": "张三",
  "password": "a-strong-password"
}
```

### 学员课程

| 方法 | 地址 | 说明 |
| --- | --- | --- |
| GET | `/api/courses` | 获取全部已发布课程及当前用户学习进度 |
| GET | `/api/courses/{course_id}` | 获取课程章节和课时 |
| GET | `/api/lessons/{lesson_id}/play` | 校验授权后返回播放地址和水印文字 |
| PUT | `/api/lessons/{lesson_id}/progress` | 保存观看位置和完成状态 |

进度上报示例：

```json
{
  "position_sec": 180,
  "duration_sec": 480,
  "completed": false
}
```

### 管理后台

| 方法 | 地址 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/admin/overview` | 管理员、讲师 | 读取统计数据 |
| GET | `/api/admin/users` | 管理员、讲师 | 查询用户列表 |
| POST | `/api/admin/courses` | 管理员、讲师 | 创建课程 |
| POST | `/api/admin/courses/{course_id}/chapters` | 管理员、讲师 | 新增章节 |
| POST | `/api/admin/chapters/{chapter_id}/lessons` | 管理员、讲师 | 新增课时 |
| POST | `/api/admin/lessons/{lesson_id}/video` | 管理员、讲师 | 以 multipart/form-data 上传 MP4 |
| POST | `/api/admin/enrollments` | 管理员、讲师 | 为学员开通课程 |

## 9. API 接口管理建议

### 接口分组与版本

当前接口已按“认证、课程、管理后台”分组并出现在 Swagger 文档。下一阶段建议将所有业务接口迁移到 `/api/v1`，例如 `/api/v1/courses`。发生不兼容改动时新增 `/api/v2`，旧版本保留一段明确的下线期，避免前端和移动端突然失效。

### 接口契约

- 每个请求和响应均使用 Pydantic 模型定义，不直接返回数据库字段。
- 为所有写接口编写成功、权限不足、参数错误和资源不存在的示例。
- 将 `openapi.json` 纳入接口评审；前端、测试和后端以同一份契约协作。
- 在 CI 中保存 OpenAPI 文件并检查破坏性变更，例如删除字段或改变字段类型。

### 鉴权与权限

当前演示版使用内存 Token，服务重启后会失效。生产环境应替换为 JWT（短期访问令牌 + 可刷新令牌），并使用 Redis 保存黑名单、会话撤销和接口限流状态。后台接口必须统一经过角色权限校验，且应记录管理员对课程授权、停用账号等敏感操作的审计日志。

### 错误和可观测性

- 统一响应错误格式，例如 `{ "detail": "课程不存在", "code": "COURSE_NOT_FOUND" }`。
- 为每个请求生成 `request_id`，写入访问日志并返回响应头，便于排障。
- 监控接口耗时、5xx 比例、登录失败次数和数据库连接池使用量。
- 生产环境禁止把异常堆栈、SQL 语句和密码信息返回给客户端。

### 发布与安全基线

- 将数据库密码、JWT 密钥、对象存储密钥放入环境变量或密钥管理服务。
- 使用 HTTPS、CORS 白名单、请求体大小限制和速率限制。
- 对注册、登录、播放地址等高频接口实行 IP 与账号维度限流。
- 使用 Alembic 管理数据库迁移，不手动在生产数据库上改表。
- 定期备份 MySQL，并恢复演练；用户密码使用 bcrypt 或 Argon2，不使用简单哈希。

## 10. 常见问题

**提示无法连接 `127.0.0.1:3306`**：MySQL 服务未启动、端口不对，或 `.env` 中的地址不正确。可用 `Test-NetConnection 127.0.0.1 -Port 3306` 检查。

**提示账号或密码错误**：确认 `.env` 内 `MYSQL_USER`、`MYSQL_PASSWORD` 与 MySQL 账号一致。数据库密码不要保留示例文字。

**注册提示账号已被注册**：`users.username` 有唯一索引，请改用其他账号；管理员可在用户表中查看已注册用户。

**端口 59322 无法启动**：更换为其他未占用的高位端口，例如 `--port 59323`，并使用新的端口访问浏览器。

## 11. 从本地到服务器的部署顺序

1. 本地使用管理员账号创建一门课程、章节、课时并上传一个小型 MP4；注册学员后为其开通课程，确认可播放和保存进度。
2. 准备 Linux 服务器、域名、HTTPS 证书、MySQL 8 和对象存储/CDN 账号。
3. 使用 Docker Compose 部署 Nginx、FastAPI、MySQL 和 Redis；视频目录挂载到持久化卷。生产环境建议将本地上传实现替换为对象存储与 HLS 转码。
4. 设置生产 `.env`、限制 MySQL 对公网暴露、迁移演示账号、完成数据库备份和恢复测试。
5. 将域名接入 Nginx，配置 HTTPS、反向代理、上传大小限制、访问日志和安全响应头。
