import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
from datetime import datetime

st.set_page_config(page_title="Electricity Usage Overview", layout="wide")

# ─── Google Sheet Config ──────────────────────────────────────────────────────
SHEET_ID   = "1Ym2yfzkLTyLTtJtLZSSgWoeew_IPWUaI_u6d45jKUnw"
SHEET_NAME = "Clean Data"
from urllib.parse import quote
EXPORT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx&sheet={quote(SHEET_NAME)}"

# ─── Thai electricity tariff (PEA TOU rates, Baht/kWh) ───────────────────────
ON_PEAK_RATE  = 4.1824
OFF_PEAK_RATE = 2.6369
FT_ADJ        = 0.3949

# ─── Helpers ──────────────────────────────────────────────────────────────────
DAY_TH = {"อา": 6, "จ": 0, "อ": 1, "พ": 2, "พฤ": 3, "ศ": 4, "ส": 5}

def parse_date_col(raw: str):
    match = re.match(r"(\d{2}/\d{2})\n\((.+)\)", raw)
    if not match:
        return None, None
    date_str, th_day = match.group(1), match.group(2)
    d, m = map(int, date_str.split("/"))
    year = datetime.now().year
    if m > datetime.now().month + 1:
        year -= 1
    try:
        dt = datetime(year, m, d)
    except ValueError:
        return None, None
    return dt, DAY_TH.get(th_day, dt.weekday())


@st.cache_data(ttl=300)  # Cache 5 นาที แล้ว auto-refresh
def load_data_from_gsheet():
    try:
        raw = pd.read_excel(EXPORT_URL, sheet_name=SHEET_NAME, header=None)
    except Exception as e:
        st.error(f"❌ ไม่สามารถดึงข้อมูลจาก Google Sheet ได้: {e}")
        st.stop()

    # ── Auto-detect แถว header (หาแถวที่มีวันที่ dd/mm) ──────────────────────
    header_row = 0
    for r in range(min(6, raw.shape[0])):
        row_str = raw.iloc[r, :].astype(str)
        if row_str.str.contains(r"\d{2}/\d{2}", regex=True).any():
            header_row = r
            break

    data_start_row = header_row + 2  # ข้อมูลเริ่ม 2 แถวหลัง header

    # ── Auto-detect คอลัมน์วันที่ (scan ทุก column ไม่ข้ามทีละ 3) ────────────
    date_cols = []
    for i in range(4, raw.shape[1]):
        val = raw.iloc[header_row, i]
        if pd.notna(val):
            dt, wd = parse_date_col(str(val))
            if dt:
                date_cols.append({"col_idx": i, "date": dt, "weekday": wd})

    if not date_cols:
        st.error("❌ ไม่พบคอลัมน์วันที่ในข้อมูล กรุณาตรวจสอบรูปแบบ Google Sheet")
        st.stop()

    records = []
    for row_i in range(data_start_row, raw.shape[0]):
        meter  = raw.iloc[row_i, 0]
        group  = raw.iloc[row_i, 1]
        subgrp = raw.iloc[row_i, 2]
        if pd.isna(meter) or pd.isna(group):
            continue
        if str(group).strip() in ("nan", ""):
            continue
        for dc in date_cols:
            ci = dc["col_idx"]
            # ป้องกัน index เกิน
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
        st.error("❌ ดึงข้อมูลได้แต่ไม่พบแถวข้อมูล กรุณาตรวจสอบโครงสร้าง Sheet")
        st.dataframe(raw.iloc[:5, :8])   # แสดง 5 แถวแรกเพื่อ debug
        st.stop()

    df = pd.DataFrame(records)
    df["date"]      = pd.to_datetime(df["date"])
    df["week_num"]  = df["date"].dt.isocalendar().week.astype(int)
    df["year"]      = df["date"].dt.isocalendar().year.astype(int)
    df["year_week"] = df["year"].astype(str) + "-W" + df["week_num"].astype(str).str.zfill(2)
    return df


def get_complete_weeks(df):
    wk_days = df.groupby("year_week")["date"].nunique()
    return wk_days[wk_days == 7].index.tolist()


