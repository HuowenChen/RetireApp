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
# 檢查如果還沒有設定深色模式，就自動寫入
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

# --- 🌟 全新讀取機制：強制純文字讀取，終結吃 0 問題 ---
def load_stocks():
    try:
        raw_data = sheet_stocks.get_all_values()
        if len(raw_data) <= 1: 
            return pd.DataFrame(columns=["市場", "券商", "代號", "股數", "預估殖利率(%)"])
        
        df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
        
        if "券商" not in df.columns: df.insert(1, "券商", "未指定")
        if "預估殖利率(%)" not in df.columns: df["預估殖利率(%)"] = 4.0
        
        # 移除可能存在的隱形單引號，並保留純文字格式
        df["代號"] = df["代號"].astype(str).str.replace("'", "").str.strip()
        
        # 將數量與殖利率安全地轉回數字
        df["股數"] = pd.to_numeric(df["股數"], errors='coerce').fillna(0)
        df["預估殖利率(%)"] = pd.to_numeric(df["預估殖利率(%)"], errors='coerce').fillna(0)
        
        return df
    except Exception as e: 
        st.error(f"讀取錯誤: {e}")
        return pd.DataFrame(columns=["市場", "券商", "代號", "股數", "預估殖利率(%)"])

def load_funds():
    try:
        raw_data = sheet_funds.get_all_values()
        if len(raw_data) <= 1: 
            return pd.DataFrame(columns=["基金名稱", "券商/平台", "目前總額(TWD)", "預估殖利率(%)"])
        
        df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
        if "券商/平台" not in df.columns: df.insert(1, "券商/平台", "未指定")
        
        df["目前總額(TWD)"] = pd.to_numeric(df["目前總額(TWD)"], errors='coerce').fillna(0)
        df["預估殖利率(%)"] = pd.to_numeric(df["預估殖利率(%)"], errors='coerce').fillna(0)
        return df
    except: 
        return pd.DataFrame(columns=["基金名稱", "券商/平台", "目前總額(TWD)", "預估殖利率(%)"])

# --- 儲存資料 ---
def save_all_data(df_stocks, df_funds):
    try:
        # 存檔時，強制在代號前加上單引號，確保 Google 雲端不會再度把它變數字
        df_stocks_save = df_stocks.copy()
        df_stocks_save["代號"] = df_stocks_save["代號"].apply(lambda x: f"'{x}" if pd.notnull(x) and str(x).strip() != "" else x)

        sheet_stocks.clear() 
        sheet_stocks.update(values=[df_stocks_save.columns.values.tolist()] + df_stocks_save.values.tolist(), range_name="A1")
        sheet_funds.clear()
        sheet_funds.update(values=[df_funds.columns.values.tolist()] + df_funds.values.tolist(), range_name="A1")
        return True
    except: return False

# --- 側邊欄與主畫面 ---
st.sidebar.header("🎯 退休目標設定")
fire_goal = st.sidebar.number_input("目標總資產 (TWD)", value=20000000, step=1000000)
monthly_expense = st.sidebar.number_input("預估每月花費 (TWD)", value=50000, step=5000)

st.title("📊 RetireFlow 退休戰情室")
st.markdown("### 跨券商集中管理大廳")

df_all_stocks = load_stocks()
df_funds = load_funds()

tab1, tab2, tab3, tab4 = st.tabs(["🇹🇼 台股", "🇺🇸 美股", "🇯🇵 日股", "📈 基金"])
stock_col_config = {
    "市場": st.column_config.SelectboxColumn("市場", options=["台股", "美股", "日股"], required=True),
    "券商": st.column_config.TextColumn("所屬券商", required=True),
    "代號": st.column_config.TextColumn("代號 (字串鎖定)", required=True),
    "股數": st.column_config.NumberColumn("持股數量", min_value=0, required=True),
    "預估殖利率(%)": st.column_config.NumberColumn("殖利率(%)", min_value=0.0, format="%.2f", required=True)
}

with tab1:
    df_tw = df_all_stocks[df_all_stocks["市場"] == "台股"].copy()
    edited_tw = st.data_editor(df_tw, num_rows="dynamic", use_container_width=True, column_config=stock_col_config, key="tw")
