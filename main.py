import sqlite3
import io
import pandas as pd
from fastapi import FastAPI, Form, Request, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI()
security = HTTPBasic()

# 🔐 마스터 관리자 ID / PW (원하는 대로 변경 가능)
ADMIN_USERNAME = "cheongwon"
ADMIN_PASSWORD = "cheongwon"

def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != ADMIN_USERNAME or credentials.password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 틀렸습니다.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# 데이터베이스 연결 및 테이블 생성
conn = sqlite3.connect("school_seuteuk.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS student_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT,       -- 학번
    student_name TEXT,     -- 이름
    course_name TEXT,      -- 강좌
    teacher_name TEXT,     -- 세특담당교사
    report_link TEXT,      -- 구글 폼 보고서 링크
    seuteuk_content TEXT   -- 입력된 세특 내용
)
""")
conn.commit()

# [최초 1회 실행] 첨부해주신 엑셀(CSV) 기반 데이터 자동 탑재
def load_initial_excel_data():
    cursor.execute("SELECT COUNT(*) FROM student_courses")
    if cursor.fetchone()[0] == 0:
        try:
            # 💡 주의: 업로드할 파일명이 정확히 'students_data.csv' 여야 합니다.
            df = pd.read_csv("students_data.csv", encoding="utf-8")
            for _, row in df.iterrows():
                # 빈 교사 이름 예외 처리 (공백 제거)
                t_name = str(row['세특담당교사']).strip() if pd.notna(row['세특담당교사']) else ""
                if t_name == "" or t_name == "nan":
                    continue  # 담당 교사가 지정되지 않은 행은 우선 제외하거나 빈 문자열 처리
                
                cursor.execute("""
                    INSERT INTO student_courses (student_id, student_name, course_name, teacher_name, report_link, seuteuk_content)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (str(row['학번']), row['이름'], row['강좌'], t_name, "", ""))
            conn.commit()
            print("▶ [성공] 기초 학생 데이터 탑재 완료!")
        except Exception as e:
            print(f"▶ [알림] 초기 파일(students_data.csv) 로드 대기 중... 오류: {e}")

load_initial_excel_data()


