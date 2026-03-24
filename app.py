import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
import json
import os
from datetime import datetime, timezone, timedelta

# --- 🌟 自動設定深色模式 ---
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
    
    try: sheet_liab = spreadsheet.worksheet("負債清單")
    except: 
        sheet_liab = spreadsheet.add_worksheet(title="負債清單", rows="100", cols="10")
        sheet_liab.append_row(["負債項目(如房貸,質借)", "貸款機構", "目前餘額(TWD)", "貸款利率(%)"])

    # 🌟 新版歷史紀錄：新增各市場總計欄位
    try: sheet_history = spreadsheet.worksheet("資產歷史紀錄")
    except: 
        sheet_history = spreadsheet.add_worksheet(title="資產歷史紀錄", rows="1000", cols="9")
        sheet_history.append_row(["紀錄日期", "總資產(TWD)", "總負債(TWD)", "淨資產(TWD)", "預估年領股息(TWD)", "台股總計", "美股總計", "日股總計", "基金總計"])
        
    return sheet_stocks, sheet_funds, sheet_liab, sheet_history

try:
    sheet_stocks, sheet_funds, sheet_liab, sheet_history = init_connection()
except Exception as e:
    st.error(f"連線失敗: {e}")
    st.stop()

# --- 讀取資料 ---
def load_data_from_sheets():
    raw_stocks = sheet_stocks.get_all_values()
    if len(raw_stocks) > 1:
        df_stocks = pd.DataFrame(raw_stocks[1:], columns=raw_stocks[0])
        if "券商" not in df_stocks.columns: df_stocks.insert(1, "券商", "未指定")
        if "預估殖利率(%)" not in df_stocks.columns: df_stocks["預估殖利率(%)"] = 4.0
        df_stocks["代號"] = df_stocks["代號"].astype(str).str.replace("'", "").str.strip()
        df_stocks["股數"] = pd.to_numeric(df_stocks["股數"], errors='coerce').fillna(0)
        df_stocks["預估殖利率(%)"] = pd.to_numeric(df_stocks["預估殖利率(%)"], errors='coerce').fillna(0)
    else: df_stocks = pd.DataFrame(columns=["市場", "券商", "代號", "股數", "預估殖利率(%)"])
        
    raw_funds = sheet_funds.get_all_values()
    if len(raw_funds) > 1:
        df_funds = pd.DataFrame(raw_funds[1:], columns=raw_funds[0])
        if "券商/平台" not in df_funds.columns: df_funds.insert(1, "券商/平台", "未指定")
        df_funds["目前總額(TWD)"] = pd.to_numeric(df_funds["目前總額(TWD)"], errors='coerce').fillna(0)
        df_funds["預估殖利率(%)"] = pd.to_numeric(df_funds["預估殖利率(%)"], errors='coerce').fillna(0)
    else: df_funds = pd.DataFrame(columns=["基金名稱", "券商/平台", "目前總額(TWD)", "預估殖利率(%)"])
    
    raw_liab = sheet_liab.get_all_values()
    if len(raw_liab) > 1:
        df_liab = pd.DataFrame(raw_liab[1:], columns=raw_liab[0])
        df_liab["目前餘額(TWD)"] = pd.to_numeric(df_liab["目前餘額(TWD)"], errors='coerce').fillna(0)
    else: df_liab = pd.DataFrame(columns=["負債項目(如房貸,質借)", "貸款機構", "目前餘額(TWD)", "貸款利率(%)"])
        
    return df_stocks, df_funds, df_liab

def load_history():
    try:
        raw_hist = sheet_history.get_all_values()
        if len(raw_hist) > 1:
            df_hist = pd.DataFrame(raw_hist[1:], columns=raw_hist[0])
            numeric_cols = ["總資產(TWD)", "總負債(TWD)", "淨資產(TWD)", "預估年領股息(TWD)", "台股總計", "美股總計", "日股總計", "基金總計"]
            for col in numeric_cols:
                if col in df_hist.columns:
                    df_hist[col] = pd.to_numeric(df_hist[col], errors='coerce').fillna(0)
            return df_hist
        return pd.DataFrame()
    except: return pd.DataFrame()

