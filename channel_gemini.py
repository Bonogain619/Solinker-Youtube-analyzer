import streamlit as st
from googleapiclient.discovery import build
import pandas as pd
import plotly.express as px
import isodate
import requests
import json
from datetime import datetime
import io 
from docx import Document 
from docx.oxml.ns import qn 
from docx.shared import Pt # 폰트 크기 조절용

# ==============================================================================
# [필승 설정] check.py에서 성공했던 그 'Gemini 키'를 따옴표 안에 붙여넣으세요!
# ==============================================================================
GEMINI_API_KEY = "AIzaSyASndV5RssUI9Uj3Shuwm8BdhnFP5F7vx4"
# ==============================================================================

st.set_page_config(page_title="Solinker Channel Analyzer", page_icon="⚡", layout="wide")

# [스타일] UI 최적화
st.markdown("""
<style>
    .report-box {
        border: 2px solid #e0e0e0;
        padding: 30px;
        border-radius: 15px;
        background-color: #f9f9f9;
        color: #333333;
        font-size: 1.2rem !important; 
        line-height: 1.8 !important;
        margin-bottom: 30px;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 1.1rem;
        font-weight: 600;
    }
    .big-text {
        font-size: 1.5rem !important;
        font-weight: bold;
        margin-bottom: 10px;
        color: #1E1E1E;
    }
</style>
""", unsafe_allow_html=True)

# 1. 초기화
if "run_pro" not in st.session_state: st.session_state.run_pro = False
if "messages" not in st.session_state: st.session_state.messages = []
if "data" not in st.session_state: st.session_state.data = None

# 2. 사이드바 UI
with st.sidebar:
    st.header("🔧 설정 패널")
    
    if GEMINI_API_KEY.startswith("AIza"):
        st.success(f"✅ AI 엔진 준비 완료")
    else:
        st.error("🚨 코드 12번째 줄에 Gemini 키를 넣어주세요!")

    with st.expander("🔑 유튜브 키 입력", expanded=True):
        yt_key = st.text_input("YouTube API Key", type="password")
    
    st.divider()
    handle_input = st.text_input("채널 핸들 (@포함)", placeholder="@핸들명")
    
    if st.button("⚡ 심층 분석 시작", type="primary"):
        st.session_state.run_pro = True
        st.session_state.messages = [] 
        st.session_state.data = None

# 3. 유틸리티 함수들
def get_youtube(api_key): return build("youtube", "v3", developerKey=api_key)

def check_is_shorts(video_id):
    try: return requests.head(f"https://www.youtube.com/shorts/{video_id}", allow_redirects=False, timeout=2).status_code == 200
    except: return False

