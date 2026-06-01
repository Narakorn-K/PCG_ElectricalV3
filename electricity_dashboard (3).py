import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
from datetime import datetime
from urllib.parse import quote
import sys

def fmt_day(dt, show_year=True):
    if sys.platform == 'win32':
        return dt.strftime('%#d %b %Y') if show_year else dt.strftime('%#d %b')
    return dt.strftime('%-d %b %Y') if show_year else dt.strftime('%-d %b')

def fmt_day_short(dt):
    return fmt_day(dt, show_year=False)

st.set_page_config(page_title="Energy Dashboard", layout="wide", page_icon="⚡")

SHEET_ID = "1Ym2yfzkLTyLTtJtLZSSgWoeew_IPWUaI_u6d45jKUnw"
SHEET_NAME = "Daily"
SHEET_TON = "Product Ton"

ON_PEAK_RATE  = 4.1824
OFF_PEAK_RATE = 2.6369
FT_ADJ        = 0.1623

DAY_TH = {"อา": 6, "จ": 0, "อ": 1, "พ": 2, "พฤ": 3, "ศ": 4, "ส": 5}
MONTH_TH = {
    1: "ม.ค.", 2: "ก.พ.", 3: "มี.ค.", 4: "เม.ย.",
    5: "พ.ค.", 6: "มิ.ย.", 7: "ก.ค.", 8: "ส.ค.",
    9: "ก.ย.", 10: "ต.ค.", 11: "พ.ย.", 12: "ธ.ค.",
}

st.markdown("""
<style>
.kpi-card {
    background: var(--bg, #fff);
    border: 1px solid #e8eaf0;
    border-radius: 12px;
    padding: 16px 18px 12px;
    text-align: center;
    border-top: 4px solid #1565c0;
}
.kpi-label { font-size: 12px; color: #666; font-weight: 600; text-transform: uppercase;
             letter-spacing: 0.5px; margin-bottom: 4px; }
.kpi-value { font-size: 22px; font-weight: 800; color: #1a237e; line-height: 1.2; }
.kpi-unit  { font-size: 13px; font-weight: 400; }
.kpi-sub   { font-size: 12px; color: #999; margin-top: 4px; }
.kpi-pct-up   { color: #e53935; font-weight: 700; font-size: 13px; }
.kpi-pct-down { color: #43a047; font-weight: 700; font-size: 13px; }
.summary-box {
    background: #f8f9ff;
    border-left: 4px solid #1565c0;
    border-radius: 0 8px 8px 0;
    padding: 12px 20px;
    margin-top: 8px;
    font-size: 14px;
    line-height: 1.9;
    color: #333;
}
.section-title {
    font-size: 16px; font-weight: 700; color: #1a237e;
    border-left: 4px solid #1565c0; padding-left: 10px;
    margin: 24px 0 12px;
}
</style>
""", unsafe_allow_html=True)


def parse_date_col(raw_val, fallback_year=2026):
    match = re.match(r"(\d{2}/\d{2})", str(raw_val))
    if not match:
        return None, None
    date_str = match.group(1)
    d, m = map(int, date_str.split("/"))
    for yr in [fallback_year, fallback_year - 1, datetime.now().year]:
        try:
            dt = datetime(yr, m, d)
            day_match = re.search(r"\((.+?)\)", str(raw_val))
            wd = DAY_TH.get(day_match.group(1), dt.weekday()) if day_match else dt.weekday()
            return dt, wd
        except ValueError:
            continue
    return None, None


def diff_badge(pct):
    if pct > 0:
        return f'<span class="kpi-pct-up">▲ {abs(pct):.1f}%</span>'
    elif pct < 0:
        return f'<span class="kpi-pct-down">▼ {abs(pct):.1f}%</span>'
    return '<span style="color:#999;font-size:13px;">— 0%</span>'


def diff_text(pct, label_up="เพิ่มขึ้น", label_down="ลดลง"):
    arrow = "▲" if pct >= 0 else "▼"
    color = "#e53935" if pct >= 0 else "#43a047"
    word  = label_up if pct >= 0 else label_down
    return f'<span style="color:{color};font-weight:700;">{arrow} {word} {abs(pct):.1f}%</span>'