# --- 🌟 終極抓價引擎：雙管齊下 (上市+上櫃) ---
@st.cache_data(ttl=600, show_spinner=False)
def fetch_market_data_robust(df_stocks):
    market_data = {}
    market_names = {} 
    tickers_primary = ["TWD=X", "JPYTWD=X"]
    
    for _, row in df_stocks.iterrows():
        sym = str(row["代號"]).upper().strip()
        if row["市場"] == "台股": 
            # 🌟 秘訣：同時把 .TW 和 .TWO 都丟進去抓，誰有資料就用誰！
            tickers_primary.extend([f"{sym}.TW", f"{sym}.TWO"])
        elif row["市場"] == "美股": tickers_primary.append(sym.replace(".", "-"))
        elif row["市場"] == "日股": tickers_primary.append(f"{sym}.T")
            
    tickers_primary = list(set(tickers_primary))

    if tickers_primary:
        try:
            data = yf.download(tickers_primary, period="5d", ignore_tz=True)
            if not data.empty:
                for t in tickers_primary:
                    try:
                        if ('Close', t) in data.columns: val = data[('Close', t)].dropna().iloc[-1]
                        elif 'Close' in data.columns and t in data['Close'].columns: val = data['Close'][t].dropna().iloc[-1]
                        elif 'Close' in data.columns: val = data['Close'].dropna().iloc[-1]
                        else: val = 0.0
                        market_data[t] = float(val) if pd.notna(val) else 0.0
                    except: pass
        except: pass

    # 抓取公司名稱 (只針對成功抓到報價的標的，加速處理)
    for t in tickers_primary:
        if market_data.get(t, 0.0) > 0.0:
            try:
                if t not in ["TWD=X", "JPYTWD=X"]:
                    short_name = yf.Ticker(t).info.get('shortName', '')
                    if short_name: market_names[t] = short_name
            except: pass

    return market_data, market_names

# --- 側邊欄：獨立目標設定 ---
st.sidebar.header("🎯 各市場資產目標")
fire_goal_tw = st.sidebar.number_input("🇹🇼 台股目標 (TWD)", value=60000000, step=5000000)
fire_goal_us = st.sidebar.number_input("🇺🇸 美股目標 (TWD)", value=40000000, step=5000000)
fire_goal_jp = st.sidebar.number_input("🇯🇵 日股目標 (TWD)", value=10000000, step=1000000)
fire_goal_fund = st.sidebar.number_input("📈 基金目標 (TWD)", value=10000000, step=1000000)

fire_goal_total = fire_goal_tw + fire_goal_us + fire_goal_jp + fire_goal_fund
st.sidebar.markdown("---")
monthly_expense = st.sidebar.number_input("預估每月花費 (TWD)", value=250000, step=10000)

st.title("📊 RetireFlow 退休戰情室")
st.info("💡 **操作提示**：請在您的 Google 試算表中維護持股與負債，修改完成後點擊下方按鈕結算。")

