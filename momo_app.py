import random
import re
import time

import pandas as pd
import plotly.express as px
import streamlit as st
from curl_cffi import requests

# ----------------------------------------------------------------------
# 基本設定
# ----------------------------------------------------------------------
st.set_page_config(page_title="MOMO 商品價格分析", page_icon="🛒", layout="wide")

API_URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HOME_URL = "https://www.momoshop.com.tw/"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}

PRICE_BINS = [0, 500, 1000, 1500, 2000, 3000, 5000, float("inf")]
PRICE_LABELS = [
    "0~500",
    "501~1,000",
    "1,001~1,500",
    "1,501~2,000",
    "2,001~3,000",
    "3,001~5,000",
    "5,001以上",
]


# ----------------------------------------------------------------------
# 爬蟲 (CODE01)
# ----------------------------------------------------------------------
def build_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


def parse_price(raw) -> int | None:
    """把 '$1,273'、'1273' 之類的字串轉成整數，失敗則回傳 None。"""
    digits = re.sub(r"[^\d]", "", str(raw))
    return int(digits) if digits else None


@st.cache_data(show_spinner=False, ttl=60 * 30)
def crawl_momo(keyword: str, pages: int) -> tuple[pd.DataFrame, list[str]]:
    """爬取 1~pages 頁，回傳 (DataFrame, 錯誤訊息列表)。"""
    rows, errors = [], []
    session = requests.Session(impersonate="chrome")  # 模擬 Chrome TLS 指紋
    session.get(HOME_URL, headers=HEADERS)  # 先取得 cookie

    for page in range(1, pages + 1):
        try:
            resp = session.post(API_URL, headers=HEADERS, json=build_payload(keyword, page))
            if resp.status_code != 200:
                errors.append(f"第 {page} 頁：HTTP {resp.status_code}")
                continue
            goods = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
            if not goods:
                errors.append(f"第 {page} 頁：沒有資料（可能已超過最後一頁）")
                break
            for g in goods:
                rows.append(
                    {
                        "頁數": page,
                        "品名": g.get("goodsName", ""),
                        "價格": parse_price(g.get("goodsPrice", "")),
                    }
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"第 {page} 頁：{e}")
        time.sleep(random.uniform(0.8, 1.6))  # 禮貌性延遲，降低被擋機率

    df = pd.DataFrame(rows, columns=["頁數", "品名", "價格"])
    df = df.dropna(subset=["價格"]).reset_index(drop=True)
    df["價格"] = df["價格"].astype(int)
    return df, errors


# ----------------------------------------------------------------------
# 資料處理
# ----------------------------------------------------------------------
def extract_brand(name: str) -> str:
    """momo 品名多半是「【品牌】商品名稱」，抓出品牌。"""
    m = re.search(r"【(.+?)】", name)
    return m.group(1).strip() if m else "未標示品牌"


def add_features(df: pd.DataFrame, top_n_brands: int = 8) -> pd.DataFrame:
    df = df.copy()
    df["價格區間"] = pd.cut(
        df["價格"], bins=PRICE_BINS, labels=PRICE_LABELS, right=True, include_lowest=True
    ).astype(str)
    df["品牌"] = df["品名"].apply(extract_brand)
    top = df["品牌"].value_counts().head(top_n_brands).index
    df["品牌"] = df["品牌"].where(df["品牌"].isin(top), "其他品牌")
    return df


# ----------------------------------------------------------------------
# 介面
# ----------------------------------------------------------------------
st.title("🛒 MOMO 購物網商品價格分析")
st.caption("輸入商品關鍵字與要爬取的頁數，自動產生折線圖、圓餅圖與旭日圖。")

with st.sidebar:
    st.header("搜尋條件")
    with st.form("search_form"):
        keyword = st.text_input("產品名稱", value="行動電源")
        pages = st.number_input("爬取頁數", min_value=1, max_value=10, value=2, step=1)
        top_n = st.slider("旭日圖顯示前幾大品牌", 3, 15, 8)
        submitted = st.form_submit_button("開始爬取", type="primary", use_container_width=True)

