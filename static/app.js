let token = localStorage.getItem("zx_token");
let me = null;
let activeCourse = null;
let activeLesson = null;

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
const chapterName = (chapter) => String(chapter.title || "").replace(/^第\s*(?:[一二三四五六七八九十百千]+|\d+)\s*章[：:\s]*/u, "");
const chapterLabel = (chapter, position) => `第${chapter.sort_order ?? position}章 ${chapterName(chapter)}`;
const api = async (path, options = {}) => {
  const response = await fetch(path, {...options, headers: {"Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {})}});
  const data = await response.json();
  if (response.status === 401) { localStorage.removeItem("zx_token"); location.href = "/"; throw Error("登录已过期"); }
  if (!response.ok) throw Error(data.detail || "请求失败");
  return data;
};

function setupHeader() {
  document.querySelectorAll("[data-user]").forEach((node) => node.textContent = `${me.name} · ${me.role === "student" ? "学员" : "管理员"}`);
  if (me.role !== "student") document.querySelectorAll("[data-admin]").forEach((node) => node.classList.remove("hidden"));
  document.querySelectorAll("[data-logout]").forEach((node) => node.onclick = async () => {
    try { await api("/api/auth/logout", {method: "POST"}); } finally { localStorage.removeItem("zx_token"); location.href = "/"; }
  });
}

async function authenticatedPage() {
  if (!token) { location.href = "/"; return false; }
  me = await api("/api/me");
  setupHeader();
  return true;
}

function courseCard(course) {
  const action = course.enrolled ? "继续学习 →" : "查看课程 →";
  const status = course.enrolled ? `<div class="progress"><i style="width:${course.progress}%"></i></div><span class="tag">已学习 ${course.progress}%</span>` : '<span class="tag">可试听</span>';
  return `<article class="card"><div class="cover" style="background:${course.cover || "#4f46e5"}">${esc(course.category)}</div><div class="card-body"><h3>${esc(course.title)}</h3><p>${esc(course.description)}</p><div class="meta">${esc(course.teacher)} · ${course.lesson_count} 个课时</div>${status}<div class="card-footer"><span></span><a class="link-button" href="/static/course.html?id=${course.id}">${action}</a></div></div></article>`;
}

async function loadCourses(mineOnly = false) {
  const courses = await api("/api/courses");
  const visible = mineOnly ? courses.filter((course) => course.enrolled) : courses;
  document.querySelector("#course-list").innerHTML = visible.length ? visible.map(courseCard).join("") : '<div class="panel empty">你还没有开通课程，先去首页看看吧。</div>';
  const count = document.querySelector("#course-count");
  if (count) count.textContent = `${courses.length} 门精选课程`;
}

async function bootHome() { if (await authenticatedPage()) await loadCourses(); }
async function bootMine() { if (await authenticatedPage()) await loadCourses(true); }

async function bootCourse() {
  if (!(await authenticatedPage())) return;
  const courseId = new URLSearchParams(location.search).get("id");
  if (!courseId) { location.href = "/static/home.html"; return; }
  activeCourse = await api(`/api/courses/${courseId}`);
  document.querySelector("#course-title").textContent = activeCourse.title;
  document.querySelector("#course-description").textContent = activeCourse.description;
  document.querySelector("#course-progress").style.width = `${activeCourse.progress}%`;
  document.querySelector("#progress-text").textContent = `课程学习进度 ${activeCourse.progress}%`;
  document.querySelector("#chapters").innerHTML = activeCourse.chapters.map((chapter, index) => `<div class="chapter"><b>${esc(chapterLabel(chapter, index + 1))}</b>${chapter.lessons.map((lesson) => `<button class="lesson" data-lesson="${lesson.id}"><span>${esc(lesson.title)} ${lesson.completed ? "✓" : ""}</span><small>${Math.ceil(lesson.duration / 60)} 分钟</small></button>`).join("")}</div>`).join("");
  document.querySelectorAll("[data-lesson]").forEach((node) => node.onclick = () => playLesson(Number(node.dataset.lesson)));
  const first = activeCourse.chapters.flatMap((chapter) => chapter.lessons).find((lesson) => lesson.position_sec) || activeCourse.chapters[0]?.lessons[0];
  if (first) playLesson(first.id);
  const player = document.querySelector("#player");
  player.addEventListener("timeupdate", () => { if (activeLesson && Math.floor(player.currentTime) % 15 === 0) saveProgress(); });
  player.addEventListener("ended", () => saveProgress(true));
}

async function playLesson(id) {
  try {
    const lesson = activeCourse.chapters.flatMap((chapter) => chapter.lessons).find((item) => item.id === id);
    const playback = await api(`/api/lessons/${id}/play`);
    const player = document.querySelector("#player");
    activeLesson = lesson; player.src = playback.url; player.currentTime = lesson.position_sec || 0;
    document.querySelector("#watermark").textContent = playback.watermark;
    document.querySelector("#lesson-title").textContent = lesson.title;
    document.querySelectorAll("[data-lesson]").forEach((node) => node.classList.toggle("selected", Number(node.dataset.lesson) === id));
    player.play().catch(() => {});
  } catch (error) { alert(error.message); }
}

async function saveProgress(completed = false) {
  if (!activeLesson) return;
  const player = document.querySelector("#player");
  try { await api(`/api/lessons/${activeLesson.id}/progress`, {method: "PUT", body: JSON.stringify({position_sec: Math.floor(player.currentTime), duration_sec: Math.floor(player.duration) || activeLesson.duration, completed})}); } catch (error) { console.warn(error); }
}

async function bootAdmin() {
  if (!(await authenticatedPage())) return;
  if (me.role === "student") { location.href = "/static/home.html"; return; }
  await loadAdmin();
}

async function loadAdmin() {
  const [overview, users, courses] = await Promise.all([api("/api/admin/overview"), api("/api/admin/users"), api("/api/admin/courses")]);
  document.querySelector("#stats").innerHTML = [["学员数量", overview.students], ["已发布课程", overview.courses], ["有效授权", overview.enrollments], ["学习时长", `${Math.round(overview.watch_minutes)} 分钟`]].map(([name, value]) => `<div class="stat"><span class="muted">${name}</span><b>${value}</b></div>`).join("");
  document.querySelector("#admin-course-list").innerHTML = courses.map((course) => `<tr><td>${course.id}</td><td>${esc(course.title)}</td><td>${course.chapter_count}</td><td>${course.lesson_count}</td><td><a class="link-button" href="/static/course-editor.html?id=${course.id}">统一编辑课程内容</a></td></tr>`).join("");
  document.querySelector("#user-list").innerHTML = users.map((user) => `<tr><td>${esc(user.name)}</td><td>${esc(user.username)}</td><td>${user.role === "student" ? "学员" : user.role === "admin" ? "管理员" : "讲师"}</td><td><span class="tag">${user.status === "active" ? "正常" : "停用"}</span></td><td>${user.role === "student" ? `<button class="link-button" data-grant="${user.id}">开通课程</button>` : ""}</td></tr>`).join("");
  document.querySelectorAll("[data-grant]").forEach((node) => node.onclick = () => grant(Number(node.dataset.grant), courses));
}

async function addChapter(courseId) { const title = prompt(`课程 ${courseId} 的章节名称：`); if (!title) return; try { const chapter = await api(`/api/admin/courses/${courseId}/chapters`, {method: "POST", body: JSON.stringify({title})}); await loadAdmin(); alert(`章节已创建，章节 ID：${chapter.id}`); } catch (error) { alert(error.message); } }
async function addLesson(courseId) { try { const course = await api(`/api/courses/${courseId}`); const choices = course.chapters.map((chapter) => `${chapter.id}：${chapter.title}`).join("\n"); if (!choices) return alert("请先创建章节"); const chapterId = prompt(`输入章节 ID：\n${choices}`); if (!chapterId) return; const title = prompt("课时名称："); const duration = prompt("视频时长（秒），例如 600：", "600"); if (!title || !duration) return; const lesson = await api(`/api/admin/chapters/${chapterId}/lessons`, {method: "POST", body: JSON.stringify({title, duration: Number(duration), is_preview: confirm("是否允许试听？")})}); await loadAdmin(); alert(`课时已创建，课时 ID：${lesson.id}`); } catch (error) { alert(error.message); } }
async function uploadVideo(courseId) { try { const course = await api(`/api/courses/${courseId}`); const choices = course.chapters.flatMap((chapter) => chapter.lessons.map((lesson) => `${lesson.id}：${lesson.title}${lesson.original_filename ? "（已上传）" : ""}`)).join("\n"); if (!choices) return alert("请先创建课时"); const lessonId = prompt(`输入课时 ID：\n${choices}`); if (!lessonId) return; const input = Object.assign(document.createElement("input"), {type: "file", accept: "video/mp4,.mp4"}); input.onchange = async () => { const file = input.files[0]; if (!file) return; if (file.size > 1024 * 1024 * 1024) return alert("视频不能超过 1 GB"); const form = new FormData(); form.append("file", file); try { const response = await fetch(`/api/admin/lessons/${lessonId}/video`, {method: "POST", headers: {Authorization: `Bearer ${token}`}, body: form}); const data = await response.json(); if (!response.ok) throw Error(data.detail || "上传失败"); await loadAdmin(); alert(`上传成功：${data.filename}`); } catch (error) { alert(error.message); } }; input.click(); } catch (error) { alert(error.message); } }
async function grant(userId, courses) { const choice = prompt(`输入课程 ID：\n${courses.map((course) => `${course.id}：${course.title}`).join("\n")}`); if (!choice) return; try { await api("/api/admin/enrollments", {method: "POST", body: JSON.stringify({user_id: userId, course_id: Number(choice)})}); alert("已开通课程"); } catch (error) { alert(error.message); } }

async function bootCourseCreate() {
  if (!(await authenticatedPage())) return;
  if (me.role === "student") { location.href = "/static/home.html"; return; }
  const form = document.querySelector("#create-course-form");
  const message = document.querySelector("#create-course-message");
  form.onsubmit = async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    const payload = Object.fromEntries(new FormData(form));
    message.textContent = "";
    button.disabled = true;
    button.textContent = "正在创建…";
    try {
      const course = await api("/api/admin/courses", {method: "POST", body: JSON.stringify(payload)});
      location.href = `/static/course-editor.html?id=${course.id}`;
    } catch (error) {
      message.textContent = error.message;
      button.disabled = false;
      button.textContent = "创建并编辑课程内容";
    }
  };
}

async function bootEditor() {
  if (!(await authenticatedPage())) return;
  if (me.role === "student") { location.href = "/static/home.html"; return; }
  const courseId = new URLSearchParams(location.search).get("id");
  if (!courseId) { location.href = "/static/admin.html"; return; }
  let selectedDuration = 0;
  const loadEditor = async () => {
    activeCourse = await api(`/api/courses/${courseId}`);
    document.querySelector("#editor-title").value = activeCourse.title;
    document.querySelector("#editor-description").value = activeCourse.description;
    document.querySelector("#editor-category").value = activeCourse.category;
    document.querySelector("#editor-chapters").innerHTML = activeCourse.chapters.length ? activeCourse.chapters.map((chapter, index) => `<div class="chapter"><b>${esc(chapterLabel(chapter, index + 1))}</b> <button class="link-button" data-edit-chapter="${chapter.id}">修改</button> <button class="link-button" data-delete-chapter="${chapter.id}">删除</button>${chapter.lessons.length ? chapter.lessons.map((lesson) => `<div class="lesson"><span>${esc(lesson.title)} ${lesson.is_preview ? "（试听）" : ""}</span><small>${lesson.duration ? `${Math.ceil(lesson.duration / 60)} 分钟` : "待上传视频"} ${lesson.original_filename ? "· 已上传" : ""}　<button class="link-button" data-edit-lesson="${lesson.id}">修改</button> <button class="link-button" data-delete-lesson="${lesson.id}">删除</button></small></div>`).join("") : '<p class="muted">暂无课时</p>'}</div>`).join("") : '<p class="muted">还没有章节，请先在右侧创建。</p>';
    document.querySelector("#chapter-select").innerHTML = activeCourse.chapters.map((chapter, index) => `<option value="${chapter.id}">${esc(chapterLabel(chapter, index + 1))}</option>`).join("");
    document.querySelectorAll("[data-edit-chapter]").forEach((node) => node.onclick = () => editChapter(Number(node.dataset.editChapter)));
    document.querySelectorAll("[data-delete-chapter]").forEach((node) => node.onclick = () => deleteChapter(Number(node.dataset.deleteChapter)));
    document.querySelectorAll("[data-edit-lesson]").forEach((node) => node.onclick = () => editLesson(Number(node.dataset.editLesson)));
    document.querySelectorAll("[data-delete-lesson]").forEach((node) => node.onclick = () => deleteLesson(Number(node.dataset.deleteLesson)));
  };
  const readDuration = (file) => new Promise((resolve, reject) => { const video = document.createElement("video"); const url = URL.createObjectURL(file); video.preload = "metadata"; video.onloadedmetadata = () => { URL.revokeObjectURL(url); resolve(Math.ceil(video.duration)); }; video.onerror = () => { URL.revokeObjectURL(url); reject(Error("无法读取视频元数据，请确认是有效 MP4")); }; video.src = url; });
  document.querySelector("#video-file").onchange = async (event) => { const file = event.target.files[0]; if (!file) return; try { selectedDuration = await readDuration(file); document.querySelector("#video-meta").textContent = `已读取实际时长：${Math.floor(selectedDuration / 60)} 分 ${selectedDuration % 60} 秒`; } catch (error) { selectedDuration = 0; document.querySelector("#video-meta").textContent = error.message; } };
  const findChapter = (id) => activeCourse.chapters.find((chapter) => chapter.id === id);
  const findLesson = (id) => activeCourse.chapters.flatMap((chapter) => chapter.lessons).find((lesson) => lesson.id === id);
  const editChapter = async (id) => { const chapter = findChapter(id); const title = prompt("章节名称（不需要填写序号）：", chapterName(chapter)); if (title === null) return; try { await api(`/api/admin/chapters/${id}`, {method: "PATCH", body: JSON.stringify({title})}); await loadEditor(); } catch (error) { alert(error.message); } };
  const deleteChapter = async (id) => { if (!confirm("删除章节会同时删除其中所有课时和视频，确认继续吗？")) return; try { await api(`/api/admin/chapters/${id}`, {method: "DELETE"}); await loadEditor(); } catch (error) { alert(error.message); } };
  const editLesson = async (id) => { const lesson = findLesson(id); const title = prompt("课时名称：", lesson.title); if (title === null) return; try { await api(`/api/admin/lessons/${id}`, {method: "PATCH", body: JSON.stringify({title, is_preview: confirm("允许未授权学员试听？")})}); await loadEditor(); } catch (error) { alert(error.message); } };
  const deleteLesson = async (id) => { if (!confirm("确认删除该课时及其上传视频吗？")) return; try { await api(`/api/admin/lessons/${id}`, {method: "DELETE"}); await loadEditor(); } catch (error) { alert(error.message); } };
  document.querySelector("#course-form").onsubmit = async (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const button = formElement.querySelector("button[type=submit]");
    const message = document.querySelector("#course-save-message");
    const payload = Object.fromEntries(new FormData(formElement));
    message.className = "form-message";
    message.textContent = "";
    button.disabled = true;
    button.textContent = "保存中…";
    try {
      await api(`/api/admin/courses/${courseId}`, {method: "PATCH", body: JSON.stringify(payload)});
      await loadEditor();
      message.textContent = "课程基本信息已保存";
    } catch (error) {
      message.className = "form-message error";
      message.textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = "保存基本信息";
    }
  };
  document.querySelector("#chapter-form").onsubmit = async (event) => { event.preventDefault(); const formElement = event.currentTarget; const title = new FormData(formElement).get("title"); try { await api(`/api/admin/courses/${courseId}/chapters`, {method: "POST", body: JSON.stringify({title})}); formElement.reset(); await loadEditor(); } catch (error) { alert(error.message); } };
  document.querySelector("#lesson-form").onsubmit = async (event) => { event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement), file = form.get("video"); if (!selectedDuration) return alert("请等待系统读取视频实际时长后再提交"); try { const lesson = await api(`/api/admin/chapters/${form.get("chapter_id")}/lessons`, {method: "POST", body: JSON.stringify({title: form.get("title"), is_preview: form.get("is_preview") === "on"})}); const upload = new FormData(); upload.append("file", file); upload.append("duration", String(selectedDuration)); const response = await fetch(`/api/admin/lessons/${lesson.id}/video`, {method: "POST", headers: {Authorization: `Bearer ${token}`}, body: upload}); const data = await response.json(); if (!response.ok) throw Error(data.detail || "视频上传失败"); selectedDuration = 0; formElement.reset(); document.querySelector("#video-meta").textContent = "上传成功，时长已按视频元数据写入。"; await loadEditor(); } catch (error) { alert(error.message); } };
  await loadEditor();
}

function bootAuth() {
  const login = document.querySelector("#login-form"), register = document.querySelector("#register-form"), message = document.querySelector("#auth-message");
  const toggle = () => { const isRegister = register.classList.toggle("hidden"); login.classList.toggle("hidden", !isRegister); document.querySelector("#auth-title").textContent = isRegister ? "猴子课堂" : "创建学习账号"; document.querySelector("#auth-subtitle").textContent = isRegister ? "稳定、安全的录播课程学习平台" : "注册后即可试听课程并保存学习进度"; document.querySelector("#auth-switch").textContent = isRegister ? "没有账号？立即注册" : "已有账号？返回登录"; document.querySelector("#demo-hint").classList.toggle("hidden", !isRegister); message.textContent = ""; };
  document.querySelector("#auth-switch").onclick = toggle;
  const submit = async (form, path) => { const body = Object.fromEntries(new FormData(form)); try { const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)}); const data = await response.json(); if (!response.ok) throw Error(data.detail); localStorage.setItem("zx_token", data.token); location.href = "/static/home.html"; } catch (error) { message.textContent = error.message; } };
  login.onsubmit = (event) => { event.preventDefault(); submit(login, "/api/auth/login"); }; register.onsubmit = (event) => { event.preventDefault(); submit(register, "/api/auth/register"); };
  if (token) location.href = "/static/home.html";
}

document.addEventListener("DOMContentLoaded", () => ({home: bootHome, mine: bootMine, course: bootCourse, admin: bootAdmin, "course-create": bootCourseCreate, editor: bootEditor}[document.body.dataset.page] || bootAuth)());
