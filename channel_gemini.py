import streamlit as st
import pandas as pd
import google.generativeai as genai
from googleapiclient.discovery import build
import time

# 1. 페이지 설정
st.set_page_config(page_title="Solinker YouTube Analyst", page_icon="📊", layout="wide")

st.title("📊 Solinker 유튜브 채널 심층 분석기")
st.markdown("---")

# 2. 사이드바 설정 (API 키 및 입력)
with st.sidebar:
    st.header("⚙️ 설정 패널")
    
    # YouTube API 키 입력 (비밀번호 형식)
    youtube_api_key = st.text_input("YouTube API Key", type="password")
    
    # Gemini API Key는 Secrets에서 가져옴 (없을 경우 입력창 표시)
    if "GEMINI_API_KEY" in st.secrets:
        gemini_api_key = st.secrets["GEMINI_API_KEY"]
        st.success("✅ Gemini 엔진 준비 완료 (Secrets)")
    else:
        gemini_api_key = st.text_input("Gemini API Key", type="password")
        st.warning("⚠️ Secrets에 Gemini 키가 없습니다.")

    st.markdown("---")
    channel_handle = st.text_input("채널 핸들 (@포함)", value="@bonogain619")
    analyze_btn = st.button("⚡ 심층 분석 시작", type="primary")

# 3. Gemini 모델 설정 (가장 중요: 1.5 Flash 고정)
if gemini_api_key:
    try:
        genai.configure(api_key=gemini_api_key)
        # 안전장치: 구형 모델 대신 최신 Flash 모델 명시
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        st.error(f"Gemini 설정 오류: {e}")

# 4. 유튜브 데이터 수집 함수
def get_channel_stats(youtube, channel_id):
    request = youtube.channels().list(part="snippet,contentDetails,statistics", id=channel_id)
    response = request.execute()
    return response['items'][0]

def get_video_ids(youtube, playlist_id):
    video_ids = []
    request = youtube.playlistItems().list(part="snippet,contentDetails", playlistId=playlist_id, maxResults=50)
    response = request.execute()
    for item in response['items']:
        video_ids.append(item['contentDetails']['videoId'])
    return video_ids

def get_video_details(youtube, video_ids):
    all_video_info = []
    for i in range(0, len(video_ids), 50):
        request = youtube.videos().list(part="snippet,statistics", id=','.join(video_ids[i:i+50]))
        response = request.execute()
        for video in response['items']:
            stats = video['statistics']
            snippet = video['snippet']
            all_video_info.append({
                'Title': snippet['title'],
                'Published_date': snippet['publishedAt'],
                'Views': int(stats.get('viewCount', 0)),
                'Likes': int(stats.get('likeCount', 0)),
                'Comments': int(stats.get('commentCount', 0))
            })
    return all_video_info

# 5. 메인 로직
if analyze_btn:
    if not youtube_api_key or not gemini_api_key:
        st.error("🚨 API 키가 필요합니다. (YouTube 및 Gemini)")
    else:
        try:
            with st.spinner("🔍 채널 데이터를 수집하고 있습니다..."):
                youtube = build('youtube', 'v3', developerKey=youtube_api_key)
                
                # 핸들로 채널 ID 찾기
                search_response = youtube.search().list(part="snippet", q=channel_handle, type="channel").execute()
                if not search_response['items']:
                    st.error("채널을 찾을 수 없습니다.")
                    st.stop()
                
                channel_id = search_response['items'][0]['snippet']['channelId']
                
                # 데이터 수집
                channel_stats = get_channel_stats(youtube, channel_id)
                uploads_playlist_id = channel_stats['contentDetails']['relatedPlaylists']['uploads']
                video_ids = get_video_ids(youtube, uploads_playlist_id)
                video_data = get_video_details(youtube, video_ids)
                
                df = pd.DataFrame(video_data)
                
            st.success("✅ 데이터 수집 완료!")
            
            # 데이터 표시
            col1, col2 = st.columns([1, 1])
            with col1:
                st.subheader("📈 상위 5개 인기 영상")
                top_videos = df.sort_values(by='Views', ascending=False).head(5)
                st.dataframe(top_videos[['Title', 'Views', 'Likes']])
                
            with col2:
                st.subheader("📊 채널 기본 통계")
                st.write(f"**구독자 수:** {channel_stats['statistics']['subscriberCount']}")
                st.write(f"**총 조회수:** {channel_stats['statistics']['viewCount']}")
                st.write(f"**총 영상 수:** {channel_stats['statistics']['videoCount']}")

            # AI 분석 요청
            st.markdown("---")
            st.subheader("🤖 Gemini AI 심층 인사이트")
            
            with st.spinner("🧠 AI가 데이터를 분석하여 전략을 수립 중입니다..."):
                # 프롬프트 구성
                data_summary = top_videos.to_string()
                prompt = f"""
                당신은 전문 유튜브 컨설턴트입니다. 아래는 '{channel_handle}' 채널의 상위 인기 영상 데이터입니다.
                
                [데이터]
                {data_summary}
                
                [요청사항]
                1. 이 채널이 성공한 주요 요인(키워드, 주제 등)을 3가지로 요약해 주세요.
                2. 조회수가 높은 영상들의 공통된 패턴을 분석해 주세요.
                3. 향후 채널 성장을 위한 구체적인 콘텐츠 아이디어 1가지를 제안해 주세요.
                
                답변은 전문적이고 격려하는 어조로 작성해 주세요.
                """
                
                response = model.generate_content(prompt)
                st.info(response.text)

        except Exception as e:
            st.error(f"❌ 오류 발생: {str(e)}")
            st.warning("팁: Gemini API 관련 오류라면 키 권한이나 모델명(gemini-1.5-flash)을 확인하세요.")