def format_duration(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0: return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def get_channel_stats(yt, handle):
    try:
        res = yt.search().list(part="id,snippet", q=handle, type="channel", maxResults=1).execute()
        if not res["items"]: return None
        ch_id = res["items"][0]["id"]["channelId"]
        item = yt.channels().list(part="statistics,contentDetails,snippet", id=ch_id).execute()["items"][0]
        return {
            "title": item["snippet"]["title"],
            "thumbnail": item["snippet"]["thumbnails"]["high"]["url"],
            "subs": int(item["statistics"]["subscriberCount"]),
            "views": int(item["statistics"]["viewCount"]),
            "video_count": int(item["statistics"]["videoCount"]),
            "upload_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
            "desc": item["snippet"]["description"]
        }
    except Exception as e: st.error(f"채널 검색 실패: {e}"); return None

def get_recent_videos(yt, upload_id):
    try:
        res = yt.playlistItems().list(part="snippet,contentDetails", playlistId=upload_id, maxResults=50).execute()
        vid_ids = [i["contentDetails"]["videoId"] for i in res["items"]]
        vid_res = yt.videos().list(part="statistics,contentDetails,snippet", id=",".join(vid_ids)).execute()
        videos = []
        status_text = st.empty()
        total = len(vid_res["items"])
        for i, item in enumerate(vid_res["items"]):
            stats = item["statistics"]
            dur = isodate.parse_duration(item["contentDetails"]["duration"]).total_seconds()
            is_s = False
            if dur <= 180:
                status_text.caption(f"🔍 영상 분석 중 ({i+1}/{total})...")
                if check_is_shorts(item['id']): is_s = True
            videos.append({
                "제목": item["snippet"]["title"],
                "조회수": int(stats.get("viewCount", 0)),
                "좋아요": int(stats.get("likeCount", 0)),
                "댓글": int(stats.get("commentCount", 0)),
                "길이": format_duration(dur),
                "날짜": item["snippet"]["publishedAt"][:10],
                "유형": "Shorts" if is_s else "Long-form"
            })
        status_text.empty()
        return pd.DataFrame(videos)
    except: return pd.DataFrame()

# [핵심] 워드 생성기 (표 인식 기능 추가됨)
def create_docx(text, title="문서"):
    doc = Document()
    
    # 1. 문서 기본 폰트 설정 (한글 깨짐 방지)
    style = doc.styles['Normal']
    style.font.name = 'Malgun Gothic'
    style.element.rPr.rFonts.set(qn('w:eastAsia'), 'Malgun Gothic')
    
    doc.add_heading(title, 0)
    
    # 줄 단위로 처리하되, 표(Table)를 만나면 모아서 한 번에 처리
    lines = text.split('\n')
    table_buffer = [] # 표 내용을 임시 저장할 공간
    
    for line in lines:
        line = line.strip()
        
        # (1) 표가 시작되거나 이어지는 경우 (|로 시작)
        if line.startswith('|'):
            table_buffer.append(line)
        else:
            # (2) 표가 끝났는데 버퍼에 내용이 있다면 -> 표 생성!
            if table_buffer:
                _add_table_to_doc(doc, table_buffer)
                table_buffer = [] # 버퍼 초기화
            
            # (3) 일반 텍스트 처리
            if not line: continue
            
            if line.startswith('### '): doc.add_heading(line.replace('### ', ''), level=3)
            elif line.startswith('## '): doc.add_heading(line.replace('## ', ''), level=2)
            elif line.startswith('# '): doc.add_heading(line.replace('# ', ''), level=1)
            elif line.startswith('- ') or line.startswith('* '): doc.add_paragraph(line, style='List Bullet')
            else: doc.add_paragraph(line)
            
    # 반복문이 끝났는데 마지막에 표가 남아있을 경우 처리
    if table_buffer:
        _add_table_to_doc(doc, table_buffer)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# 내부 함수: 마크다운 표를 워드 표로 변환
def _add_table_to_doc(doc, markdown_lines):
    # 데이터 파싱
    rows = []
    for line in markdown_lines:
        # | 구분자로 자르고 앞뒤 공백 제거
        cells = [c.strip() for c in line.strip('|').split('|')]
        rows.append(cells)
    
    # 구분선(---|---) 제거: 보통 두 번째 줄에 있음
    real_rows = [r for r in rows if not set(''.join(r)).issubset(set('-:| '))]
    
    if not real_rows: return

    # 표 생성
    num_cols = len(real_rows[0])
    table = doc.add_table(rows=len(real_rows), cols=num_cols)
    table.style = 'Table Grid' # 격자 무늬 스타일 적용
    
    # 데이터 채우기 & 폰트 설정
    for i, row_data in enumerate(real_rows):
        row = table.rows[i]
        for j, text in enumerate(row_data):
            if j < len(row.cells):
                cell = row.cells[j]
                cell.text = text
                # 표 안의 글씨도 '맑은 고딕' 강제 적용
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.name = 'Malgun Gothic'
                        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'Malgun Gothic')

