# 5. 관리자 기능: 구글 폼 보고서 파일 링크 매핑 (학교 맞춤형 열 인식 보완)
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
        
        # 열 이름 앞뒤 공백 제거
        df.columns = [col.strip() for col in df.columns]
        
        # ⭐ 선생님의 구글 폼 열 이름 구조에 완벽하게 대응하도록 유연한 검색 적용
        try:
            student_id_col = [col for col in df.columns if '학번' in col][0]
        except IndexError:
            raise Exception("파일에서 '학번'이 포함된 열을 찾을 수 없습니다.")
            
        try:
            report_link_col = [col for col in df.columns if '업로드' in col or '파일' in col or '보고서' in col or '제출' in col or '링크' in col][0]
        except IndexError:
            raise Exception("파일에서 '업로드', '보고서', '파일' 등이 포함된 링크 열을 찾을 수 없습니다.")

        updated_count = 0
        for _, row in df.iterrows():
            if pd.isna(row[student_id_col]): 
                continue
            
            # 학번 정제 (.0 제거 및 문자열 통일)
            s_id_raw = row[student_id_col]
            if isinstance(s_id_raw, float) or isinstance(s_id_raw, int):
                s_id = str(int(s_id_raw)).strip()
            else:
                s_id = str(s_id_raw).strip().split('.')[0]

            # 구글 드라이브 링크 추출
            link = str(row[report_link_col]).strip() if pd.notna(row[report_link_col]) else ""
            
            # DB 업데이트 시행
            cursor.execute("UPDATE student_courses SET report_link = ? WHERE student_id = ?", (link, s_id))
            updated_count += cursor.rowcount
            
        conn.commit()
        return f'<html><head><meta charset="UTF-8"><script>alert("{updated_count}명의 구글 폼 보고서 링크가 완벽하게 매핑되었습니다!"); location.href="/admin";</script></head><body></body></html>'
    except Exception as e:
        return f'<html><head><meta charset="UTF-8"><script>alert("에러가 발생했습니다. 오류 내용: {e}"); location.href="/admin";</script></head><body></body></html>'