# --- 核心結算邏輯 ---
if st.button("🔄 同步結算資產與負債總額", type="primary", use_container_width=True):
    with st.spinner('連線全球交易所、掃描上櫃市場並彙整資料中...'):
        try:
            df_stocks, df_funds, df_liab = load_data_from_sheets()
            market_data, market_names = fetch_market_data_robust(df_stocks)
            
            usd_twd = market_data.get("TWD=X", 32.0)
            if usd_twd == 0.0: usd_twd = 32.0
            jpy_twd = market_data.get("JPYTWD=X", 0.22)
            if jpy_twd == 0.0: jpy_twd = 0.22

            raw_data = []
            total_assets = 0
            market_subtotals = {"台股": 0.0, "美股": 0.0, "日股": 0.0, "基金": 0.0}
            
            for _, row in df_stocks.iterrows():
                market, broker, symbol, shares, yield_pct = row["市場"], str(row.get("券商", "未指定")), str(row["代號"]).upper().strip(), row["股數"], float(row.get("預估殖利率(%)", 0))/100.0
                
                price = 0.0
                fx = 1.0
                stock_name = symbol 
                
                if market == "台股": 
                    # 🌟 優先取用 .TW，若為 0 則自動取用 .TWO (上櫃)
                    price = market_data.get(f"{symbol}.TW", 0.0)
                    target_t = f"{symbol}.TW"
                    if price == 0.0:
                        price = market_data.get(f"{symbol}.TWO", 0.0)
                        target_t = f"{symbol}.TWO"
                    stock_name = market_names.get(target_t, symbol)
                elif market == "美股": 
                    sym_us = symbol.replace(".", "-")
                    price, fx = market_data.get(sym_us, 0.0), usd_twd
                    stock_name = market_names.get(sym_us, symbol)
                elif market == "日股": 
                    target_t = f"{symbol}.T"
                    price, fx = market_data.get(target_t, 0.0), jpy_twd
                    stock_name = market_names.get(target_t, symbol)
                    
                value_twd = price * shares * fx
                dividend_twd = value_twd * yield_pct
                total_assets += value_twd
                market_subtotals[market] += value_twd
                
                display_name = f"{symbol} {stock_name}" if symbol != stock_name else symbol
                raw_data.append([market, broker, display_name, shares, price, fx, value_twd, yield_pct, dividend_twd])

            for _, row in df_funds.iterrows():
                broker, fund_name, fund_value, yield_pct = str(row.get("券商/平台", "未指定")), row["基金名稱"], float(row["目前總額(TWD)"]), float(row.get("預估殖利率(%)", 0))/100.0
                dividend_twd = fund_value * yield_pct
                total_assets += fund_value
                market_subtotals["基金"] += fund_value
                raw_data.append(["基金", broker, fund_name, "-", "-", "-", fund_value, yield_pct, dividend_twd])

            df_raw = pd.DataFrame(raw_data, columns=["市場", "券商", "標的名稱", "股數", "現價", "匯率", "市值(TWD)", "殖利率", "年配息(TWD)"])
            total_annual_dividend = df_raw["年配息(TWD)"].sum()
            monthly_dividend = total_annual_dividend / 12
            
            total_liabilities = df_liab["目前餘額(TWD)"].sum() if not df_liab.empty else 0
            net_worth = total_assets - total_liabilities
            
            # 寫入歷史紀錄 (包含細分市場)
            tz_tw = timezone(timedelta(hours=8))
            today_str = datetime.now(tz_tw).strftime("%Y-%m-%d")
            
            try:
                hist_records = sheet_history.get_all_values()
                new_row_data = [today_str, float(total_assets), float(total_liabilities), float(net_worth), float(total_annual_dividend), 
                                float(market_subtotals["台股"]), float(market_subtotals["美股"]), float(market_subtotals["日股"]), float(market_subtotals["基金"])]
                                
                if len(hist_records) > 1 and hist_records[-1][0] == today_str:
                    row_idx = len(hist_records)
                    sheet_history.update(values=[new_row_data], range_name=f"A{row_idx}:I{row_idx}")
                else:
                    sheet_history.append_row(new_row_data)
            except Exception as e:
                st.warning(f"歷史紀錄寫入失敗: {e}")

            # --- 畫面顯示區 ---
            st.subheader("🏦 財務健康總覽 (總資產 vs 總負債)")
            col_a, col_b, col_c, col_d = st.columns(4)
            col_a.metric("總資產 (TWD)", f"${total_assets:,.0f}")
            col_b.metric("總負債 (TWD)", f"${total_liabilities:,.0f}", delta_color="inverse")
            col_c.metric("✨ 淨資產 (TWD)", f"${net_worth:,.0f}")
            col_d.metric("平均每月被動收入", f"${monthly_dividend:,.0f}", f"缺口: ${monthly_expense - monthly_dividend:,.0f}" if monthly_expense > monthly_dividend else "✅ 已達標")
            
            st.markdown("---")

            st.subheader("📊 總資產配置佔比")
            col_pie1, col_pie2 = st.columns(2)
            with col_pie1:
                df_market_pie = df_raw.groupby("市場")["市值(TWD)"].sum().reset_index()
                if not df_market_pie.empty and df_market_pie["市值(TWD)"].sum() > 0:
                    fig_market = px.pie(df_market_pie, values='市值(TWD)', names='市場', hole=0.4, title="依市場/資產類別")
                    fig_market.update_layout(margin=dict(t=30, b=0, l=0, r=0), paper_bgcolor='rgba(0,0,0,0)')
                    st.plotly_chart(fig_market, use_container_width=True)
            with col_pie2:
                broker_summary = df_raw.groupby("券商").agg({"市值(TWD)": "sum"}).reset_index()
                if not broker_summary.empty and broker_summary["市值(TWD)"].sum() > 0:
                    fig_broker = px.pie(broker_summary, values='市值(TWD)', names='券商', hole=0.4, title="依券商/平台")
                    fig_broker.update_layout(margin=dict(t=30, b=0, l=0, r=0), paper_bgcolor='rgba(0,0,0,0)')
                    st.plotly_chart(fig_broker, use_container_width=True)

            st.markdown("---")
            
            df_hist_plot = load_history()
            if not df_hist_plot.empty and len(df_hist_plot) > 0 and "淨資產(TWD)" in df_hist_plot.columns:
                st.subheader("📈 淨資產成長趨勢 (總覽)")
                fig_line = px.line(df_hist_plot, x="紀錄日期", y=["總資產(TWD)", "淨資產(TWD)", "總負債(TWD)"], markers=True,
                                   color_discrete_map={"總資產(TWD)": "#1f77b4", "淨資產(TWD)": "#00FF7F", "總負債(TWD)": "#ff7f0e"})
                fig_line.update_layout(margin=dict(t=20, b=0, l=0, r=0), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', legend_title_text='')
                st.plotly_chart(fig_line, use_container_width=True)
                st.markdown("---")
            
            st.subheader(f"🚀 總淨資產 FIRE 目標進度 (目標：{fire_goal_total / 100000000:.1f} 億)")
            progress = min(max(net_worth / fire_goal_total, 0), 1.0) if fire_goal_total > 0 else 1.0
            st.progress(progress)
            st.write(f"目前達成率：**{progress*100:.2f}%**")
            st.markdown("---")

            # --- 分頁與市場專屬資訊 ---
            st.subheader("📋 各市場專屬儀表板與明細清單")
            tab_tw, tab_us, tab_jp, tab_fund, tab_liab = st.tabs(["🇹🇼 台股", "🇺🇸 美股", "🇯🇵 日股", "📈 基金", "📉 負債"])
            
            def render_market_tab(market_name, df_market, target_goal, hist_col):
                if df_market.empty:
                    st.info(f"目前尚無{market_name}資料。")
                    return
                
                subtotal = df_market["市值(TWD)"].sum()
                
                col_m1, col_m2 = st.columns([1, 1])
                with col_m1:
                    st.metric(f"**{market_name} 總計 (TWD)**", f"${subtotal:,.0f}")
                with col_m2:
                    m_progress = min(max(subtotal / target_goal, 0), 1.0) if target_goal > 0 else 1.0
                    st.write(f"🎯 **目標達成率：{m_progress*100:.2f}%** (目標 ${target_goal:,.0f})")
                    st.progress(m_progress)

                # 🌟 專屬圓餅圖 (取代柏拉圖)
                col_p1, col_p2 = st.columns([1, 1])
                with col_p1:
                    df_plot = df_market.groupby("標的名稱")["市值(TWD)"].sum().reset_index()
                    if not df_plot.empty:
                        fig_pie = px.pie(df_plot, values='市值(TWD)', names='標的名稱', title=f"{market_name} 各股資金佔比", hole=0.3)
                        fig_pie.update_layout(margin=dict(t=30, b=0, l=0, r=0), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                        st.plotly_chart(fig_pie, use_container_width=True)
                
                # 🌟 專屬歷史趨勢圖
                with col_p2:
                    if not df_hist_plot.empty and hist_col in df_hist_plot.columns:
                        fig_hist = px.line(df_hist_plot, x="紀錄日期", y=hist_col, markers=True, title=f"{market_name} 成長趨勢")
                        fig_hist.update_layout(margin=dict(t=30, b=0, l=0, r=0), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                        st.plotly_chart(fig_hist, use_container_width=True)
                
                # 明細表
                df_display = df_market.copy()
                df_display["現價"] = df_display["現價"].apply(lambda x: f"{float(x):.2f}" if x != "-" else x)
                df_display["市值(TWD)"] = df_display["市值(TWD)"].map(lambda x: f"{x:,.0f}")
                df_display["殖利率"] = df_display["殖利率"].map(lambda x: f"{x*100:.2f}%")
                df_display["年配息(TWD)"] = df_display["年配息(TWD)"].map(lambda x: f"{x:,.0f}")
                st.dataframe(df_display, use_container_width=True)

            with tab_tw: render_market_tab("台股", df_raw[df_raw["市場"] == "台股"], fire_goal_tw, "台股總計")
            with tab_us: render_market_tab("美股", df_raw[df_raw["市場"] == "美股"], fire_goal_us, "美股總計")
            with tab_jp: render_market_tab("日股", df_raw[df_raw["市場"] == "日股"], fire_goal_jp, "日股總計")
            with tab_fund: render_market_tab("基金", df_raw[df_raw["市場"] == "基金"], fire_goal_fund, "基金總計")
            
            with tab_liab:
                st.info("📉 您的負債清單")
                if not df_liab.empty:
                    st.markdown(f"**負債總計：** `${total_liabilities:,.0f}` TWD")
                    df_liab_display = df_liab.copy()
                    df_liab_display["目前餘額(TWD)"] = df_liab_display["目前餘額(TWD)"].map(lambda x: f"{x:,.0f}")
                    st.dataframe(df_liab_display, use_container_width=True)
                else:
                    st.success("太棒了！您目前沒有任何負債。")

        except Exception as e:
            st.error(f"計算發生錯誤。詳細錯誤: {e}")