# 4. AI 연결
def call_gemini_rest(prompt):
    models = ["gemini-flash-latest", "gemini-1.5-flash", "gemini-pro"]
    for model in models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            resp = requests.post(url, headers={'Content-Type': 'application/json'}, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            if resp.status_code == 200: return resp.json()['candidates'][0]['content']['parts'][0]['text']
        except: continue
    return "❌ AI 연결 실패"

def generate_pro_insight(channel, df):
    prompt = f"""
    당신은 최신 트렌드를 반영하는 유튜브 컨설턴트입니다. (기준일: {datetime.now().strftime('%Y-%m-%d')})
    
    [정책 가이드]
    - 쇼츠는 최대 3분까지 가능합니다. 60초 제한이라고 단정 짓지 마세요.
    
    [채널 정보]
    - 채널명: {channel['title']}
    - 구독자: {channel['subs']}명
    
    [데이터]
    {df[['유형', '제목', '조회수', '좋아요', '댓글', '길이', '날짜']].to_string(index=False)}
    
    위 데이터를 바탕으로 다음 내용을 마크다운으로 작성하세요:
    1. 📊 팩트 체크 (조회수 및 충성도 분석) - **반드시 표(Table)를 사용하여 데이터를 비교하세요.**
    2. 🚨 냉정한 비판 (성장 정체 원인)
    3. 🚀 솔루션 3가지 (구체적 실행 방안)
    """
    return call_gemini_rest(prompt)

def ask_gemini_chat(question, context_report):
    prompt = f"당신은 유튜브 컨설턴트입니다.\n[리포트]\n{context_report}\n[질문]\n{question}\n답변해주세요."
    return call_gemini_rest(prompt)

# 5. 메인 실행
if st.session_state.run_pro and yt_key:
    yt = get_youtube(yt_key)
    stats = get_channel_stats(yt, handle_input)
    if stats:
        with st.spinner("데이터 분석 중..."):
            df = get_recent_videos(yt, stats["upload_id"])
            if not df.empty:
                report = generate_pro_insight(stats, df)
                st.session_state.data = (stats, df, report)
                st.session_state.run_pro = False 
                st.rerun()

# 6. 화면 출력
if st.session_state.data is not None:
    stats, df, report = st.session_state.data
    
    c1, c2 = st.columns([1, 6])
    with c1: st.image(stats["thumbnail"], width=100)
    with c2: st.title(stats["title"])
    st.divider()
    
    t1, t2 = st.tabs(["📄 AI 심층 리포트 & 채팅", "📈 데이터 상세"])
    
    with t1: 
        st.markdown(f'<div class="report-box">{report}</div>', unsafe_allow_html=True)
        st.divider()
        st.subheader("💬 AI 컨설턴트에게 질문하기")
        
        for msg in st.session_state.messages:
            with st.chat_message("user" if msg['role']=="user" else "assistant"):
                st.markdown(msg['content'])

        if prompt := st.chat_input("질문을 입력하세요..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("생각 중..."):
                    ans = ask_gemini_chat(prompt, report)
                    st.markdown(ans)
                    st.session_state.messages.append({"role": "assistant", "content": ans})
        
    with t2:
        st.markdown('<p class="big-text">📊 상세 데이터 테이블</p>', unsafe_allow_html=True)
        st.dataframe(
            df[['날짜', '유형', '제목', '길이', '조회수', '좋아요', '댓글']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "조회수": st.column_config.NumberColumn(format="%d"),
                "좋아요": st.column_config.NumberColumn(format="%d"),
                "댓글": st.column_config.NumberColumn(format="%d")
            }
        )
        st.markdown('<p class="big-text">🔴 Shorts vs 🔵 Long-form 성과 비교</p>', unsafe_allow_html=True)
        fig = px.scatter(
            df, x="날짜", y="조회수", size="좋아요", color="유형",
            color_discrete_map={"Shorts": "#FF4B4B", "Long-form": "#1C83E1"},
            hover_data=["제목", "길이"], title="영상 성과 & 충성도 분포"
        )
        st.plotly_chart(fig, use_container_width=True)

    with st.sidebar:
        st.divider()
        st.header("📂 결과 저장소")
        file_prefix = f"Solinker_{stats['title']}_{datetime.now().strftime('%Y%m%d')}"
        
        docx_buffer = create_docx(report, title=f"{stats['title']} 채널 분석 리포트")
        st.download_button("📄 리포트 다운로드 (.docx)", docx_buffer, f"{file_prefix}_Report.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Sheet1')
        st.download_button("📊 데이터 다운로드 (.xlsx)", buffer, f"{file_prefix}_Data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        if st.session_state.messages:
            chat_full_text = ""
            for msg in st.session_state.messages:
                role = "👤 질문" if msg['role'] == "user" else "🤖 답변"
                chat_full_text += f"## {role}\n{msg['content']}\n\n"
            chat_docx = create_docx(chat_full_text, title=f"{stats['title']} AI 상담 기록")
            st.download_button("💬 상담 기록 다운로드 (.docx)", chat_docx, f"{file_prefix}_Chat.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

else:
    st.title("🎥 Solinker Channel Analyzer")
    st.markdown("왼쪽 사이드바에 **유튜브 키**와 **핸들**을 입력하고 **[심층 분석 시작]**을 눌러주세요.")