if submitted:
    if not keyword.strip():
        st.warning("請輸入產品名稱")
    else:
        with st.spinner(f"正在爬取「{keyword}」前 {pages} 頁…"):
            df_raw, errs = crawl_momo(keyword.strip(), int(pages))
        st.session_state["result"] = (keyword.strip(), df_raw, errs, top_n)

if "result" not in st.session_state:
    st.info("請在左側輸入條件後按「開始爬取」。")
    st.stop()

kw, df_raw, errs, top_n = st.session_state["result"]

for e in errs:
    st.warning(e)

if df_raw.empty:
    st.error("沒有取得任何資料，可能被網站阻擋或關鍵字無結果，請稍後再試。")
    st.stop()

df = add_features(df_raw, top_n_brands=top_n)
mean_price = df["價格"].mean()

# ---- 統計指標 ----
c1, c2, c3, c4 = st.columns(4)
c1.metric("商品數量", f"{len(df):,}")
c2.metric("平均價格", f"${mean_price:,.0f}")
c3.metric("最高價格", f"${df['價格'].max():,}")
c4.metric("最低價格", f"${df['價格'].min():,}")

tab_line, tab_pie, tab_sun, tab_data = st.tabs(["📈 折線圖", "🥧 圓餅圖", "☀️ 旭日圖", "📋 資料表"])

# ---- 折線圖 ----
with tab_line:
    fig_line = px.line(
        df,
        x=df.index,
        y="價格",
        hover_data={"品名": True, "頁數": True},
        markers=True,
        title=f"MOMO 電商網站上「{kw}」售價",
    )
    fig_line.add_hline(
        y=mean_price,
        line_dash="dash",
        line_color="red",
        annotation_text=f"平均 {mean_price:,.0f}",
        annotation_position="top left",
    )
    fig_line.update_layout(xaxis_title="商品序號 (store id)", yaxis_title="價格 (元)", height=550)
    st.plotly_chart(fig_line, use_container_width=True)

# ---- 圓餅圖 ----
with tab_pie:
    pie_df = (
        df["價格區間"]
        .value_counts()
        .reindex(PRICE_LABELS, fill_value=0)
        .rename_axis("價格區間")
        .reset_index(name="商品數量")
    )
    pie_df = pie_df[pie_df["商品數量"] > 0]
    fig_pie = px.pie(
        pie_df,
        names="價格區間",
        values="商品數量",
        title=f"「{kw}」價格區間分布",
        category_orders={"價格區間": PRICE_LABELS},
        hole=0.3,
    )
    fig_pie.update_traces(textinfo="label+percent")
    fig_pie.update_layout(height=550)
    st.plotly_chart(fig_pie, use_container_width=True)

# ---- 旭日圖 ----
with tab_sun:
    # px.sunburst 不支援 category_orders，改成先依價格區間排序，再關閉自動排序
    sun_df = df.copy()
    sun_df["_order"] = sun_df["價格區間"].map({l: i for i, l in enumerate(PRICE_LABELS)})
    sun_df = sun_df.sort_values("_order").drop(columns="_order")
    fig_sun = px.sunburst(
        sun_df,
        path=["價格區間", "品牌"],
        title=f"「{kw}」價格區間 × 品牌",
    )
    fig_sun.update_traces(
        textinfo="label+value", insidetextorientation="radial", sort=False
    )
    fig_sun.update_layout(height=650)
    st.plotly_chart(fig_sun, use_container_width=True)
    st.caption("品牌取自品名中【】內的文字；未標示者歸為「未標示品牌」，排名之外歸為「其他品牌」。")

# ---- 資料表 / 下載 ----
with tab_data:
    st.dataframe(df[["頁數", "品名", "價格", "價格區間", "品牌"]], use_container_width=True)
    st.download_button(
        "下載 CSV",
        data=df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=f"MOMO_{kw}_{time.strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
