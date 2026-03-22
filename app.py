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
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(st.secrets["sheet_url"]).sheet1
    return sheet

try:
    sheet = init_connection()
except Exception as e:
    st.error(f"無法連線至 Google 試算表，請檢查 Secrets 設定。錯誤訊息: {e}")
    st.stop()

# --- 讀寫資料的函數 ---
def load_data():
    try:
        records = sheet.get_all_records()
        if not records: 
            return pd.DataFrame({"市場": ["台股", "台股", "美股", "日股"], "代號": ["2330", "0050", "VT", "7203"], "股數": [1000, 2000, 50, 100], "預估殖利率(%)": [1.5, 3.5, 2.0, 3.0]})
        
        df = pd.DataFrame(records)
        df["代號"] = df["代號"].astype(str)
        df["代號"] = df.apply(lambda row: str(row["代號"]).zfill(4) if row["市場"] == "台股" and len(str(row["代號"])) < 4 else str(row["代號"]), axis=1)
        
        # 🌟 自動相容舊版資料：如果舊表單沒有殖利率欄位，自動補上預設值 4.0%
        if "預估殖利率(%)" not in df.columns:
            df["預估殖利率(%)"] = 4.0
            
        return df
    except Exception as e:
        st.error(f"讀取資料失敗: {e}")
        return pd.DataFrame(columns=["市場", "代號", "股數", "預估殖利率(%)"])

def save_data(df):
    try:
        sheet.clear() 
        data_to_write = [df.columns.values.tolist()] + df.values.tolist()
        sheet.update(values=data_to_write, range_name="A1")
        return True
    except Exception as e:
        st.error(f"儲存資料失敗: {e}")
        return False

# --- 側邊欄 ---
st.sidebar.header("🎯 退休目標設定")
fire_goal = st.sidebar.number_input("目標總資產 (TWD)", value=20000000, step=1000000)
monthly_expense = st.sidebar.number_input("退休後預估每月花費 (TWD)", value=50000, step=5000)

st.title("📊 RetireFlow 退休戰情室")
st.markdown("### 跨市場複委託管理系統 ＆ 現金流試算")

current_portfolio = load_data()

# 互動式表格加入「預估殖利率」
edited_portfolio = st.data_editor(
    current_portfolio,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "市場": st.column_config.SelectboxColumn("市場", options=["台股", "美股", "日股"], required=True),
        "代號": st.column_config.TextColumn("代號 (例: 2330, AAPL)", required=True),
        "股數": st.column_config.NumberColumn("持股數量", min_value=0, required=True),
        "預估殖利率(%)": st.column_config.NumberColumn("預估殖利率(%)", min_value=0.0, format="%.2f", required=True)
    }
)

if st.button("💾 儲存至雲端 (Google Sheets)"):
    with st.spinner("正在同步至 Google 試算表..."):
        if save_data(edited_portfolio):
            st.success("✅ 同步成功！")

# --- 抓價邏輯 (維持不變) ---
@st.cache_data(ttl=600)
def get_market_data(portfolio_df):
    market_dict = {}
    tickers_to_fetch = []
    for index, row in portfolio_df.iterrows():
        market = row["市場"]
        symbol = str(row["代號"]).upper().strip()
        if market == "台股": tickers_to_fetch.append(f"{symbol}.TW")
        elif market == "日股": tickers_to_fetch.append(f"{symbol}.T")
        else: tickers_to_fetch.append(symbol)

    for t in set(tickers_to_fetch):
        try:
            hist = yf.Ticker(t).history(period="5d")
            market_dict[t] = float(hist['Close'].iloc[-1]) if not hist.empty else 0.0
        except:
            market_dict[t] = 0.0

    try:
        usd_twd = float(yf.Ticker("TWD=X").history(period="5d")['Close'].iloc[-1])
    except: usd_twd = 32.0

    try:
        jpy_twd = float(yf.Ticker("JPYTWD=X").history(period="5d")['Close'].iloc[-1])
    except: jpy_twd = 0.22

    return market_dict, usd_twd, jpy_twd

st.markdown("---")

# --- 結算與顯示 ---
if st.button("🔄 結算最新資產總值", type="primary", use_container_width=True):
    with st.spinner('正在連線至全球交易所抓取最新報價...'):
        try:
            market_data, usd_twd, jpy_twd = get_market_data(edited_portfolio)
            
            results = []
            total_value = 0
            total_annual_dividend = 0
            
            for index, row in edited_portfolio.iterrows():
                market = row["市場"]
                symbol = str(row["代號"]).upper().strip()
                shares = row["股數"]
                yield_pct = float(row.get("預估殖利率(%)", 0)) / 100.0
                
                # 判斷市場與匯率
                if market == "台股":
                    price = market_data.get(f"{symbol}.TW", 0.0)
                    fx = 1.0
                elif market == "美股":
                    price = market_data.get(symbol, 0.0)
                    fx = usd_twd
                elif market == "日股":
                    price = market_data.get(f"{symbol}.T", 0.0)
                    fx = jpy_twd
                
                # 計算單股市值與股息
                value_twd = price * shares * fx
                dividend_twd = value_twd * yield_pct
                
                total_value += value_twd
                total_annual_dividend += dividend_twd
                
                results.append([market, symbol, shares, price, fx, value_twd, yield_pct*100, dividend_twd])

            monthly_dividend = total_annual_dividend / 12
            
            # --- 顯示資產與現金流指標 ---
            st.subheader("💰 資產與現金流摘要")
            col1, col2, col3 = st.columns(3)
            col1.metric("總資產現值 (TWD)", f"${total_value:,.0f}")
            col2.metric("預估年領股息 (TWD)", f"${total_annual_dividend:,.0f}")
            col3.metric("平均每月被動收入", f"${monthly_dividend:,.0f}", 
                        f"目標缺口: ${monthly_expense - monthly_dividend:,.0f}" if monthly_expense > monthly_dividend else "✅ 已達財務自由")
            
            st.markdown("---")

            # --- 圖表區塊 ---
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("🚀 總資產目標進度")
                progress = min(total_value / fire_goal, 1.0) if fire_goal > 0 else 1.0
                st.progress(progress)
                st.write(f"目前達成率：**{progress*100:.2f}%** (目標：${fire_goal:,.0f})")

            with