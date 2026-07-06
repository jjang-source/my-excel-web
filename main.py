# 5. 관리자 기능: 구글 폼 보고서 파일 링크 매핑 (인코딩 에러 완벽 방어형)
@app.post("/admin/upload-reports")
async def upload_reports(file: UploadFile = File(...), username: str = Depends(authenticate_admin)):
    try:
        contents = await file.read()
        
        df = None
        # 전 세계 모든 인코딩을 유연하게 다 시도하고, 최악의 경우 글자가 일부 깨지더라도 무조건 강제로 읽어오도록 개선
        encodings_to_try = ["utf-8-sig", "cp949", "utf-8", "euc-kr", "utf-16", "cp950", "latin1"]
        for enc in encodings_to_try:
            try:
                # errors='ignore' 또는 'replace'를 주어 인코딩 해석 실패 오류를 원천 차단
                df = pd.read_csv(io.BytesIO(contents), encoding=enc, errors='replace')
                print(f"▶ [성공] 구글폼 CSV 파일을 {enc} 인코딩으로 해석했습니다.")
                break
            except Exception:
                continue
                
        if df is None:
            # 최종 방어선: 바이트를 직접 문자열로 바꾸며 강제 파싱 시도
            try:
                decoded_text = contents.decode('utf-8', errors='replace')
                df = pd.read_csv(io.StringIO(decoded_text))
            except Exception as e:
                raise Exception(f"인코딩 강제 변환 실패: {e}")
        
        # 열 이름 앞뒤 공백 제거 및 줄바꿈 정리
        df.columns = [str(col).strip().replace('\n', ' ') for col in df.columns]
        
        # 선생님의 구글 폼 열 이름 구조 검색
        try:
            student_id_col = [col for col in df.columns if '학번' in col][0]
        except IndexError:
            raise Exception("파일에서 '학번'이 포함된 열을 찾을 수 없습니다.")
            
        try:
            report_link_col = [col for col in df.columns if '업로드' in col or '파일' in col or '보고서' in col or '제출' in col or '링크' in col][0]
        except IndexError:
            raise Exception("파일에서 '업로드', '보고서' 등이 포함된 링크 열을 찾을 수 없습니다.")

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
        return f'<html><head><meta charset="UTF-8"><script>alert("에러가 발생했습니다. 오류 내용: {e}"); location.href="/admin";</script></head><body></body></html>'