# 1. 메인 화면: 세특 담당교사 로그인창
@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <html><head><meta charset="UTF-8"><title>2026 자율적 교육과정 세특 입력</title>
    <style>body{font-family:sans-serif;max-width:450px;margin:100px auto;padding:30px;border:1px solid #ddd;border-radius:10px;box-shadow:0 4px 6px rgba(0,0,0,0.1);}
    input{width:100%;padding:12px;margin:15px 0;box-sizing:border-box;border:1px solid #ccc;border-radius:4px;font-size:16px;}
    button{width:100%;padding:12px;background:#007bff;color:white;border:none;border-radius:4px;font-size:16px;cursor:pointer;font-weight:bold;}
    button:hover{background:#0056b3;}</style></head>
    <body><h2>👨‍🏫 세특 담당교사 로그인</h2>
    <p style="color:gray; font-size:13px;">배정되신 <b>세특담당교사 성명</b>을 입력하시면 담당 학생 및 강좌 목록이 나타납니다.</p>
    <form action="/teacher/list" method="get">
        <label><b>교사 성명 입력:</b></label>
        <input type="text" name="teacher_name" placeholder="예: 안경남" required>
        <button type="submit">담당 강좌/학생 조회</button>
    </form></body></html>
    """

# 2. 교사별 담당 학생 목록 및 세특 입력 화면 (실시간 글자수 확인 가능)
@app.get("/teacher/list", response_class=HTMLResponse)
async def teacher_list(teacher_name: str):
    cursor.execute("""
        SELECT id, student_id, student_name, course_name, report_link, seuteuk_content 
        FROM student_courses 
        WHERE teacher_name = ?
        ORDER BY student_id ASC
    """, (teacher_name.strip(),))
    rows = cursor.fetchall()
    
    if not rows:
        return f'<html><head><meta charset="UTF-8"></head><body style="text-align:center;margin-top:100px;font-family:sans-serif;"><h3>❌ "{teacher_name}" 선생님으로 등록된 담당 학생 명단이 없습니다.</h3><p style="color:gray;">오타나 공백이 없는지 확인해 주세요.</p><a href="/">돌아가기</a></body></html>'
    
    table_rows = ""
    for idx, r in enumerate(rows):
        db_id, s_id, s_name, c_name, r_link, s_content = r
        link_html = f'<a href="{r_link}" target="_blank" style="color:#007bff;font-weight:bold;text-decoration:none;">📄 보고서 확인</a>' if r_link else '<span style="color:#999;font-size:12px;">미제출</span>'
        s_content = s_content if s_content else ""
        
        table_rows += f"""
        <tr>
            <td>{s_id}</td>
            <td><b>{s_name}</b></td>
            <td style="color:#555; font-size:14px;">{c_name}</td>
            <td style="text-align:center;">{link_html}</td>
            <td>
                <form action="/teacher/save" method="post" style="margin:0; display:flex; flex-direction:column; gap:5px;">
                    <input type="hidden" name="db_id" value="{db_id}">
                    <input type="hidden" name="teacher_name" value="{teacher_name}">
                    <textarea id="txt_{idx}" name="seuteuk_content" rows="4" style="width:100%; padding:8px; box-sizing:border-box; border:1px solid #ccc; border-radius:4px; font-size:13px;" oninput="checkBytes(this, 'byte_{idx}')" placeholder="내용을 입력하세요 (개학 전까지 750바이트 권장)">{s_content}</textarea>
                    <div style="display:flex; justify-content:between; align-items:center;">
                        <span style="font-size:12px; color:#666;"><span id="byte_{idx}" style="font-weight:bold; color:#007bff;">0</span> / 750 바이트</span>
                        <button type="submit" style="margin-left:auto; padding:4px 12px; background:#28a745; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:bold;">저장</button>
                    </div>
                </form>
                <script>
                    // 초기 글자수 계산 실행
                    document.addEventListener("DOMContentLoaded", function() {{
                        checkBytes(document.getElementById("txt_{idx}"), "byte_{idx}");
                    }});
                </script>
            </td>
        </tr>
        """
        
    return f"""
    <html><head><meta charset="UTF-8"><title>{teacher_name} 선생님 대시보드</title>
    <style>body{{font-family:sans-serif; max-width:1300px; margin:30px auto; padding:0 20px;}}
    .header{{display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; border-bottom:2px solid #007bff; padding-bottom:10px;}}
    table{{width:100%; border-collapse:collapse; margin-top:10px;}} th,td{{border:1px solid #ddd; padding:12px; text-align:left;}}
    th{{background:#f2f2f2; font-weight:bold;}} tr:nth-child(even){{background-color:#f9f9f9;}}</style>
    <script>
        // 한글 3바이트, 영문/숫자/공백 1바이트 계산기 함수
        function checkBytes(obj, targetId) {{
            var str = obj.value;
            var str_len = str.length;
            var rbyte = 0;
            for (var i = 0; i < str_len; i++) {{
                var code = str.charCodeAt(i);
                if (code > 127) {{ rbyte += 3; }} else {{ rbyte++; }}
            }
            document.getElementById(targetId).innerText = rbyte;
        }}
    </script>
    </head>
    <body>
        <div class="header">
            <h2>👨‍🏫 {teacher_name} 선생님 담당 세특 입력 ({len(rows)}명 배정)</h2>
            <a href="/" style="text-decoration:none; color:#666; font-weight:bold;">◀ 로그아웃</a>
        </div>
        <table>
            <thead>
                <tr>
                    <th style="width:8%;">학번</th>
                    <th style="width:10%;">이름</th>
                    <th style="width:25%;">수강 강좌명</th>
                    <th style="width:12%; text-align:center;">첨부 탐구보고서</th>
                    <th style="width:45%;">세부능력 및 특기사항 입력 (글자수 실시간 계산)</th>
                </tr>
            </thead>
            <tbody>{table_rows}</tbody>
        </table>
    </body></html>
    """

# 3. 세특 저장 처리
@app.post("/teacher/save")
async def save_seuteuk(db_id: int = Form(...), teacher_name: str = Form(...), seuteuk_content: str = Form(...)):
    cursor.execute("UPDATE student_courses SET seuteuk_content = ? WHERE id = ?", (seuteuk_content, db_id))
    conn.commit()
    return f'<html><head><meta charset="UTF-8"><script>alert("성공적으로 저장되었습니다."); location.href="/teacher/list?teacher_name={teacher_name}";</script></head><body></body></html>'


# 4. [관리자 화면] 전체 진행 현황 및 구글폼 링크 동기화창
@app.get("/admin", response_class=HTMLResponse)
async def admin_page(username: str = Depends(authenticate_admin)):
    cursor.execute("SELECT student_id, student_name, course_name, teacher_name, report_link, seuteuk_content FROM student_courses ORDER BY student_id ASC")
    rows = cursor.fetchall()
    
    table_rows = ""
    for r in rows:
        has_report = "O" if r[4] else "X"
        has_seuteuk = "완료" if r[5] else "미입력"
        table_rows += f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td style='text-align:center;'>{has_report}</td><td>{has_seuteuk}</td></tr>"
        
    return f"""
    <html><head><meta charset="UTF-8"><title>마스터 관리자 대시보드</title>
    <style>body{{font-family:sans-serif;max-width:1000px;margin:40px auto; padding:20px;}} .hd{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;}}
    .box{{background:#f8f9fa; padding:20px; border:1px solid #ddd; border-radius:6px; margin-bottom:30px;}}
    table{{width:100%;border-collapse:collapse;margin-top:20px;}}th,td{{border:1px solid #ddd;padding:10px;}}th{{background:#f2f2f2;}}</style></head>
    <body>
        <div class="hd">
            <h2>🛠️ 2026 학년도 마스터 관리자 시스템</h2>
            <a href="/admin/download" style="padding:12px 20px;background:#218838;color:white;text-decoration:none;border-radius:4px;font-weight:bold;">📊 최종 종합본 엑셀 다운로드</a>
        </div>

        <div class="box">
            <h4>📥 구글 폼 보고서 링크 일괄 반영 (CSV 파일 업로드)</h4>
            <p style="font-size:13px; color:#666;">구글 폼 결과 스프레드시트에서 [학번] 정보와 [구글 드라이브 파일 링크]가 포함된 CSV를 선택해 업로드하면 선생님 화면에 자동 연동됩니다.</p>
            <form action="/admin/upload-reports" method="post" enctype="multipart/form-data">
                <input type="file" name="file" accept=".csv" required>
                <button type="submit" style="padding:6px 12px; background:#007bff; color:white; border:none; border-radius:4px; cursor:pointer;">링크 일괄 업데이트</button>
            </form>
        </div>

        <h3>📋 현재 전체 학생 배정 및 입력 진행 현황 ({len(rows)}건)</h3>
        <table>
            <thead>
                <tr>
                    <th>학번</th>
                    <th>이름</th>
                    <th>수강 강좌명</th>
                    <th>세특담당교사</th>
                    <th>보고서연동</th>
                    <th>세특입력여부</th>
                </tr>
            </thead>
            <tbody>{table_rows}</tbody>
        </table>
    </body></html>
    """

# 5. 관리자 기능: 구글 폼 보고서 파일 링크 매핑
@app.post("/admin/upload-reports")
async def upload_reports(file: UploadFile = File(...), username: str = Depends(authenticate_admin)):
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents), encoding='utf-8')
        
        student_id_col = [col for col in df.columns if '학번' in col][0]
        report_link_col = [col for col in df.columns if '파일' in col or '보고서' in col or '제출' in col][0]

        updated_count = 0
        for _, row in df.iterrows():
            if pd.isna(row[student_id_col]): continue
            s_id = str(int(row[student_id_col])).strip()
            link = str(row[report_link_col]).strip() if pd.notna(row[report_link_col]) else ""
            
            cursor.execute("UPDATE student_courses SET report_link = ? WHERE student_id = ?", (link, s_id))
            updated_count += cursor.rowcount
            
        conn.commit()
        return f'<html><head><meta charset="UTF-8"><script>alert("{updated_count}명의 구글 폼 보고서 링크 매핑 성공!"); location.href="/admin";</script></head><body></body></html>'
    except Exception as e:
        return f'<html><head><meta charset="UTF-8"><script>alert("에러가 발생했습니다. 구글폼 CSV에 학번, 보고서 관련 컬럼이 있는지 확인해 주세요. 오류: {e}"); location.href="/admin";</script></head><body></body></html>'


# 6. 최종 엑셀 추출 기능 (학번, 이름, 강좌명, 세특담당교사, 입력된 세특)
@app.get("/admin/download")
async def download(username: str = Depends(authenticate_admin)):
    query = """
        SELECT 
            student_id AS [학번], 
            student_name AS [이름], 
            course_name AS [강좌명], 
            teacher_name AS [세특담당교사], 
            seuteuk_content AS [입력된 세특] 
        FROM student_courses
        ORDER BY student_id ASC
    """
    df = pd.read_sql_query(query, conn)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: 
        df.to_excel(writer, index=False, sheet_name='자율과정_세특종합본')
    output.seek(0)
    
    return StreamingResponse(
        output, 
        headers={'Content-Disposition': 'attachment; filename="2026_자율적교육과정_세특_최종종합.xlsx"'}, 
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