def week_agg(df, year_week, dept_filter=None):
    sub = df[df["year_week"] == year_week]
    if dept_filter and dept_filter != "🏭 Factory (ทั้งหมด)":
        sub = sub[sub["department"] == dept_filter]
    return sub[["on_peak", "off_peak", "total"]].sum()


def dept_week_agg(df, year_week):
    sub = df[df["year_week"] == year_week]
    return sub.groupby("department")[["on_peak", "off_peak", "total"]].sum().reset_index()


# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-title {
        font-size:26px; font-weight:700; text-align:center;
        color:#1a237e; margin-bottom:20px;
    }
    .kpi-card {
        background:#fff; border-radius:12px; padding:18px 22px;
        box-shadow:0 2px 10px rgba(0,0,0,0.08); text-align:center;
        border-top: 4px solid #1565c0;
    }
    .kpi-label {font-size:12px; color:#666; font-weight:600; margin-bottom:6px; text-transform:uppercase; letter-spacing:0.5px;}
    .kpi-value {font-size:26px; font-weight:800; color:#1a237e;}
    .kpi-unit  {font-size:14px; font-weight:400;}
    .kpi-sub   {font-size:12px; color:#999; margin-top:4px;}
    .kpi-on    {color:#e65100 !important;}
    .kpi-off   {color:#2e7d32 !important;}
    .kpi-cost  {color:#6a1b9a !important;}
    .up   {color:#e53935; font-weight:700;}
    .down {color:#43a047; font-weight:700;}
    .section-header {
        font-size:16px; font-weight:700; color:#1a237e;
        border-left:4px solid #1565c0; padding-left:10px;
        margin:28px 0 14px;
    }
</style>
""", unsafe_allow_html=True)

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚡ Electricity Dashboard")
    st.markdown("---")
    if st.button("🔄 Refresh ข้อมูล", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    st.caption("📡 ดึงข้อมูลจาก Google Sheet อัตโนมัติ")
    st.caption("🔄 Auto-refresh ทุก 5 นาที")
    st.markdown("---")
    st.caption("**อัตราค่าไฟ PEA TOU**")
    st.caption(f"• On Peak  : {ON_PEAK_RATE + FT_ADJ:.4f} ฿/kWh")
    st.caption(f"• Off Peak : {OFF_PEAK_RATE + FT_ADJ:.4f} ฿/kWh")
    st.caption(f"• Ft Surcharge : {FT_ADJ} ฿/kWh")

# ─── Load Data ────────────────────────────────────────────────────────────────
st.markdown('<div class="main-title">⚡ Electricity Usage Overview</div>', unsafe_allow_html=True)

with st.spinner("⏳ กำลังดึงข้อมูลจาก Google Sheet..."):
    df = load_data_from_gsheet()

complete_weeks = sorted(get_complete_weeks(df))

if len(complete_weeks) < 1:
    st.error("ไม่พบสัปดาห์ที่ครบ 7 วัน กรุณาตรวจสอบข้อมูลใน Google Sheet")
    st.stop()

latest_week = complete_weeks[-1]
prev_week   = complete_weeks[-2] if len(complete_weeks) >= 2 else None

# ─── Section 1: KPI Cards ─────────────────────────────────────────────────────
agg       = week_agg(df, latest_week)
on_kwh    = agg["on_peak"]
off_kwh   = agg["off_peak"]
total_kwh = on_kwh + off_kwh
cost      = on_kwh * (ON_PEAK_RATE + FT_ADJ) + off_kwh * (OFF_PEAK_RATE + FT_ADJ)
on_pct    = on_kwh  / total_kwh * 100 if total_kwh else 0
off_pct   = off_kwh / total_kwh * 100 if total_kwh else 0

if prev_week:
    agg_p      = week_agg(df, prev_week)
    prev_total = agg_p["on_peak"] + agg_p["off_peak"]
    chg_total  = (total_kwh - prev_total)        / prev_total        * 100 if prev_total        else 0
    chg_on     = (on_kwh    - agg_p["on_peak"])  / agg_p["on_peak"]  * 100 if agg_p["on_peak"]  else 0
    chg_off    = (off_kwh   - agg_p["off_peak"]) / agg_p["off_peak"] * 100 if agg_p["off_peak"] else 0
else:
    chg_total = chg_on = chg_off = 0

def badge(v):
    cls   = "up" if v >= 0 else "down"
    arrow = "▲" if v >= 0 else "▼"
    return f'<span class="{cls}">{arrow} {abs(v):.1f}%</span>'

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Total Energy This Week</div>
        <div class="kpi-value">{total_kwh:,.0f} <span class="kpi-unit">kWh</span></div>
        <div class="kpi-sub">สัปดาห์ {latest_week} &nbsp; {badge(chg_total)}</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""
    <div class="kpi-card" style="border-top-color:#e65100">
        <div class="kpi-label">On Peak Usage</div>
        <div class="kpi-value kpi-on">{on_kwh:,.0f} <span class="kpi-unit">kWh</span></div>
        <div class="kpi-sub">({on_pct:.0f}%) &nbsp; {badge(chg_on)}</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""
    <div class="kpi-card" style="border-top-color:#2e7d32">
        <div class="kpi-label">Off Peak Usage</div>
        <div class="kpi-value kpi-off">{off_kwh:,.0f} <span class="kpi-unit">kWh</span></div>
        <div class="kpi-sub">({off_pct:.0f}%) &nbsp; {badge(chg_off)}</div>
    </div>""", unsafe_allow_html=True)
with c4:
    st.markdown(f"""
    <div class="kpi-card" style="border-top-color:#6a1b9a">
        <div class="kpi-label">Cost Estimate</div>
        <div class="kpi-value kpi-cost">{cost:,.0f} <span class="kpi-unit">฿</span></div>
        <div class="kpi-sub">คำนวณจากอัตรา TOU + Ft</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ─── Section 2: Weekly Comparison ────────────────────────────────────────────
st.markdown('<div class="section-header">📊 Weekly Usage Comparison</div>', unsafe_allow_html=True)

departments    = sorted(df["department"].unique().tolist())
filter_options = ["🏭 Factory (ทั้งหมด)"] + departments

col_f, col_g = st.columns([1, 3])
with col_f:
    dept_sel = st.selectbox("🔍 เลือกแผนก", filter_options, index=0)

agg_cur  = week_agg(df, latest_week, dept_sel)
agg_prev = week_agg(df, prev_week,   dept_sel) if prev_week else None

label_cur  = f"สัปดาห์นี้\n({latest_week})"
label_prev = f"สัปดาห์ที่แล้ว\n({prev_week})" if prev_week else "สัปดาห์ที่แล้ว"

on_vals  = [agg_prev["on_peak"]  if agg_prev is not None else 0, agg_cur["on_peak"]]
off_vals = [agg_prev["off_peak"] if agg_prev is not None else 0, agg_cur["off_peak"]]
x_labels = [label_prev, label_cur]

fig_w = go.Figure()
fig_w.add_trace(go.Bar(
    name="On Peak", x=x_labels, y=on_vals, marker_color="#e65100",
    text=[f"{v:,.0f}" for v in on_vals], textposition="outside",
))
fig_w.add_trace(go.Bar(
    name="Off Peak", x=x_labels, y=off_vals, marker_color="#1565c0",
    text=[f"{v:,.0f}" for v in off_vals], textposition="outside",
))
fig_w.update_layout(
    barmode="group", height=360,
    yaxis_title="kWh",
    title_text=f"On Peak vs Off Peak — {dept_sel}",
    title_font_size=13,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(t=50, b=20, l=20, r=20),
    plot_bgcolor="white", paper_bgcolor="white",
)
fig_w.update_yaxes(gridcolor="#f0f0f0")

with col_g:
    st.plotly_chart(fig_w, use_container_width=True)

# ─── Section 3: Department Breakdown ─────────────────────────────────────────
st.markdown('<div class="section-header">🏭 Department Usage Breakdown</div>', unsafe_allow_html=True)

dept_cur  = dept_week_agg(df, latest_week).set_index("department")
dept_prev = dept_week_agg(df, prev_week).set_index("department") if prev_week else None
all_depts = sorted(dept_cur.index.tolist())

fig_d = make_subplots(
    rows=len(all_depts), cols=1,
    shared_xaxes=True,
    subplot_titles=all_depts,
    vertical_spacing=0.03,
)

for i, dep in enumerate(all_depts, start=1):
    cur_on  = dept_cur.loc[dep,  "on_peak"]  if dep in dept_cur.index  else 0
    cur_off = dept_cur.loc[dep,  "off_peak"] if dep in dept_cur.index  else 0
    prv_on  = dept_prev.loc[dep, "on_peak"]  if (dept_prev is not None and dep in dept_prev.index) else 0
    prv_off = dept_prev.loc[dep, "off_peak"] if (dept_prev is not None and dep in dept_prev.index) else 0

    total_cur = cur_on + cur_off
    total_prv = prv_on + prv_off
    pct       = ((total_cur - total_prv) / total_prv * 100) if total_prv else 0
    arrow_txt = f"▲{pct:.1f}%" if pct >= 0 else f"▼{abs(pct):.1f}%"
    clr       = "#e53935" if pct >= 0 else "#43a047"
    show_leg  = (i == 1)

    fig_d.add_trace(go.Bar(
        name="On Peak (ก่อน)", x=[prv_on], y=["ก่อน"],
        orientation="h", marker_color="#ffcc80",
        legendgroup="p_on", showlegend=show_leg,
        hovertemplate=f"{dep} On Peak (ก่อน): %{{x:,.0f}} kWh<extra></extra>",
    ), row=i, col=1)
    fig_d.add_trace(go.Bar(
        name="Off Peak (ก่อน)", x=[prv_off], y=["ก่อน"],
        orientation="h", marker_color="#90caf9",
        legendgroup="p_off", showlegend=show_leg,
        hovertemplate=f"{dep} Off Peak (ก่อน): %{{x:,.0f}} kWh<extra></extra>",
    ), row=i, col=1)
    fig_d.add_trace(go.Bar(
        name="On Peak (นี้)", x=[cur_on], y=["นี้"],
        orientation="h", marker_color="#e65100",
        legendgroup="c_on", showlegend=show_leg,
        hovertemplate=f"{dep} On Peak (นี้): %{{x:,.0f}} kWh<extra></extra>",
    ), row=i, col=1)
    fig_d.add_trace(go.Bar(
        name="Off Peak (นี้)", x=[cur_off], y=["นี้"],
        orientation="h", marker_color="#1565c0",
        legendgroup="c_off", showlegend=show_leg,
        hovertemplate=f"{dep} Off Peak (นี้): %{{x:,.0f}} kWh<extra></extra>",
    ), row=i, col=1)

    max_val = max(cur_on + cur_off, prv_on + prv_off)
    fig_d.add_annotation(
        x=max_val * 1.02, y=0.5,
        yref=f"y{i}", xref=f"x{i}",
        text=f"<b>{arrow_txt}</b>",
        showarrow=False,
        font=dict(color=clr, size=11),
        xanchor="left",
    )

fig_d.update_layout(
    barmode="stack",
    height=max(130 * len(all_depts), 500),
    legend=dict(orientation="h", yanchor="bottom", y=1.005, xanchor="right", x=1),
    margin=dict(l=80, r=120, t=60, b=20),
    plot_bgcolor="white", paper_bgcolor="white",
)
for i in range(1, len(all_depts) + 1):
    fig_d.update_xaxes(gridcolor="#f0f0f0", row=i, col=1)

st.plotly_chart(fig_d, use_container_width=True)

# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("---")
last_updated = datetime.now().strftime("%d/%m/%Y %H:%M")
st.caption(
    f"📅 สัปดาห์ล่าสุด: **{latest_week}** | "
    f"ก่อนหน้า: **{prev_week or 'N/A'}** | "
    f"ข้อมูล {df['date'].nunique()} วัน | "
    f"🕐 โหลดล่าสุด: {last_updated}"
)
