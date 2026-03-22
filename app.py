import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
import json

st.set_page_config(page_title="RetireFlow 退休資產戰情室", layout="wide")

# --- Google Sheets 連線設定 ---
@st.cache_resource
def init_connection():
    creds_dict = json.loads(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(st.secrets["sheet_url"]).sheet1
    return sheet

try:
    sheet = init_connection()
except Exception as e:
    st.error(f"無法連線至 Google 試算表，請檢查 Secrets 設定。錯誤訊息: {e}")
    st.stop()

# --- 讀寫資料的函數 (包含解鎖修正) ---
def load_data():
    try:
        records = sheet.get_all_records()
        if not records: 
            return pd.DataFrame({"市場": ["台股", "台股", "美股", "日股"], "代號": ["2330", "0050", "VT", "7203"], "股數": [1000, 2000, 50, 100]})
        
        df = pd.DataFrame(records)
        # 強制轉文字並補齊台股的 0
        df["代號"] = df["代號"].astype(str)
        df["代號"] = df.apply(lambda row: str(row["代號"]).zfill(4) if row["市場"] == "台股" and len(str(row["代號"])) < 4 else str(row["代號"]), axis=1)
        return df
    except Exception as e:
        st.error(f"讀取資料失敗: {e}")
        return pd.DataFrame(columns=["市場", "代號", "股數"])

def save_data(df):
    try:
        sheet.clear() 
        data_to_write = [df.columns.values.tolist()] + df.values.tolist()
        sheet.update(values=data_to_write, range_name="A1")
        return True
    except Exception as e:
        st.error(f"儲存資料失敗: {e}")
        return False

st.sidebar.header("🎯 退休目標設定")
fire_goal = st.sidebar.number_input("目標資產 (TWD)", value=20000000, step=1000000)

st.title("📊 RetireFlow 退休戰情室 (雲端同步版)")
st.markdown("### 跨市場複委託管理系統")
st.info("💡 **操作提示：** 下方表格已與您的 Google 試算表即時連動！修改後請點擊「💾 儲存至雲端」。")

current_portfolio = load_data()

edited_portfolio = st.data_editor(
    current_portfolio,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "市場": st.column_config.SelectboxColumn("市場", options=["台股", "美股", "日股"], required=True),
        "代號": st.column_config.TextColumn("代號 (例: 2330, AAPL)", required=True),
        "股數": st.column_config.NumberColumn("持股數量", min_value=0, required=True)
    }
)

if st.button("💾 儲存至雲端 (Google Sheets)"):
    with st.spinner("正在同步至 Google 試算表..."):
        if save_data(edited_portfolio):
            st.success("✅ 同步成功！您現在可以隨時隨地用手機查看最新資產了。")

# --- 🚀 核心邏輯：全新改寫的「週末防呆」抓價系統 ---
@st.cache_data(ttl=600)
def get_market_data(portfolio_df):
    market_dict = {}
    
    # 1. 整理所有要抓的代號
    tickers_to_fetch = []
    for index, row in portfolio_df.iterrows():
        market = row["市場"]
        symbol = str(row["代號"]).upper().strip()
        if market == "台股":
            tickers_to_fetch.append(f"{symbol}.TW")
        elif market == "日股":
            tickers_to_fetch.append(f"{symbol}.T")
        else: 
            tickers_to_fetch.append(symbol)

    # 2. 一檔一檔抓，設定 period="5d" 確保週末也能抓到週五的價格
    for t in set(tickers_to_fetch):
        try:
            hist = yf.Ticker(t).history(period="5d")
            if not hist.empty:
                market_dict[t] = float(hist['Close'].iloc[-1])
            else:
                market_dict[t] = 0.0
        except:
            market_dict[t] = 0.0

    # 3. 獨立抓取匯率 (含雙重備用機制)
    try:
        usd_hist = yf.Ticker("TWD=X").history(period="5d")
        usd_twd = float(usd_hist['Close'].iloc[-1]) if not usd_hist.empty else 32.0
    except:
        usd_twd = 32.0

    try:
        jpy_hist = yf.Ticker("JPYTWD=X").history(period="5d")
        jpy_twd = float(jpy_hist['Close'].iloc[-1]) if not jpy_hist.empty else 0.22
    except:
        try: # 備用：如果直抓不到 JPY/TWD，就用 JPY/USD 換算
            jpy_usd = yf.Ticker("JPY=X").history(period="5d")
            jpy_twd = (1 / float(jpy_usd['Close'].iloc[-1])) * usd_twd if not jpy_usd.empty else 0.22
        except:
            jpy_twd = 0.22

    return market_dict, usd_twd, jpy_twd

