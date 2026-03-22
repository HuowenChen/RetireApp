import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
import json

st.set_page_config(page_title="RetireFlow 退休資產戰情室", layout="wide")

# --- Google Sheets 連線設定 (包含自動建立基金分頁) ---
@st.cache_resource
def init_connection():
    creds_dict = json.loads(st.secrets["gcp_service_account"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(st.secrets["sheet_url"])
    
    # 讀取原本的股票表單
    sheet_stocks = spreadsheet.sheet1
    
    # 自動尋找或建立「基金帳戶」表單
    try:
        sheet_funds = spreadsheet.worksheet("基金帳戶")
    except:
        # 如果找不到，就自動建一個新的 Tab 在您的 Google 表單裡
        sheet_funds = spreadsheet.add_worksheet(title="基金帳戶", rows="100", cols="20")
        
    return sheet_stocks, sheet_funds

try:
    sheet_stocks, sheet_funds = init_connection()
except Exception as e:
    st.error(f"無法連線至 Google 試算表，請檢查 Secrets 設定。錯誤訊息: {e}")
    st.stop()

# --- 讀取資料的函數 (分為股票與基金) ---
def load_stocks():
    try:
        records = sheet_stocks.get_all_records()
        if not records: 
            return pd.DataFrame({"市場": ["台股", "美股", "日股"], "代號": ["2330", "VT", "7203"], "股數": [1000, 50, 100], "預估殖利率(%)": [1.5, 2.0, 3.0]})
        df = pd.DataFrame(records)
        if "預估殖利率(%)" not in df.columns: df["預估殖利率(%)"] = 4.0
        df["代號"] = df["代號"].astype(str)
        df["代號"] = df.apply(lambda row: str(row["代號"]).zfill(4) if row["市場"] == "台股" and len(str(row["代號"])) < 4 else str(row["代號"]), axis=1)
        return df
    except:
        return pd.DataFrame(columns=["市場", "代號", "股數", "預估殖利率(%)"])

def load_funds():
    try:
        records = sheet_funds.get_all_records()
        if not records:
            return pd.DataFrame({"基金名稱": ["安聯收益成長基金", "元大台灣高股息優質龍頭基金"], "目前總額(TWD)": [500000, 300000], "預估殖利率(%)": [8.0, 5.0]})
        return pd.DataFrame(records)
    except:
        return pd.DataFrame(columns=["基金名稱", "目前總額(TWD)", "預估殖利率(%)"])

# --- 儲存資料的函數 (一次存兩份) ---
def save_all_data(df_stocks, df_funds):
    try:
        sheet_stocks.clear() 
        sheet_stocks.update(values=[df_stocks.columns.values.tolist()] + df_stocks.values.tolist(), range_name="A1")
        
        sheet_funds.clear()
        sheet_funds.update(values=[df_funds.columns.values.tolist()] + df_funds.values.tolist(), range_name="A1")
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

# --- 側邊欄 ---
st.sidebar.header("🎯 退休目標設定")
fire_goal = st.sidebar.number_input("目標總資產 (TWD)", value=20000000, step=1000000)
monthly_expense = st.sidebar.number_input("退休後預估每月花費 (TWD)", value=50000, step=5000)

st.title("📊 RetireFlow 退休戰情室")
st.markdown("### 多帳戶資產與現金流整合系統")

# 讀取全部資料
df_all_stocks = load_stocks()
df_funds = load_funds()

# --- 🌟 全新分頁設計 (Tabs) ---
tab1, tab2, tab3, tab4 = st.tabs(["🇹🇼 台股帳戶", "🇺🇸 美股帳戶", "🇯🇵 日股帳戶", "📈 基金總額管理"])

with tab1:
    st.info("💡 **台股部位：** 請輸入台股代號與股數 (例: 2330, 0056)。")
    df_tw = df_all_stocks[df_all_stocks["市場"] == "台股"].copy()
    edited_tw = st.data_editor(df_tw, num_rows="dynamic", use_container_width=True, key="tw_editor")

with tab2:
    st.info("💡 **美股部位：** 請輸入美股代號與股數 (例: VT, AAPL)。")
    df_us = df_all_stocks[df_all_stocks["市場"] == "美股"].copy()
    edited_us = st.data_editor(df_us, num_rows="dynamic", use_container_width=True, key="us_editor")

with tab3:
    st.info("💡 **日股部位：** 請輸入日股代號與股數 (例: 7203, 6526)。")
    df_jp = df_all_stocks[df_all_stocks["市場"] == "日股"].copy()
    edited_jp = st.data_editor(df_jp, num_rows="dynamic", use_container_width=True, key="jp_editor")

with tab4:
    st.info("💡 **基金帳戶：** 基金報價較難即時取得，請直接手動輸入您在銀行/券商看到的「目前帳戶總額 (台幣)」。")
    edited_funds = st.data_editor(df_funds, num_rows="dynamic", use_container_width=True, key="funds_editor")

# --- 統一儲存按鈕 ---
st.markdown("<br>", unsafe_allow_html=True)
if st.button("💾 將所有帳戶的變更儲存至雲端", type="secondary", use_container_width=True):
    with st.spinner("正在同步至 Google 試算表..."):
        # 把分開編輯的三個股票 DataFrame 重新合併成一個
        edited_tw["市場"] = "台股"
        edited_us["市場"] = "美股"
        edited_jp["市場"] = "日股"
        merged_stocks = pd.concat([edited_tw, edited_us, edited_jp], ignore_index=True)
        
        if save_all_data(merged_stocks, edited_funds):
            st.success("✅ 台股、美股、日股與基金帳戶皆已同步成功！")

# --- 抓價邏輯 ---
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
        except: market_dict[t] = 0.0

    try: usd_twd = float(yf.Ticker("TWD=X").history(period="5d")['Close'].iloc[-1])
    except: usd_twd = 32.0

    try: jpy_twd = float(yf.Ticker("JPYTWD=X").history(period="5d")['Close'].iloc[-1])
    except:
        try: jpy_twd = (1 / float(yf.Ticker("JPY=X").history(period="5d")['Close'].iloc[-1])) * usd_twd
        except: jpy_twd = 0.22

    return market_dict, usd_twd, jpy_twd

st.markdown("---")

# --- 結算與顯示 ---
if st.button("🔄 結算多帳戶最新資產總值", type="primary", use_container_width=True):
    with st.spinner('正在連線交易所並彙整基金資料...'):
        try:
            # 合併股票資料以供計算
            merged_stocks = pd.concat([edited_tw, edited_us, edited_jp], ignore_index=True)
            market_data, usd_twd, jpy_twd = get_market_data(merged_stocks)
            
            results = []
            total_value = 0
            total_annual_dividend = 0
            
            # 1. 計算股票部位
            for index, row in merged_stocks.iterrows():
                market = row["市場"]
                symbol = str(row["代號"]).upper().strip()
                shares = row["股數"]
                yield_pct = float(row.get("預估殖利率(%)", 0)) / 100.0
                
                if market == "台股": price, fx = market_data.get(f"{symbol}.TW", 0.0), 1.0
                elif market == "美股": price, fx = market_data.get(symbol, 0.0), usd_twd
                elif market == "日股": price, fx = market_data.get(f"{symbol}.T", 0.0), jpy_twd
                
                value_twd = price * shares * fx
                dividend_twd = value_twd * yield_pct
                
                total_value += value_twd
                total_annual_dividend += dividend_twd
                results.append([market, symbol, shares, price, fx, value_twd, yield_pct*100, dividend_twd])

            # 2. 計算基金部位
            for index, row in edited_funds.iterrows():
                fund_name = row["基金名稱"]
                fund_value = float(row["目前總額(TWD)"])
                yield_pct = float(row.get("預估殖利率(%)", 0)) / 100.0
                
                dividend_twd = fund_value * yield_pct
                total_value += fund_value
                total_annual_dividend += dividend_twd
                # 為了能統整在同一個明細表，格式維持一致
                results.append(["基金", fund_name, "-", "-", "-", fund_value, yield_pct*100, dividend_twd])

            monthly_dividend = total_annual_dividend / 12
            
            st.subheader("💰 資產與現金流摘要")
            col1, col2, col3 = st.columns(3)
            col1.metric("總資產現值 (TWD)", f"${total_value:,.0f}")
            col2.metric("預估年領被動收入 (TWD)", f"${total_annual_dividend:,.0f}")
            col3.metric("平均每月被動收入", f"${monthly_dividend:,.0f}", 
                        f"目標缺口: ${monthly_expense - monthly_dividend:,.0f}" if monthly_expense > monthly_dividend else "✅ 已達財務自由")
            
            st.markdown("---")

            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("🚀 總資產目標進度")
                progress = min(total_value / fire_goal, 1.0) if fire_goal > 0 else 1.0
                st.progress(progress)
                st.write(f"目前達成率：**{progress*100:.2f}%** (目標：${fire_goal:,.0f})")

            with c2:
                st.subheader("被動現金