@st.cache_data(ttl=300)
def load_all_bytes():
    import urllib.request
    BASE_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
    try:
        req  = urllib.request.Request(BASE_URL, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=60).read()
    except Exception as e:
        st.error(f"❌ ดึงข้อมูลไม่ได้: {e}")
        st.stop()
    return data


@st.cache_data(ttl=300)
def load_data():
    import io
    xls = pd.ExcelFile(io.BytesIO(load_all_bytes()))
    try:
        raw = xls.parse(SHEET_NAME, header=None)
    except Exception as e:
        st.error(f"❌ ไม่พบ Sheet '{SHEET_NAME}': {e}")
        st.stop()

    header_row = 0
    for r in range(min(6, raw.shape[0])):
        if raw.iloc[r, :].astype(str).str.contains(r"\d{2}/\d{2}", regex=True).any():
            header_row = r
            break

    data_start_row = header_row + 2
    fallback_year  = datetime.now().year

    date_cols = []
    for i in range(4, raw.shape[1]):
        val = raw.iloc[header_row, i]
        if pd.notna(val):
            dt, wd = parse_date_col(str(val), fallback_year)
            if dt:
                date_cols.append({"col_idx": i, "date": dt, "weekday": wd})

    if not date_cols:
        st.error("❌ ไม่พบคอลัมน์วันที่")
        st.stop()

    records = []
    for row_i in range(data_start_row, raw.shape[0]):
        meter  = raw.iloc[row_i, 0]
        group  = raw.iloc[row_i, 2]
        subgrp = raw.iloc[row_i, 3]
        if pd.isna(meter) or pd.isna(group):
            continue
        if str(group).strip() in ("nan", ""):
            continue
        for dc in date_cols:
            ci  = dc["col_idx"]
            on  = pd.to_numeric(raw.iloc[row_i, ci],     errors="coerce") if ci     < raw.shape[1] else 0
            off = pd.to_numeric(raw.iloc[row_i, ci + 1], errors="coerce") if ci + 1 < raw.shape[1] else 0
            tot = pd.to_numeric(raw.iloc[row_i, ci + 2], errors="coerce") if ci + 2 < raw.shape[1] else 0
            records.append({
                "meter":      str(meter),
                "department": str(group).strip(),
                "sub_group":  str(subgrp).strip(),
                "date":       dc["date"],
                "weekday":    dc["weekday"],
                "on_peak":    float(on)  if pd.notna(on)  else 0.0,
                "off_peak":   float(off) if pd.notna(off) else 0.0,
                "total":      float(tot) if pd.notna(tot) else 0.0,
            })

    if not records:
        st.error("❌ ไม่พบแถวข้อมูล")
        st.stop()

    df = pd.DataFrame(records)
    df["date"]      = pd.to_datetime(df["date"])
    df["week_num"]  = df["date"].dt.isocalendar().week.astype(int)
    df["year"]      = df["date"].dt.isocalendar().year.astype(int)
    df["year_week"] = df["year"].astype(str) + "-W" + df["week_num"].astype(str).str.zfill(2)
    df["month"]     = df["date"].dt.month
    df["ym"]        = df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2)
    return df