st.markdown("---")

if st.button("🔄 結算最新資產總值", type="primary", use_container_width=True):
    with st.spinner('正在連線至全球交易所抓取最新報價... (改為逐筆驗證，可能需要幾秒鐘)'):
        try:
            market_data, usd_twd, jpy_twd = get_market_data(edited_portfolio)
            
            results = []
            total_tw, total_us, total_jp = 0, 0, 0
            
            for index, row in edited_portfolio.iterrows():
                market = row["市場"]
                symbol = str(row["代號"]).upper().strip()
                shares = row["股數"]
                
                if market == "台股":
                    price = market_data.get(f"{symbol}.TW", 0.0)
                    value = price * shares
                    total_tw += value
                    results.append([market, symbol, shares, price, 1.0, value])
                    
                elif market == "美股":
                    price = market_data.get(symbol, 0.0)
                    value = price * shares * usd_twd
                    total_us += value
                    results.append([market, symbol, shares, price, usd_twd, value])
                    
                elif market == "日股":
                    price = market_data.get(f"{symbol}.T", 0.0)
                    value = price * shares * jpy_twd
                    total_jp += value
                    results.append([market, symbol, shares, price, jpy_twd, value])

            total_value = total_tw + total_us + total_jp
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("總資產 (TWD)", f"${total_value:,.0f}")
            col2.metric("台股總計", f"${total_tw:,.0f}")
            col3.metric("美股總計", f"${total_us:,.0f}", f"匯率 {usd_twd:.2f}")
            col4.metric("日股總計", f"${total_jp:,.0f}", f"匯率 {jpy_twd:.4f}")
            
            st.markdown("---")

            c1, c2 = st.columns([2, 1])
            with c1:
                st.subheader("🚀 退休目標進度")
                progress = min(total_value / fire_goal, 1.0) if fire_goal > 0 else 1.0
                st.progress(progress)
                st.write(f"目前達成率：**{progress*100:.2f}%** (目標：${fire_goal:,.0f})")

            with c2:
                st.subheader("資產配置佔比")
                df_pie = pd.DataFrame({'Market': ['台股', '美股', '日股'], 'Value': [total_tw, total_us, total_jp]})
                df_pie = df_pie[df_pie['Value'] > 0]
                if not df_pie.empty:
                    fig = px.pie(df_pie, values='Value', names='Market', hole=0.4)
                    fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
                    st.plotly_chart(fig, use_container_width=True)

            st.subheader("📋 投資組合最新明細")
            result_df = pd.DataFrame(results, columns=["市場", "代號", "股數", "現價(原幣)", "匯率", "台幣市值(TWD)"])
            result_df["現價(原幣)"] = result_df["現價(原幣)"].map(lambda x: f"{x:.2f}")
            result_df["匯率"] = result_df["匯率"].map(lambda x: f"{x:.4f}")
            result_df["台幣市值(TWD)"] = result_df["台幣市值(TWD)"].map(lambda x: f"{x:,.0f}")
            st.dataframe(result_df, use_container_width=True)

        except Exception as e:
            st.error(f"計算錯誤，請確認股票代號。詳細錯誤: {e}")