import sqlite3
import io
import pandas as pd
from fastapi import FastAPI, Form, Request, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI()
security = HTTPBasic()

# 🔐 마스터 관리자 ID / PW
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

# [최초 1회 실행 및 빈 DB 강제 리셋 보완] 업로드된 학생 데이터 로드
def load_initial_excel_data():
    try:
        cursor.execute("SELECT COUNT(*) FROM student_courses")
        count = cursor.fetchone()[0]
        
        if count == 0:
            print("▶ [알림] 현재 데이터베이스가 비어 있습니다. students_data.csv 로드를 시도합니다...")
            # 확장자가 대문자(.CSV)든 소문자(.csv)든 유연하게 처리하기 위해 두 경로 모두 시도
            df = None
            for filename in ["students_data.csv", "students_data.CSV"]:
                for enc in ["utf-8-sig", "cp949", "utf-8", "euc-kr"]:
                    try:
                        df = pd.read_csv(filename, encoding=enc)
                        print(f"▶ [성공] {filename} 파일을 {enc} 인코딩으로 읽었습니다.")
                        break
                    except Exception:
                        continue
                if df is not None:
                    break

            if df is not None:
                df.columns = [col.strip() for col in df.columns]
                
                teacher_col = [col for col in df.columns if '교사' in col or '담당' in col][0]
                student_id_col = [col for col in df.columns if '학번' in col][0]
                student_name_col = [col for col in df.columns if '이름' in col or '성명' in col][0]
                course_col = [col for col in df.columns if '강좌' in col or '과목' in col][0]

                for _, row in df.iterrows():
                    t_name = str(row[teacher_col]).strip() if pd.notna(row[teacher_col]) else ""
                    if t_name == "" or t_name.lower() == "nan" or t_name == "none":
                        t_name = "미배정"
                    
                    # ⭐ [해결 1] 학번에 .0이 붙는 현상 방지 정제 작업
                    s_id_raw = row[student_id_col]
                    if pd.isna(s_id_raw):
                        continue
                    if isinstance(s_id_raw, float):
                        s_id = str(int(s_id_raw)).strip()
                    else:
                        s_id = str(s_id_raw).strip()
                        if s_id.endswith('.0'):
                            s_id = s_id[:-2]

                    s_name = str(row[student_name_col]).strip()
                    c_name = str(row[course_col]).strip()

                    cursor.execute("""
                        INSERT INTO student_courses (student_id, student_name, course_name, teacher_name, report_link, seuteuk_content)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (s_id, s_name, c_name, t_name, "", ""))
                conn.commit()
                print("▶ [완료] 기초 학생 데이터 DB 탑재 성공 (학번 깨짐 해결)!")
            else:
                print("▶ [경고] 서버 내에 'students_data.csv' 파일이 없거나 형식이 잘못되었습니다.")
        else:
            print(f"▶ [알림] 이미 데이터베이스에 {count}명의 데이터가 탑재되어 있습니다.")
    except Exception as e:
        print(f"▶ [초기화 에러] {e}")

load_initial_excel_data()


# 1. 메인 화면
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

# 2. 교사별 담당 학생 목록 및 세특 입력 화면 (페이지 이동 없는 AJAX 및 부드러운 알림창 적용)
@app.get("/teacher/list", response_class=HTMLResponse)
async def teacher_list(teacher_name: str):
    search_name = teacher_name.strip()
    
    cursor.execute("""
        SELECT id, student_id, student_name, course_name, report_link, seuteuk_content 
        FROM student_courses 
        WHERE teacher_name = ? OR teacher_name LIKE ?
        ORDER BY student_id ASC
    """, (search_name, f"%{search_name}%"))
    rows = cursor.fetchall()
    
    if not rows:
        return f'<html><head><meta charset="UTF-8"></head><body style="text-align:center;margin-top:100px;font-family:sans-serif;"><h3>❌ "{teacher_name}" 선생님으로 등록된 담당 학생 명단이 없습니다.</h3><p style="color:gray;">오타나 성명 앞뒤의 공백을 확인해 주세요.</p><a href="/">돌아가기</a></body></html>'
    
    table_rows = ""
    for idx, r in enumerate(rows):
        db_id, s_id, s_name, c_name, r_link, s_content = r
        link_html = f'<a href="{r_link}" target="_blank" style="color:#007bff;font-weight:bold;text-decoration:none;">📄 보고서 확인</a>' if r_link else '<span style="color:#999;font-size:12px;">미제출</span>'
        s_content = s_content if s_content else ""
        
        # ⭐ [해결 2] 폼 전송 시 온페이지 전송(AJAX) 구현을 위한 구조 전면 변경
        table_rows += f"""
        <tr>
            <td>{s_id}</td>
            <td><b>{s_name}</b></td>
            <td style="color:#555; font-size:14px;">{c_name}</td>
            <td style="text-align:center;">{link_html}</td>
            <td>
                <div style="margin:0; display:flex; flex-direction:column; gap:5px;">
                    <textarea id="txt_{idx}" rows="4" style="width:100%; padding:8px; box-sizing:border-box; border:1px solid #ccc; border-radius:4px; font-size:13px;" oninput="checkBytes(this, 'byte_{idx}')" placeholder="내용을 입력하세요">{s_content}</textarea>
                    <div style="display:flex; align-items:center;">
                        <span style="font-size:12px; color:#666;"><span id="byte_{idx}" style="font-weight:bold; color:#007bff;">0</span> / 750 바이트</span>
                        <button type="button" onclick="saveData({db_id}, 'txt_{idx}', '{teacher_name}', this)" style="margin-left:auto; padding:5px 15px; background:#28a745; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:bold;">저장</button>
                    </div>
                </div>
            </td>
        </tr>
        """
        
    return f"""
    <html><head><meta charset="UTF-8"><title>{teacher_name} 선생님 대시보드</title>
    <style>body{{font-family:sans-serif; max-width:1300px; margin:30px auto; padding:0 20px;}}
    .header{{display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; border-bottom:2px solid #007bff; padding-bottom:10px;}}
    table{{width:100%; border-collapse:collapse; margin-top:10px;}} th,td{{border:1px solid #ddd; padding:12px; text-align:left;}}
    th{{background:#f2f2f2; font-weight:bold;}} tr:nth-child(even){{background-color:#f9f9f9;}}
    /* 부드러운 알림 팝업 스타일 */
    #toast-msg {{
        visibility: hidden; min-width: 250px; background-color: #333; color: #fff; text-align: center;
        border-radius: 6px; padding: 16px; position: fixed; z-index: 9999; left: 50%; top: 50px;
        transform: translateX(-50%); font-weight: bold; box-shadow: 0 4px 10px rgba(0,0,0,0.3);
    }}
    #toast-msg.show {{ visibility: visible; -webkit-animation: fadein 0.5s, fadeout 0.5s 2.5s; animation: fadein 0.5s, fadeout 0.5s 2.5s; }}
    @-webkit-keyframes fadein {{ from {{top: 0; opacity: 0;}} to {{top: 50px; opacity: 1;}} }}
    @keyframes fadein {{ from {{top: 0; opacity: 0;}} to {{top: 50px; opacity: 1;}} }}
    @-webkit-keyframes fadeout {{ from {{top: 50px; opacity: 1;}} to {{top: 0; opacity: 0;}} }}
    @keyframes fadeout {{ from {{top: 50px; opacity: 1;}} to {{top: 0; opacity: 0;}} }}
    </style>
    <script>
        function checkBytes(obj, targetId) {{
            var str = obj.value;
            var rbyte = 0;
            for (var i = 0; i < str.length; i++) {{
                if (str.charCodeAt(i) > 127) {{ rbyte += 3; }} else {{ rbyte++; }}
            }}
            document.getElementById(targetId).innerText = rbyte;
        }}

        // ⭐ 페이지 이동 없이 화면 안에서 안전하게 세특을 저장하는 자바스크립트 함수 (AJAX)
        function saveData(dbId, textareaId, tName, btnObj) {{
            var content = document.getElementById(textareaId).value;
            btnObj.innerText = "⏳...";
            btnObj.disabled = true;

            var formData = new FormData();
            formData.append("db_id", dbId);
            formData.append("teacher_name", tName);
            formData.append("seuteuk_content", content);

            fetch("/teacher/save", {{
                method: "POST",
                body: formData
            }})
            .then(response => response.json())
            .then(data => {{
                if(data.status === "success") {{
                    showToast("✅ 저장되었습니다!");
                }} else {{
                    showToast("❌ 저장에 실패했습니다.");
                }}
                btnObj.innerText = "저장";
                btnObj.disabled = false;
            }})
            .catch(error => {{
                console.error("Error:", error);
                showToast("❌ 네트워크 오류 발생");
                btnObj.innerText = "저장";
                btnObj.disabled = false;
            }});
        }}

        function showToast(msg) {{
            var toast = document.getElementById("toast-msg");
            toast.innerText = msg;
            toast.className = "show";
            setTimeout(function() {{ toast.className = toast.className.replace("show", ""); }}, 3000);
        }}

        // 최초 글자수 바이트 세팅
        document.addEventListener("DOMContentLoaded", function() {{
            var textareas = document.querySelectorAll("textarea");
            textareas.forEach((txt, idx) => {{
                checkBytes(txt, "byte_" + idx);
            }});
        }});
    </script>
    </head>
    <body>
        <div id="toast-msg">✅ 성공적으로 저장되었습니다!</div>
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

# 3. 세특 저장 처리 (JSON 결과 반환으로 개편)
@app.post("/teacher/save")
async def save_seuteuk(db_id: int = Form(...), teacher_name: str = Form(...), seuteuk_content: str = Form(...)):
    try:
        cursor.execute("UPDATE student_courses SET seuteuk_content = ? WHERE id = ?", (seuteuk_content, db_id))
        conn.commit()
        return {"status": "success"}
    except Exception:
        return {"status": "error"}


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
        
        df = None
        for enc in ["utf-8-sig", "cp949", "utf-8", "euc-kr"]:
            try:
                df = pd.read_csv(io.BytesIO(contents), encoding=enc)
                break
            except Exception:
                continue
                
        if df is None:
            raise Exception("CSV 파일의 인코딩을 해석할 수 없습니다.")
        
        df.columns = [col.strip() for col in df.columns]
        student_id_col = [col for col in df.columns if '학번' in col][0]
        report_link_col = [col for col in df.columns if '파일' in col or '보고서' in col or '제출' in col][0]

        updated_count = 0
        for _, row in df.iterrows():
            if pd.isna(row[student_id_col]): continue
            
            s_id_raw = row[student_id_col]
            if isinstance(s_id_raw, float):
                s_id = str(int(s_id_raw)).strip()
            else:
                s_id = str(s_id_raw).strip().split('.')[0]

            link = str(row[report_link_col]).strip() if pd.notna(row[report_link_col]) else ""
            
            cursor.execute("UPDATE student_courses SET report_link = ? WHERE student_id = ?", (link, s_id))
            updated_count += cursor.rowcount
            
        conn.commit()
        return f'<html><head><meta charset="UTF-8"><script>alert("{updated_count}명의 구글 폼 보고서 링크 매핑 성공!"); location.href="/admin";</script></head><body></body></html>'
    except Exception as e:
        return f'<html><head><meta charset="UTF-8"><script>alert("에러가 발생했습니다. 오류: {e}"); location.href="/admin";</script></head><body></body></html>'


# 6. ⭐ [해결 3] 최종 엑셀 추출 기능 (오류 차단 및 안전한 버퍼 출력 전면 수정)
@app.get("/admin/download")
async def download(username: str = Depends(authenticate_admin)):
    try:
        query = "SELECT student_id, student_name, course_name, teacher_name, seuteuk_content FROM student_courses ORDER BY student_id ASC"
        cursor.execute(query)
        rows = cursor.fetchall()
        
        # 순수 내장 데이터 형태로 DataFrame 재구축하여 라이브러리 엔진 충돌 완전 방지
        data_list = []
        for r in rows:
            data_list.append({
                "학번": r[0],
                "이름": r[1],
                "강좌명": r[2],
                "세특담당교사": r[3],
                "입력된 세특": r[4] if r[4] else ""
            })
        
        df = pd.DataFrame(data_list)
        
        output = io.BytesIO()
        # 호환성 확보를 위한 복수 시트 방지 옵션 제거 및 단순화
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        
        output.seek(0)
        excel_data = output.read()
        
        return StreamingResponse(
            io.BytesIO(excel_data), 
            headers={'Content-Disposition': 'attachment; filename="seuteuk_total_2026.xlsx"'}, 
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"엑셀 파일 생성 실패 원인: {e}")