@st.cache_data(ttl=300)
def load_ton_data():
    import io
    xls = pd.ExcelFile(io.BytesIO(load_all_bytes()))
    try:
        ton = xls.parse(SHEET_TON, header=0)
    except Exception as e:
        st.warning(f"⚠️ ไม่พบ Sheet '{SHEET_TON}': {e}")
        return pd.DataFrame(columns=["date", "ton"])

    ton.columns = ["date", "ton"] + list(ton.columns[2:])
    ton = ton[["date", "ton"]].copy()
    ton["date"] = pd.to_datetime(ton["date"], dayfirst=True, errors="coerce")
    ton["ton"]  = pd.to_numeric(ton["ton"], errors="coerce")
    ton = ton.dropna(subset=["date", "ton"])
    ton["week_num"]  = ton["date"].dt.isocalendar().week.astype(int)
    ton["year"]      = ton["date"].dt.isocalendar().year.astype(int)
    ton["year_week"] = ton["year"].astype(str) + "-W" + ton["week_num"].astype(str).str.zfill(2)
    ton["month"]     = ton["date"].dt.month
    ton["ym"]        = ton["year"].astype(str) + "-" + ton["month"].astype(str).str.zfill(2)
    return ton


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚡ Energy Dashboard")
    st.markdown("---")
    if st.button("🔄 Refresh ข้อมูล", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    st.caption("📡 ดึงข้อมูลจาก Google Sheet อัตโนมัติ")
    st.caption("🔄 Auto-refresh ทุก 5 นาที")
    st.markdown("---")
    st.caption("**อัตราค่าไฟ MEA TOU**")
    st.caption(f"• On Peak  : {ON_PEAK_RATE + FT_ADJ:.4f} ฿/kWh")
    st.caption(f"• Off Peak : {OFF_PEAK_RATE + FT_ADJ:.4f} ฿/kWh")
    st.caption(f"• Ft Surcharge : {FT_ADJ} ฿/kWh")

with st.spinner("⏳ กำลังดึงข้อมูล..."):
    df  = load_data()
    ton = load_ton_data()

tab_weekly, tab_monthly = st.tabs(["📋 รายสัปดาห์", "📅 รายเดือน"])


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def pct_diff(cur, prev):
    return (cur - prev) / prev * 100 if prev else 0.0


def build_kpi_card(label, value, unit, sub, pct, accent_color="#1565c0"):
    badge = diff_badge(pct)
    return f"""
<div class="kpi-card" style="border-top-color:{accent_color}">
    <div class="kpi-label">{label}</div>
    <div class="kpi-value">{value} <span class="kpi-unit">{unit}</span></div>
    <div class="kpi-sub">{sub}</div>
    <div style="margin-top:6px">{badge}</div>
</div>"""


def agg_kwh(data, period_col, period_val, dept=None):
    sub = data[data[period_col] == period_val]
    if dept and dept != "🏭 ทั้งโรงงาน":
        sub = sub[sub["department"] == dept]
    return sub[["on_peak", "off_peak"]].sum()


def agg_ton(ton_df, period_col, period_val):
    if ton_df.empty:
        return 0.0
    return float(ton_df[ton_df[period_col] == period_val]["ton"].sum())


def dept_agg(data, period_col, period_val):
    sub = data[data[period_col] == period_val]
    g = sub.groupby("department")[["on_peak", "off_peak"]].sum()
    g["total"] = g["on_peak"] + g["off_peak"]
    return g.sort_values("total", ascending=False)


def make_kpt_chart(cur_label, prev_label,
                   cur_ton, prev_ton,
                   cur_kwh, prev_kwh,
                   title=""):
    cur_kpt  = cur_kwh  / cur_ton  if cur_ton  > 0 else 0
    prev_kpt = prev_kwh / prev_ton if prev_ton > 0 else 0
    x = [f"ก่อนหน้า\n({prev_label})", f"ปัจจุบัน\n({cur_label})"]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        name="Ton ผลิต", x=x, y=[prev_ton, cur_ton],
        marker_color=["#90caf9", "#1565c0"],
        text=[f"{v:,.1f} T" for v in [prev_ton, cur_ton]],
        textposition="inside", insidetextanchor="middle",
        textfont=dict(color="white", size=13),
    ), secondary_y=False)

    if cur_kpt > 0 or prev_kpt > 0:
        fig.add_trace(go.Scatter(
            name="kWh/Ton", x=x, y=[prev_kpt, cur_kpt],
            mode="lines+markers+text",
            line=dict(color="#e65100", width=3),
            marker=dict(size=10, color="#e65100"),
            text=[f"{v:,.2f}" for v in [prev_kpt, cur_kpt]],
            textposition="top center",
            textfont=dict(size=14, color="#e65100"),
        ), secondary_y=True)

    fig.update_layout(
        title_text=title, title_font_size=14,
        height=300, barmode="group",
        legend=dict(orientation="h", y=1.15, x=1, xanchor="right"),
        margin=dict(t=50, b=10, l=10, r=50),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    fig.update_yaxes(title_text="Ton", gridcolor="#f0f0f0", secondary_y=False)
    fig.update_yaxes(title_text="kWh/Ton", showgrid=False, secondary_y=True)
    return fig


def summary_html(cur_kwh, prev_kwh, cur_ton, prev_ton, period_name="สัปดาห์ที่แล้ว"):
    cur_kpt  = cur_kwh  / cur_ton  if cur_ton  > 0 else None
    prev_kpt = prev_kwh / prev_ton if prev_ton > 0 else None

    pct_kwh = pct_diff(cur_kwh, prev_kwh)
    pct_ton = pct_diff(cur_ton, prev_ton)
    pct_kpt = pct_diff(cur_kpt, prev_kpt) if (cur_kpt and prev_kpt) else None

    kpt_line = ""
    if cur_kpt is not None:
        kpt_str = diff_text(pct_kpt) if pct_kpt is not None else ""
        kpt_line = f"• Unit ต่อตัน <b>{cur_kpt:,.2f} kWh/Ton</b> &nbsp; {kpt_str}<br>"

    ton_str = diff_text(pct_ton) if cur_ton > 0 else '<span style="color:#999">ไม่มีข้อมูล Ton</span>'

    return f"""
<div class="summary-box">
    • Total Energy <b>{cur_kwh:,.0f} kWh</b> &nbsp; {diff_text(pct_kwh)} vs {period_name}<br>
    {kpt_line}
    • Production <b>{cur_ton:,.1f} Ton</b> &nbsp; {ton_str} vs {period_name}
</div>"""


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — รายสัปดาห์
# ══════════════════════════════════════════════════════════════════════════════
with tab_weekly:

    all_weeks = sorted(df["year_week"].unique().tolist())

    def week_label(yw):
        sub = df[df["year_week"] == yw]["date"]
        if sub.empty:
            return yw
        s, e = sub.min(), sub.max()
        return f"{fmt_day_short(s)} – {fmt_day(e)}" if s.month != e.month else f"{s.day} – {fmt_day(e)}"

    # ── Selectors ─────────────────────────────────────────────────────────────
    col_s1, col_s2, col_s3 = st.columns([2, 2, 2])
    with col_s1:
        yw_options     = all_weeks
        yw_labels      = [f"{yw}  ({week_label(yw)})" for yw in yw_options]
        default_w_idx  = len(yw_options) - 1
        sel_display    = st.selectbox("📅 เลือกสัปดาห์", yw_labels, index=default_w_idx, key="w_week")
        sel_yw         = yw_options[yw_labels.index(sel_display)]
        sel_idx        = yw_options.index(sel_yw)
        prev_yw        = yw_options[sel_idx - 1] if sel_idx > 0 else None

    with col_s2:
        departments    = sorted(df["department"].unique().tolist())
        dept_options   = ["🏭 ทั้งโรงงาน"] + departments
        sel_dept       = st.selectbox("🏭 เลือกแผนก", dept_options, index=0, key="w_dept")

    sel_lbl  = week_label(sel_yw)
    prev_lbl = week_label(prev_yw) if prev_yw else "N/A"

    st.markdown(f"### ⚡ สัปดาห์ {sel_yw} &nbsp;|&nbsp; {sel_lbl}")
    st.markdown("---")

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    cur_e   = agg_kwh(df, "year_week", sel_yw,  sel_dept)
    prev_e  = agg_kwh(df, "year_week", prev_yw, sel_dept) if prev_yw else pd.Series({"on_peak": 0, "off_peak": 0})
    cur_ton  = agg_ton(ton, "year_week", sel_yw)
    prev_ton = agg_ton(ton, "year_week", prev_yw) if prev_yw else 0.0

    cur_on   = cur_e["on_peak"];   cur_off  = cur_e["off_peak"]
    prev_on  = prev_e["on_peak"];  prev_off = prev_e["off_peak"]
    cur_tot  = cur_on  + cur_off
    prev_tot = prev_on + prev_off
    cur_cost  = cur_on  * (ON_PEAK_RATE + FT_ADJ) + cur_off  * (OFF_PEAK_RATE + FT_ADJ)
    prev_cost = prev_on * (ON_PEAK_RATE + FT_ADJ) + prev_off * (OFF_PEAK_RATE + FT_ADJ)
    cur_kpt   = cur_tot  / cur_ton  if cur_ton  > 0 else None
    prev_kpt  = prev_tot / prev_ton if prev_ton > 0 else None
    on_pct    = cur_on  / cur_tot * 100 if cur_tot else 0
    off_pct   = cur_off / cur_tot * 100 if cur_tot else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    cards = [
        (c1, "Production Ton", f"{cur_ton:,.1f}", "T",
         "", pct_diff(cur_ton, prev_ton), "#00838f"),
        (c2, "Total Energy", f"{cur_tot:,.0f}", "kWh",
         f"vs ก่อน {prev_tot:,.0f}", pct_diff(cur_tot, prev_tot), "#1565c0"),
        (c3, "On Peak", f"{cur_on:,.0f}", "kWh",
         f"สัดส่วน {on_pct:.1f}%", pct_diff(cur_on, prev_on), "#e65100"),
        (c4, "Off Peak", f"{cur_off:,.0f}", "kWh",
         f"สัดส่วน {off_pct:.1f}%", pct_diff(cur_off, prev_off), "#2e7d32"),
        (c5, "ค่าไฟโดยประมาณ", f"{cur_cost:,.0f}", "฿",
         "อัตรา TOU + Ft", pct_diff(cur_cost, prev_cost), "#6a1b9a"),
        (c6, "kWh / Ton",
         f"{cur_kpt:,.2f}" if cur_kpt else "N/A", "",
         f"ก่อน {prev_kpt:.2f}" if prev_kpt else "ไม่มีข้อมูล Ton",
         pct_diff(cur_kpt, prev_kpt) if (cur_kpt and prev_kpt) else 0, "#00897b"),
    ]
    for col, label, val, unit, sub, pct, color in cards:
        with col:
            st.markdown(build_kpi_card(label, val, unit, sub, pct, color), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Block 1: Factory รวม ──────────────────────────────────────────────────
    st.markdown('<div class="section-title">📊 kWh/Ton — ทั้งโรงงาน (Factory)</div>', unsafe_allow_html=True)

    prev_tot_all  = (agg_kwh(df, "year_week", prev_yw)["on_peak"]  +
                     agg_kwh(df, "year_week", prev_yw)["off_peak"]) if prev_yw else 0
    cur_tot_all   = cur_e["on_peak"] + cur_e["off_peak"]

    # Use factory-wide ton (not dept-filtered) for factory block
    fig_factory = make_kpt_chart(
        sel_lbl, prev_lbl,
        cur_ton, prev_ton,
        cur_tot_all, prev_tot_all,
        title="Ton ผลิต vs kWh/Ton — ทั้งโรงงาน",
    )
    st.plotly_chart(fig_factory, use_container_width=True)
    st.markdown(summary_html(cur_tot_all, prev_tot_all, cur_ton, prev_ton), unsafe_allow_html=True)

    # ── Block 2+: แยกแผนก ────────────────────────────────────────────────────
    st.markdown('<div class="section-title">🏭 kWh/Ton — รายแผนก (เรียงจากใช้ไฟมากสุด)</div>',
                unsafe_allow_html=True)

    cur_dept_agg  = dept_agg(df, "year_week", sel_yw)
    prev_dept_agg = dept_agg(df, "year_week", prev_yw) if prev_yw else pd.DataFrame()

    # filter by sel_dept if not factory-wide
    if sel_dept != "🏭 ทั้งโรงงาน":
        dept_list = [sel_dept]
    else:
        dept_list = cur_dept_agg.index.tolist()

    for dept in dept_list:
        if dept not in cur_dept_agg.index:
            continue
        c_row = cur_dept_agg.loc[dept]
        p_row = prev_dept_agg.loc[dept] if (not prev_dept_agg.empty and dept in prev_dept_agg.index) else None

        c_kwh = c_row["total"]
        p_kwh = p_row["total"] if p_row is not None else 0

        st.markdown(f"**{dept}**")
        fig_d = make_kpt_chart(
            sel_lbl, prev_lbl,
            cur_ton, prev_ton,
            c_kwh, p_kwh,
            title=f"{dept}",
        )
        st.plotly_chart(fig_d, use_container_width=True)
        st.markdown(summary_html(c_kwh, p_kwh, cur_ton, prev_ton), unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("---")
    st.caption(f"📅 {sel_yw} ({sel_lbl}) | เทียบ: {prev_yw or 'N/A'} ({prev_lbl}) | 🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — รายเดือน
# ══════════════════════════════════════════════════════════════════════════════
with tab_monthly:

    all_ym = sorted(df["ym"].unique().tolist())

    def month_label(ym):
        y, m = ym.split("-")
        return f"{MONTH_TH[int(m)]} {y}"

    # ── Selectors ─────────────────────────────────────────────────────────────
    col_s1, col_s2, col_s3 = st.columns([2, 2, 2])
    with col_s1:
        ym_labels   = [month_label(ym) for ym in all_ym]
        sel_ym_disp = st.selectbox("📅 เลือกเดือน", ym_labels, index=len(all_ym) - 1, key="m_month")
        sel_ym      = all_ym[ym_labels.index(sel_ym_disp)]
        sel_ym_idx  = all_ym.index(sel_ym)
        prev_ym     = all_ym[sel_ym_idx - 1] if sel_ym_idx > 0 else None

    with col_s2:
        m_departments  = sorted(df["department"].unique().tolist())
        m_dept_options = ["🏭 ทั้งโรงงาน"] + m_departments
        sel_m_dept     = st.selectbox("🏭 เลือกแผนก", m_dept_options, index=0, key="m_dept")

    sel_mlbl  = month_label(sel_ym)
    prev_mlbl = month_label(prev_ym) if prev_ym else "N/A"

    st.markdown(f"### ⚡ เดือน {sel_mlbl}")
    st.markdown("---")

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    cur_me   = agg_kwh(df, "ym", sel_ym,  sel_m_dept)
    prev_me  = agg_kwh(df, "ym", prev_ym, sel_m_dept) if prev_ym else pd.Series({"on_peak": 0, "off_peak": 0})
    cur_mton  = agg_ton(ton, "ym", sel_ym)
    prev_mton = agg_ton(ton, "ym", prev_ym) if prev_ym else 0.0

    cur_mon   = cur_me["on_peak"];   cur_moff  = cur_me["off_peak"]
    prev_mon  = prev_me["on_peak"];  prev_moff = prev_me["off_peak"]
    cur_mtot  = cur_mon  + cur_moff
    prev_mtot = prev_mon + prev_moff
    cur_mcost  = cur_mon  * (ON_PEAK_RATE + FT_ADJ) + cur_moff  * (OFF_PEAK_RATE + FT_ADJ)
    prev_mcost = prev_mon * (ON_PEAK_RATE + FT_ADJ) + prev_moff * (OFF_PEAK_RATE + FT_ADJ)
    cur_mkpt   = cur_mtot  / cur_mton  if cur_mton  > 0 else None
    prev_mkpt  = prev_mtot / prev_mton if prev_mton > 0 else None
    mon_pct    = cur_mon  / cur_mtot * 100 if cur_mtot else 0
    moff_pct   = cur_moff / cur_mtot * 100 if cur_mtot else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    m_cards = [
        (c1, "Production Ton", f"{cur_mton:,.1f}", "T",
         "", pct_diff(cur_mton, prev_mton), "#00838f"),
        (c2, "Total Energy", f"{cur_mtot:,.0f}", "kWh",
         f"vs ก่อน {prev_mtot:,.0f}", pct_diff(cur_mtot, prev_mtot), "#1565c0"),
        (c3, "On Peak", f"{cur_mon:,.0f}", "kWh",
         f"สัดส่วน {mon_pct:.1f}%", pct_diff(cur_mon, prev_mon), "#e65100"),
        (c4, "Off Peak", f"{cur_moff:,.0f}", "kWh",
         f"สัดส่วน {moff_pct:.1f}%", pct_diff(cur_moff, prev_moff), "#2e7d32"),
        (c5, "ค่าไฟโดยประมาณ", f"{cur_mcost:,.0f}", "฿",
         "อัตรา TOU + Ft", pct_diff(cur_mcost, prev_mcost), "#6a1b9a"),
        (c6, "kWh / Ton",
         f"{cur_mkpt:,.2f}" if cur_mkpt else "N/A", "",
         f"ก่อน {prev_mkpt:.2f}" if prev_mkpt else "ไม่มีข้อมูล Ton",
         pct_diff(cur_mkpt, prev_mkpt) if (cur_mkpt and prev_mkpt) else 0, "#00897b"),
    ]
    for col, label, val, unit, sub, pct, color in m_cards:
        with col:
            st.markdown(build_kpi_card(label, val, unit, sub, pct, color), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Block 1: Factory รวม ──────────────────────────────────────────────────
    st.markdown('<div class="section-title">📊 kWh/Ton — ทั้งโรงงาน (Factory)</div>', unsafe_allow_html=True)

    prev_mtot_all = (agg_kwh(df, "ym", prev_ym)["on_peak"] +
                     agg_kwh(df, "ym", prev_ym)["off_peak"]) if prev_ym else 0
    cur_mtot_all  = cur_me["on_peak"] + cur_me["off_peak"]

    fig_mfactory = make_kpt_chart(
        sel_mlbl, prev_mlbl,
        cur_mton, prev_mton,
        cur_mtot_all, prev_mtot_all,
        title="Ton ผลิต vs kWh/Ton — ทั้งโรงงาน",
    )
    st.plotly_chart(fig_mfactory, use_container_width=True)
    st.markdown(summary_html(cur_mtot_all, prev_mtot_all, cur_mton, prev_mton,
                              period_name="เดือนก่อน"), unsafe_allow_html=True)

    # ── Block 2+: แยกแผนก ────────────────────────────────────────────────────
    st.markdown('<div class="section-title">🏭 kWh/Ton — รายแผนก (เรียงจากใช้ไฟมากสุด)</div>',
                unsafe_allow_html=True)

    cur_mdept_agg  = dept_agg(df, "ym", sel_ym)
    prev_mdept_agg = dept_agg(df, "ym", prev_ym) if prev_ym else pd.DataFrame()

    if sel_m_dept != "🏭 ทั้งโรงงาน":
        m_dept_list = [sel_m_dept]
    else:
        m_dept_list = cur_mdept_agg.index.tolist()

    for dept in m_dept_list:
        if dept not in cur_mdept_agg.index:
            continue
        c_mrow = cur_mdept_agg.loc[dept]
        p_mrow = prev_mdept_agg.loc[dept] if (not prev_mdept_agg.empty and dept in prev_mdept_agg.index) else None

        c_mkwh = c_mrow["total"]
        p_mkwh = p_mrow["total"] if p_mrow is not None else 0

        st.markdown(f"**{dept}**")
        fig_md = make_kpt_chart(
            sel_mlbl, prev_mlbl,
            cur_mton, prev_mton,
            c_mkwh, p_mkwh,
            title=f"{dept}",
        )
        st.plotly_chart(fig_md, use_container_width=True)
        st.markdown(summary_html(c_mkwh, p_mkwh, cur_mton, prev_mton,
                                  period_name="เดือนก่อน"), unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("---")
    st.caption(f"📅 {sel_mlbl} | เทียบ: {prev_mlbl} | 🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
