import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import os # 新增：用來檢查檔案是否存在的內建工具

st.set_page_config(page_title="RetireFlow 退休資產戰情室", layout="wide")

# --- 檔案儲存設定 ---
DATA_FILE = "portfolio.csv" # 我們的資料庫檔名

# 載入資料的函數
def load_data():
    if os.path.exists(DATA_FILE):
        # 如果檔案存在，就讀取它
        return pd.read_csv(DATA_FILE)
    else:
        # 如果是第一次用（沒有檔案），就給預設值
        return pd.DataFrame({
            "市場": ["永豐", "玉山","台股", "美股", "日股"],
            "代號": ["2330", "0050", "VT", "7203"],
            "股數": [1000, 2000, 50, 100]
        })

# 儲存資料的函數
def save_data(df):
    df.to_csv(DATA_FILE, index=False) # 存成 csv 檔，不保留索引號碼

# --- 側邊欄：設定退休目標 ---
st.sidebar.header("🎯 退休目標設定")
fire_goal = st.sidebar.number_input("目標資產 (TWD)", value=20000000, step=1000000)

# --- 主畫面：持股清單編輯器 ---
st.title("📊 RetireFlow 退休資產戰情室 (自動存檔版)")
st.markdown("### 跨市場複委託管理系統")

st.info("💡 **操作提示：** 在下方表格修改完持股後，請記得點擊「💾 儲存清單」，下次打開就不必重填囉！")

# 讀取現有資料
current_portfolio = load_data()

# 產生互動式表格
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

# --- 新增：儲存按鈕 ---
if st.button("💾 儲存目前的持股清單"):
    save_data(edited_portfolio)
    st.success("✅ 儲存成功！這份清單已經安穩地存在你的電腦裡了。")

# --- 核心邏輯：轉換代號並抓取資料 ---
@st.cache_data(ttl=600)
def get_market_data(portfolio_df):
    yf_tickers = []
    for index, row in portfolio_df.iterrows():
        market = row["市場"]
        symbol = str(row["代號"]).upper().strip()
        if market == "台股":
            yf_tickers.append(f"{symbol}.TW")
        elif market == "日股":
            yf_tickers.append(f"{symbol}.T")
        else: 
            yf_tickers.append(symbol)

    yf_tickers.extend(["TWD=X", "JPYTWD=X"])
    unique_tickers = list(set(yf_tickers))
        
    data = yf.download(unique_tickers, period="1d")['Close'].iloc[-1]
    usd_twd = data.get('TWD=X', 32.0)
    jpy_twd = data.get('JPYTWD=X', 0.22)
    if pd.isna(jpy_twd): jpy_twd = 0.22
    if pd.isna(usd_twd): usd_twd = 32.0

    return data, usd_twd, jpy_twd

st.markdown("---")

# --- 結算按鈕 ---
if st.button("🔄 結算最新資產總值", type="primary", use_container_width=True):
    with st.spinner('正在連線至全球交易所抓取最新報價... (可能需要幾秒鐘)'):
        try:
            market_data, usd_twd, jpy_twd = get_market_data(edited_portfolio)
            
            results = []
            total_tw, total_us, total_jp = 0, 0, 0
            
            for index, row in edited_portfolio.iterrows():
                market = row["市場"]
                symbol = str(row["代號"]).upper().strip()
                shares = row["股數"]
                
                if market == "台股":
                    price = market_data.get(f"{symbol}.TW", 0)
                    if pd.isna(price): price = 0
                    value = price * shares
                    total_tw += value
                    results.append([market, symbol, shares, price, 1.0, value])
                    
                elif market == "美股":
                    price = market_data.get(symbol, 0)
                    if pd.isna(price): price = 0
                    value = price * shares * usd_twd
                    total_us += value
                    results.append([market, symbol, shares, price, usd_twd, value])
                    
                elif market == "日股":
                    price = market_data.get(f"{symbol}.T", 0)
                    if pd.isna(price): price = 0
                    value = price * shares * jpy_twd
                    total_jp += value
                    results.append([market, symbol, shares, price, jpy_twd, value])

            total_value = total_tw + total_us + total_jp
            
            # --- 顯示主要指標 ---
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("總資產 (TWD)", f"${total_value:,.0f}")
            col2.metric("台股總計", f"${total_tw:,.0f}")
            col3.metric("美股總計", f"${total_us:,.0f}", f"匯率 {usd_twd:.2f}")
            col4.metric("日股總計", f"${total_jp:,.0f}", f"匯率 {jpy_twd:.2f}")
            
            st.markdown("---")

            # --- 圖表與進度 ---
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

            # --- 詳細清單表格 ---
            st.subheader("📋 投資組合最新明細")
            result_df = pd.DataFrame(results, columns=["市場", "代號", "股數", "現價(原幣)", "匯率", "台幣市值(TWD)"])
            
            # 格式化數字顯示
            result_df["現價(原幣)"] = result_df["現價(原幣)"].map(lambda x: f"{x:.2f}")
            result_df["匯率"] = result_df["匯率"].map(lambda x: f"{x:.4f}")
            result_df["台幣市值(TWD)"] = result_df["台幣市值(TWD)"].map(lambda x: f"{x:,.0f}")
            
            st.dataframe(result_df, use_container_width=True)

        except Exception as e:
            st.error(f"資料計算發生錯誤，請確認輸入的股票代號是否皆正確。詳細錯誤: {e}")