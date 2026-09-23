# 知学课堂 MVP

基于计划书实现的录播课程平台演示版。包含学生端和管理端：注册登录、MySQL 用户维护、课程授权、章节课时、受保护播放地址、学习进度续播、课程及学生管理。

## 运行

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:MYSQL_HOST="127.0.0.1"
$env:MYSQL_PORT="3306"
$env:MYSQL_USER="root"
$env:MYSQL_PASSWORD="ljh737688"
$env:MYSQL_DATABASE="course_platform"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 59322
```

浏览器访问 `http://127.0.0.1:59322`。应用首次启动时会自动创建 `course_platform` 数据库及业务表；MySQL 账号需具备建库、建表权限。

也可将连接参数写入 [`.env.example`](.env.example) 的副本 `.env`。启动命令会自动读取 `.env` 文件。

详细的部署、角色操作、接口调试和 API 管理规范请阅读 [使用说明与 API 管理](docs/使用说明与API管理.md)。

演示账号：

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 学员 | student | 123456 |
| 管理员 | admin | admin123 |

## 当前实现与生产替换

- 数据层：MySQL 8 + PyMySQL，用户、课程、授权与学习进度均写入关系型数据表。
- 会话：内存 Token；生产环境替换为 JWT + Redis 黑名单/限流。
- 视频：使用公开演示视频；生产环境由对象存储、FFmpeg HLS 转码、CDN 签名 URL 提供。
- 前端：单页原型；可按计划书拆分为 Vue 3 + Vite + Element Plus 工程。