with tab2:
    df_us = df_all_stocks[df_all_stocks["市場"] == "美股"].copy()
    edited_us = st.data_editor(df_us, num_rows="dynamic", use_container_width=True, column_config=stock_col_config, key="us")
with tab3:
    df_jp = df_all_stocks[df_all_stocks["市場"] == "日股"].copy()
    edited_jp = st.data_editor(df_jp, num_rows="dynamic", use_container_width=True, column_config=stock_col_config, key="jp")
with tab4:
    edited_funds = st.data_editor(df_funds, num_rows="dynamic", use_container_width=True, column_config={"券商/平台": st.column_config.TextColumn("所屬券商", required=True)}, key="funds")

if st.button("💾 儲存所有券商變更至雲端", type="secondary", use_container_width=True):
    with st.spinner("同步中..."):
        edited_tw["市場"], edited_us["市場"], edited_jp["市場"] = "台股", "美股", "日股"
        merged_stocks = pd.concat([edited_tw, edited_us, edited_jp], ignore_index=True)
        if save_all_data(merged_stocks, edited_funds): st.success("✅ 同步成功！代號前的 0 將被永久保存。")

@st.cache_data(ttl=600)
def get_market_data(portfolio_df):
    market_dict = {}
    tickers_to_fetch = [f"{str(row['代號']).upper().strip()}.TW" if row["市場"]=="台股" else f"{str(row['代號']).upper().strip()}.T" if row["市場"]=="日股" else str(row['代號']).upper().strip() for _, row in portfolio_df.iterrows()]
    for t in set(tickers_to_fetch):
        try: market_dict[t] = float(yf.Ticker(t).history(period="5d")['Close'].iloc[-1])
        except: market_dict[t] = 0.0
    try: usd_twd = float(yf.Ticker("TWD=X").history(period="5d")['Close'].iloc[-1])
    except: usd_twd = 32.0
    try: jpy_twd = float(yf.Ticker("JPYTWD=X").history(period="5d")['Close'].iloc[-1])
    except: jpy_twd = 0.22
    return market_dict, usd_twd, jpy_twd

st.markdown("---")

if st.button("🔄 結算全球帳戶總值", type="primary", use_container_width=True):
    with st.spinner('彙整各券商資料中...'):
        try:
            merged_stocks = pd.concat([edited_tw, edited_us, edited_jp], ignore_index=True)
            market_data, usd_twd, jpy_twd = get_market_data(merged_stocks)
            
            raw_data = []
            total_value = 0
            
            for _, row in merged_stocks.iterrows():
                market, broker, symbol, shares, yield_pct = row["市場"], str(row.get("券商", "未指定")), str(row["代號"]).upper().strip(), row["股數"], float(row.get("預估殖利率(%)", 0))/100.0
                if market == "台股": price, fx = market_data.get(f"{symbol}.TW", 0.0), 1.0
                elif market == "美股": price, fx = market_data.get(symbol, 0.0), usd_twd
                elif market == "日股": price, fx = market_data.get(f"{symbol}.T", 0.0), jpy_twd
                
                value_twd = price * shares * fx
                dividend_twd = value_twd * yield_pct
                total_value += value_twd
                raw_data.append([market, broker, symbol, shares, price, fx, value_twd, yield_pct, dividend_twd])

            for _, row in edited_funds.iterrows():
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
            st.subheader("🏦 各券商/平台 集中管理總覽")
            
            broker_summary = df_raw.groupby("券商").agg({"市值": "sum", "年配息": "sum"}).reset_index()
            broker_summary = broker_summary.sort_values(by="市值", ascending=False)
            broker_summary["資產佔比"] = (broker_summary["市值"] / total_value) * 100 if total_value > 0 else 0

            display_broker = broker_summary.copy()
            display_broker["市值"] = display_broker["市值"].map(lambda x: f"${x:,.0f}")
            display_broker["年配息"] = display_broker["年配息"].map(lambda x: f"${x:,.0f}")
            display_broker["資產佔比"] = display_broker["資產佔比"].map(lambda x: f"{x:.1f}%")
            
            col_b1, col_b2 = st.columns([2, 1])
            with col_b1:
                st.dataframe(display_broker, use_container_width=True)
            with col_b2:
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
            st.error(f"計算錯誤: {e}")