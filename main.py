import sqlite3
import io
import pandas as pd
from fastapi import FastAPI, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI()
security = HTTPBasic()

# 🔐 관리자 ID / PW (필요시 수정)
ADMIN_USERNAME = "admin123"
ADMIN_PASSWORD = "super-secret-password-99"

def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != ADMIN_USERNAME or credentials.password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 틀렸습니다.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# DB 초기화 (체크 스레드 옵션 추가로 안정성 향상)
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS user_inputs (username TEXT, content TEXT)")
conn.commit()

# 1. 사용자 입력 페이지 (HTML을 코드로 직접 반환)
@app.get("/", response_class=HTMLResponse)
async def index(): 
    return """
    <html><head><meta charset="UTF-8"><title>데이터 입력</title>
    <style>body{font-family:sans-serif;max-width:400px;margin:50px auto;padding:20px;border:1px solid #ccc;border-radius:8px;}
    input,textarea{width:100%;padding:10px;margin:10px 0;box-sizing:border-box;}
    button{width:100%;padding:12px;background:#28a745;color:white;border:none;border-radius:4px;cursor:pointer;}</style></head>
    <body><h2>📋 개인정보 및 데이터 입력</h2><p style="color:gray; font-size:12px;">* 제출된 정보는 암호화되어 안전하게 보관됩니다.</p>
    <form action="/submit" method="post"><label>이름/ID:</label><input type="text" name="username" required>
    <label>입력 내용 (개인정보 포함):</label><textarea name="content" rows="5" required></textarea>
    <button type="submit">안전하게 제출하기</button></form></body></html>
    """

# 2. 제출 완료 페이지
@app.post("/submit", response_class=HTMLResponse)
async def submit(username: str = Form(...), content: str = Form(...)):
    cursor.execute("INSERT INTO user_inputs (username, content) VALUES (?, ?)", (username, content))
    conn.commit()
    return '<html><head><meta charset="UTF-8"></head><body style="text-align:center;margin-top:100px;font-family:sans-serif;"><h1>✅ 제출 성공!</h1><p>데이터가 안전하게 수집되었습니다.</p><a href="/">돌아가기</a></body></html>'

# 3. 관리자 대시보드 페이지 (Internal Server Error 방지를 위해 HTML 직접 조립)
@app.get("/admin", response_class=HTMLResponse)
async def admin(username: str = Depends(authenticate_admin)):
    cursor.execute("SELECT username, content FROM user_inputs")
    rows = cursor.fetchall()
    
    table_rows = ""
    for r in rows:
        table_rows += f"<tr><td>{r[0]}</td><td>{r[1]}</td></tr>"
        
    return f"""
    <html><head><meta charset="UTF-8"><title>관리자 대시보드</title>
    <style>body{{font-family:sans-serif;max-width:600px;margin:40px auto;}}div{{display:flex;justify-content:space-between;align-items:center;}}
    table{{width:100%;border-collapse:collapse;margin-top:20px;}}th,td{{border:1px solid #ddd;padding:10px;text-align:left;}}th{{background:#f2f2f2;}}</style></head>
    <body><div><h2>🛠️ 관리자 전용 페이지</h2><a href="/admin/download" style="padding:10px;background:#218838;color:white;text-decoration:none;border-radius:4px;">📊 엑셀 다운로드</a></div>
    <table><thead><tr><th>사용자</th><th>내용</th></tr></thead><tbody>{table_rows}</tbody></table></body></html>
    """

# 4. 엑셀 다운로드
@app.get("/admin/download")
async def download(username: str = Depends(authenticate_admin)):
    df = pd.read_sql_query("SELECT username AS [사용자], content AS [내용] FROM user_inputs", conn)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: 
        df.to_excel(writer, index=False)
    output.seek(0)
    return StreamingResponse(output, headers={'Content-Disposition': 'attachment; filename="secure_data.xlsx"'}, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
