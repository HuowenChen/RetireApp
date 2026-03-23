import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
import json
import os

# --- 🌟 自動設定深色模式 (Dark Mode) ---
os.makedirs(".streamlit", exist_ok=True)
config_path = ".streamlit/config.toml"
dark_theme_config = "[theme]\nbase='dark'\n"
if not os.path.exists(config_path) or open(config_path).read() != dark_theme_config:
    with open(config_path, "w") as f:
        f.write(dark_theme_config)

st.set_page_config(page_title="RetireFlow 退休資產戰情室", layout="wide")

# --- Google Sheets 連線設定 ---
@st.cache_resource
def init_connection():
    creds_dict = json.loads(st.secrets["gcp_service_account"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(st.secrets["sheet_url"])
    sheet_stocks = spreadsheet.sheet1
    try: sheet_funds = spreadsheet.worksheet("基金帳戶")
    except: sheet_funds = spreadsheet.add_worksheet(title="基金帳戶", rows="100", cols="20")
    return sheet_stocks, sheet_funds

try:
    sheet_stocks, sheet_funds = init_connection()
except Exception as e:
    st.error(f"連線失敗: {e}")
    st.stop()

# --- 讀取資料 (唯讀) ---
def load_data_from_sheets():
    raw_stocks = sheet_stocks.get_all_values()
    if len(raw_stocks) > 1:
        df_stocks = pd.DataFrame(raw_stocks[1:], columns=raw_stocks[0])
        if "券商" not in df_stocks.columns: df_stocks.insert(1, "券商", "未指定")
        if "預估殖利率(%)" not in df_stocks.columns: df_stocks["預估殖利率(%)"] = 4.0
        df_stocks["代號"] = df_stocks["代號"].astype(str).str.replace("'", "").str.strip()
        df_stocks["股數"] = pd.to_numeric(df_stocks["股數"], errors='coerce').fillna(0)
        df_stocks["預估殖利率(%)"] = pd.to_numeric(df_stocks["預估殖利率(%)"], errors='coerce').fillna(0)
    else:
        df_stocks = pd.DataFrame(columns=["市場", "券商", "代號", "股數", "預估殖利率(%)"])
        
    raw_funds = sheet_funds.get_all_values()
    if len(raw_funds) > 1:
        df_funds = pd.DataFrame(raw_funds[1:], columns=raw_funds[0])
        if "券商/平台" not in df_funds.columns: df_funds.insert(1, "券商/平台", "未指定")
        df_funds["目前總額(TWD)"] = pd.to_numeric(df_funds["目前總額(TWD)"], errors='coerce').fillna(0)
        df_funds["預估殖利率(%)"] = pd.to_numeric(df_funds["預估殖利率(%)"], errors='coerce').fillna(0)
    else:
        df_funds = pd.DataFrame(columns=["基金名稱", "券商/平台", "目前總額(TWD)", "預估殖利率(%)"])
        
    return df_stocks, df_funds

# --- 🌟 全新升級：批次下載與快取引擎 (解決 Rate Limit 問題) ---
@st.cache_data(ttl=600, show_spinner=False)
def fetch_market_data_batched(df_stocks):
    market_data = {}
    
    # 1. 整理所有要抓的標準代號 (包含匯率)
    tickers_primary = ["TWD=X", "JPYTWD=X"]
    for _, row in df_stocks.iterrows():
        sym = str(row["代號"]).upper().strip()
        if row["市場"] == "台股": tickers_primary.append(f"{sym}.TW")
        elif row["市場"] == "美股": tickers_primary.append(sym)
        elif row["市場"] == "日股": tickers_primary.append(f"{sym}.T")
            
    tickers_primary = list(set(tickers_primary))

    # 2. 第一次批次抓取 (只發送 1 次請求)
    if tickers_primary:
        try:
            data = yf.download(tickers_primary, period="5d", ignore_tz=True)
            if not data.empty and 'Close' in data:
                close_data = data['Close']
                for t in tickers_primary:
                    try:
                        val = close_data[t].iloc[-1] if isinstance(close_data, pd.DataFrame) else close_data.iloc[-1]
                        market_data[t] = float(val) if pd.notna(val) else 0.0
                    except:
                        market_data[t] = 0.0
        except Exception as e:
            print(f"Primary batch failed: {e}")

    # 3. 找出抓失敗的台股，自動轉換為上櫃 (.TWO) 進行第二次批次抓取
    tickers_otc = []
    for _, row in df_stocks.iterrows():
        if row["市場"] == "台股":
            sym = str(row["代號"]).upper().strip()
            if market_data.get(f"{sym}.TW", 0.0) == 0.0:
                tickers_otc.append(f"{sym}.TWO")
                
    tickers_otc = list(set(tickers_otc))
    if tickers_otc:
        try:
            data_otc = yf.download(tickers_otc, period="5d", ignore_tz=True)
            if not data_otc.empty and 'Close' in data_otc:
                close_otc = data_otc['Close']
                for t in tickers_otc:
                    try:
                        val = close_otc[t].iloc[-1] if isinstance(close_otc, pd.DataFrame) else close_otc.iloc[-1]
                        market_data[t] = float(val) if pd.notna(val) else 0.0
                    except:
                        market_data[t] = 0.0
        except Exception as e:
            print(f"OTC batch failed: {e}")

    return market_data

# --- 側邊欄與主畫面 ---
st.sidebar.header("🎯 退休目標設定")
fire_goal = st.sidebar.number_input("目標總資產 (TWD)", value=120000000, step=10000000)
monthly_expense = st.sidebar.number_input("預估每月花費 (TWD)", value=250000, step=10000)

st.title("📊 RetireFlow 退休戰情室")
st.markdown("### 跨券商集中管理大廳")
st.info("💡 **唯讀同步模式**：請在您的 Google 試算表中維護持股，修改完成後點擊下方按鈕進行結算。")

# --- 核心邏輯 ---
if st.button("🔄 從 Google 試算表同步並結算總值", type="primary", use_container_width=True):
    with st.spinner('透過批次引擎高速抓取全球報價中...'):
        try:
            df_stocks, df_funds = load_data_from_sheets()
            
            # 呼叫快取版的批次抓價引擎
            market_data = fetch_market_data_batched(df_stocks)
            
            # 提取匯率
            usd_twd = market_data.get("TWD=X", 32.0)
            if usd_twd == 0.0: usd_twd = 32.0
            jpy_twd = market_data.get("JPYTWD=X", 0.22)
            if jpy_twd == 0.0: jpy_twd = 0.22

            raw_data = []
            total_value = 0
            
            for _, row in df_stocks.iterrows():
                market, broker, symbol, shares, yield_pct = row["市場"], str(row.get("券商", "未指定")), str(row["代號"]).upper().strip(), row["股數"], float(row.get("預估殖利率(%)", 0))/100.0
                
                price = 0.0
                fx = 1.0
                if market == "台股":
                    price = market_data.get(f"{symbol}.TW", market_data.get(f"{symbol}.TWO", 0.0))
                elif market == "美股":
                    price = market_data.get(symbol, 0.0)
                    fx = usd_twd
                elif market == "日股":
                    price = market_data.get(f"{symbol}.T", 0.0)
                    fx = jpy_twd
                    
                value_twd = price * shares * fx
                dividend_twd = value_twd * yield_pct
                total_value += value_twd
                raw_data.append([market, broker, symbol, shares, price, fx, value_twd, yield_pct, dividend_twd])

            for _, row in df_funds.iterrows():
                broker, fund_name, fund_value, yield_pct = str(row.get("券商/平台", "未指定")), row["基金名稱"], float(row["目前總額(TWD)"]), float(row.get("預估殖利率(%)", 0))/100.0
                dividend_twd = fund_value * yield_pct
                total_value += fund_value
                raw_data.append(["基金", broker, fund_name, "-", "-", "-", fund_value, yield_pct, dividend_twd])

            df_raw = pd.DataFrame(raw_data, columns=["市場", "券商", "標的", "股數", "現價", "匯率", "市值", "殖利率", "年配息"])
            total_annual_dividend = df_raw["年配息"].sum()
            monthly_dividend = total_annual_dividend / 12
            
            st.subheader("💰 總資產與現金流")
            col1, col2, col3 = st.columns(3)
            col1.metric("全球總資產 (TWD)", f"${total_value:,.0f}")
            col2.metric("年領被動收入 (TWD)", f"${total_annual_dividend:,.0f}")
            col3.metric("平均每月被動收入", f"${monthly_dividend:,.0f}", f"距離目標: ${monthly_expense - monthly_dividend:,.0f}" if monthly_expense > monthly_dividend else "✅ 已達標")
            
            st.markdown("---")
            
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("🚀 總資產目標進度")
                progress = min(total_value / fire_goal, 1.0) if fire_goal > 0 else 1.0
                st.progress(progress)
                st.write(f"目前達成率：**{progress*100:.2f}%** (目標：${fire_goal:,.0f})")

            with c2:
                st.subheader("🏦 各券商/平台 資產佔比")
                broker_summary = df_raw.groupby("券商").agg({"市值": "sum"}).reset_index()
                if not broker_summary.empty and broker_summary["市值"].sum() > 0:
                    fig = px.pie(broker_summary, values='市值', names='券商', hole=0.4)
                    fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
                    st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")
            st.subheader("📋 標的明細清單")
            df_display = df_raw.copy()
            df_display["現價"] = df_display["現價"].apply(lambda x: f"{float(x):.2f}" if x != "-" else x)
            df_display["市值"] = df_display["市值"].map(lambda x: f"{x:,.0f}")
            df_display["殖利率"] = df_display["殖利率"].map(lambda x: f"{x*100:.2f}%")
            df_display["年配息"] = df_display["年配息"].map(lambda x: f"{x:,.0f}")
            st.dataframe(df_display, use_container_width=True)

        except Exception as e:
            st.error(f"計算發生錯誤。詳細錯誤: {e}")