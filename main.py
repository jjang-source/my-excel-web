import os, sqlite3, io
from fastapi import FastAPI, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import pandas as pd

app = FastAPI()
security = HTTPBasic()

# 🔐 [중요] 관리자 아이디와 비밀번호 설정 (원하는 대로 바꾸세요)
ADMIN_USERNAME = "cheongwon"
ADMIN_PASSWORD = "cheongwon"

# 관리자 인증용 함수
def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != ADMIN_USERNAME or credentials.password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 틀렸습니다.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# templates 폴더 및 HTML 자동 생성
os.makedirs("templates", exist_ok=True)
def create_template(filename, content):
    with open(f"templates/{filename}", "w", encoding="utf-8") as f: f.write(content)

create_template("index.html", '<html><head><meta charset="UTF-8"><title>데이터 입력</title><style>body{font-family:sans-serif;max-width:400px;margin:50px auto;padding:20px;border:1px solid #ccc;border-radius:8px;}input,textarea{width:100%;padding:10px;margin:10px 0;box-sizing:border-box;}button{width:100%;padding:12px;background:#28a745;color:white;border:none;border-radius:4px;cursor:pointer;}</style></head><body><h2>📋 개인정보 및 데이터 입력</h2><p style="color:gray; font-size:12px;">* 제출된 정보는 암호화되어 안전하게 보관됩니다.</p><form action="/submit" method="post"><label>이름/ID:</label><input type="text" name="username" required><label>입력 내용 (개인정보 포함):</label><textarea name="content" rows="5" required></textarea><button type="submit">안전하게 제출하기</button></form></body></html>')
create_template("success.html", '<html><head><meta charset="UTF-8"></head><body style="text-align:center;margin-top:100px;font-family:sans-serif;"><h1>✅ 제출 성공!</h1><p>데이터가 안전하게 수집되었습니다.</p></body></html>')
create_template("admin.html", '<html><head><meta charset="UTF-8"><title>관리자 대시보드</title><style>body{font-family:sans-serif;max-width:600px;margin:40px auto;}div{display:flex;justify-content:space-between;align-items:center;}table{width:100%;border-collapse:collapse;}th,td{border:1px solid #ddd;padding:10px;}</style></head><body><div><h2>🛠️ 관리자 전용 페이지</h2><a href="/admin/download" style="padding:10px;background:#218838;color:white;text-decoration:none;border-radius:4px;">📊 엑셀 다운로드</a></div><table><thead><tr><th>사용자</th><th>내용</th></tr></thead><tbody>{% for item in inputs %}<tr><td>{{ item.username }}</td><td>{{ item.content }}</td></tr>{% endfor %}</tbody></table></body></html>')

templates = Jinja2Templates(directory="templates")
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS user_inputs (username TEXT, content TEXT)")
conn.commit()

@app.get("/", response_class=HTMLResponse)
async def index(request: Request): 
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/submit")
async def submit(request: Request, username: str = Form(...), content: str = Form(...)):
    cursor.execute("INSERT INTO user_inputs (username, content) VALUES (?, ?)", (username, content))
    conn.commit()
    return templates.TemplateResponse("success.html", {"request": request})

# 🔒 관리자 페이지 접근 시 로그인창이 뜨도록 보호
@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request, username: str = Depends(authenticate_admin)):
    cursor.execute("SELECT username, content FROM user_inputs")
    inputs = [{"username": r[0], "content": r[1]} for r in cursor.fetchall()]
    return templates.TemplateResponse("admin.html", {"request": request, "inputs": inputs})

# 🔒 엑셀 다운로드 링크도 로그인 없이는 다운로드 불가능하게 보호
@app.get("/admin/download")
async def download(username: str = Depends(authenticate_admin)):
    df = pd.read_sql_query("SELECT username AS [사용자], content AS [내용] FROM user_inputs", conn)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: 
        df.to_excel(writer, index=False)
    output.seek(0)
    return StreamingResponse(output, headers={'Content-Disposition': 'attachment; filename="secure_data.xlsx"'}, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')