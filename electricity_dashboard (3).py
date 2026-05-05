import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="Electricity Usage Overview", layout="wide")

# ─── Google Sheet Config ──────────────────────────────────────────────────────
SHEET_ID   = "1Ym2yfzkLTyLTtJtLZSSgWoeew_IPWUaI_u6d45jKUnw"
SHEET_NAME = "Daily"
from urllib.parse import quote
EXPORT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx&sheet={quote(SHEET_NAME)}"

# ─── Thai electricity tariff (PEA TOU rates, Baht/kWh) ───────────────────────
ON_PEAK_RATE  = 4.1824
OFF_PEAK_RATE = 2.6369
FT_ADJ        = 0.3949

# ─── Thai day abbreviation → weekday number ───────────────────────────────────
DAY_TH = {"อา": 6, "จ": 0, "อ": 1, "พ": 2, "พฤ": 3, "ศ": 4, "ส": 5}

# ─── Helpers ──────────────────────────────────────────────────────────────────
def parse_date_col(raw_val: str, fallback_year: int = 2026):
    """Parse date cell like '01/03\\n(อา)' or '01/03\\n(จ)'.
    Returns (datetime, weekday_int) or (None, None).
    """
    match = re.match(r"(\d{2}/\d{2})", str(raw_val))
    if not match:
        return None, None
    date_str = match.group(1)
    d, m = map(int, date_str.split("/"))

    # Try current year first; if that fails try fallback_year
    for yr in [fallback_year, fallback_year - 1, datetime.now().year]:
        try:
            dt = datetime(yr, m, d)
            # Detect Thai day abbrev if present
            day_match = re.search(r"\((.+?)\)", str(raw_val))
            wd = DAY_TH.get(day_match.group(1), dt.weekday()) if day_match else dt.weekday()
            return dt, wd
        except ValueError:
            continue
    return None, None


def week_label(year_week: str, df: pd.DataFrame) -> str:
    """Convert '2026-W13' to '23 Mar – 29 Mar 2026'."""
    sub = df[df["year_week"] == year_week]["date"]
    if sub.empty:
        return year_week
    start = sub.min()
    end   = sub.max()
    if start.month == end.month:
        return f"{start.day} – {end.strftime('%-d %b %Y')}"
    else:
        return f"{start.strftime('%-d %b')} – {end.strftime('%-d %b %Y')}"


@st.cache_data(ttl=300)
def load_data_from_gsheet():
    try:
        raw = pd.read_excel(EXPORT_URL, sheet_name=SHEET_NAME, header=None)
    except Exception as e:
        st.error(f"❌ ไม่สามารถดึงข้อมูลจาก Google Sheet ได้: {e}")
        st.stop()

    return _parse_raw(raw)


def _parse_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Parse raw DataFrame (either from Google Sheet or uploaded xlsx)."""

    # ── Auto-detect header row (row containing dd/mm date patterns) ─────────
    header_row = 0
    for r in range(min(6, raw.shape[0])):
        if raw.iloc[r, :].astype(str).str.contains(r"\d{2}/\d{2}", regex=True).any():
            header_row = r
            break

    data_start_row = header_row + 2

    # ── Auto-detect date columns ─────────────────────────────────────────────
    # Infer file year from today (Google Sheet may span multiple months)
    fallback_year = datetime.now().year
    date_cols = []
    for i in range(4, raw.shape[1]):
        val = raw.iloc[header_row, i]
        if pd.notna(val):
            dt, wd = parse_date_col(str(val), fallback_year)
            if dt:
                date_cols.append({"col_idx": i, "date": dt, "weekday": wd})

    if not date_cols:
        st.error("❌ ไม่พบคอลัมน์วันที่ กรุณาตรวจสอบโครงสร้าง Sheet")
        st.stop()

    records = []
    for row_i in range(data_start_row, raw.shape[0]):
        meter  = raw.iloc[row_i, 0]
        group  = raw.iloc[row_i, 2]   # Main Group (col C)
        subgrp = raw.iloc[row_i, 3]   # Group / Sub-group (col D)
        if pd.isna(meter) or pd.isna(group):
            continue
        if str(group).strip() in ("nan", ""):
            continue
        for dc in date_cols:
            ci = dc["col_idx"]
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
        st.dataframe(raw.iloc[:5, :8])
        st.stop()

    df = pd.DataFrame(records)
    df["date"]      = pd.to_datetime(df["date"])
    df["week_num"]  = df["date"].dt.isocalendar().week.astype(int)
    df["year"]      = df["date"].dt.isocalendar().year.astype(int)
    df["year_week"] = df["year"].astype(str) + "-W" + df["week_num"].astype(str).str.zfill(2)
    return df


def get_all_weeks(df):
    """Return all weeks sorted, with ≥1 day of data."""
    return sorted(df["year_week"].unique().tolist())


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
        color:#1a237e; margin-bottom:4px;
    }
    .week-subtitle {
        font-size:15px; text-align:center; color:#546e7a;
        margin-bottom:20px; font-weight:500;
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
    div[data-testid="stSelectbox"] label {font-weight:600;}
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

all_weeks      = get_all_weeks(df)
complete_weeks = sorted(get_complete_weeks(df))

if not all_weeks:
    st.error("ไม่พบข้อมูล กรุณาตรวจสอบ Google Sheet")
    st.stop()

# ─── Week Selector (Header) ───────────────────────────────────────────────────
# Build display labels: "W13 · 23 Mar – 29 Mar 2026"
week_display_map = {}
for yw in all_weeks:
    label = week_label(yw, df)
    is_complete = yw in complete_weeks
    suffix = "" if is_complete else " ⚠️ ไม่ครบ 7 วัน"
    week_display_map[yw] = f"{yw}  ·  {label}{suffix}"

display_options = list(week_display_map.values())
yw_keys         = list(week_display_map.keys())

# Default to latest complete week (or latest available)
default_yw  = complete_weeks[-1] if complete_weeks else all_weeks[-1]
default_idx = yw_keys.index(default_yw)

col_sel1, col_sel2, col_sel3 = st.columns([1, 2, 1])
with col_sel2:
    selected_display = st.selectbox(
        "📅 เลือกสัปดาห์",
        options=display_options,
        index=default_idx,
        help="เลือกสัปดาห์ที่ต้องการดู (⚠️ = ข้อมูลยังไม่ครบ 7 วัน)"
    )

selected_yw  = yw_keys[display_options.index(selected_display)]
selected_idx = yw_keys.index(selected_yw)
prev_yw      = yw_keys[selected_idx - 1] if selected_idx > 0 else None

# Show week date range as subtitle
sel_label = week_label(selected_yw, df)
st.markdown(f'<div class="week-subtitle">📆 สัปดาห์ {selected_yw} &nbsp;|&nbsp; {sel_label}</div>',
            unsafe_allow_html=True)

st.markdown("---")

# ─── Section 1: KPI Cards ─────────────────────────────────────────────────────
agg       = week_agg(df, selected_yw)
on_kwh    = agg["on_peak"]
off_kwh   = agg["off_peak"]
total_kwh = on_kwh + off_kwh
cost      = on_kwh * (ON_PEAK_RATE + FT_ADJ) + off_kwh * (OFF_PEAK_RATE + FT_ADJ)
on_pct    = on_kwh  / total_kwh * 100 if total_kwh else 0
off_pct   = off_kwh / total_kwh * 100 if total_kwh else 0

if prev_yw:
    agg_p      = week_agg(df, prev_yw)
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

prev_label = week_label(prev_yw, df) if prev_yw else "N/A"

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Total Energy This Week</div>
        <div class="kpi-value">{total_kwh:,.0f} <span class="kpi-unit">kWh</span></div>
        <div class="kpi-sub">vs สัปดาห์ก่อน &nbsp; {badge(chg_total)}</div>
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

# ─── Section 2: Weekly Comparison ─────────────────────────────────────────────
st.markdown('<div class="section-header">📊 Weekly Usage Comparison</div>', unsafe_allow_html=True)

departments    = sorted(df["department"].unique().tolist())
filter_options = ["🏭 Factory (ทั้งหมด)"] + departments

col_f, col_g = st.columns([1, 3])
with col_f:
    dept_sel = st.selectbox("🔍 เลือกแผนก", filter_options, index=0)

agg_cur  = week_agg(df, selected_yw, dept_sel)
agg_prev = week_agg(df, prev_yw,     dept_sel) if prev_yw else None

label_cur  = f"สัปดาห์นี้\n({sel_label})"
label_prev = f"สัปดาห์ก่อน\n({prev_label})" if prev_yw else "สัปดาห์ก่อน"

on_vals  = [agg_prev["on_peak"]  if agg_prev is not None else 0, agg_cur["on_peak"]]
off_vals = [agg_prev["off_peak"] if agg_prev is not None else 0, agg_cur["off_peak"]]
x_labels = [label_prev, label_cur]

# Compute % splits per bar for inside labels
tot_vals     = [on_vals[i] + off_vals[i] for i in range(2)]
on_pct_bars  = [on_vals[i]  / tot_vals[i] * 100 if tot_vals[i] else 0 for i in range(2)]
off_pct_bars = [off_vals[i] / tot_vals[i] * 100 if tot_vals[i] else 0 for i in range(2)]

fig_w = go.Figure()
fig_w.add_trace(go.Bar(
    name="On Peak", x=x_labels, y=on_vals, marker_color="#e65100",
    text=[f"{v:,.0f} kWh  ({on_pct_bars[i]:.0f}%)" for i, v in enumerate(on_vals)],
    textposition="inside", insidetextanchor="middle",
    textfont=dict(color="white", size=12),
))
fig_w.add_trace(go.Bar(
    name="Off Peak", x=x_labels, y=off_vals, marker_color="#1565c0",
    text=[f"{v:,.0f} kWh  ({off_pct_bars[i]:.0f}%)" for i, v in enumerate(off_vals)],
    textposition="inside", insidetextanchor="middle",
    textfont=dict(color="white", size=12),
))
# Total label on top of each bar
for xl, tv in zip(x_labels, tot_vals):
    fig_w.add_annotation(
        x=xl, y=tv, text=f"<b>{tv:,.0f} kWh</b>",
        showarrow=False, yshift=12,
        font=dict(size=12, color="#1a237e"),
    )
fig_w.update_layout(
    barmode="stack", height=400,
    yaxis_title="kWh",
    title_text=f"On Peak vs Off Peak — {dept_sel}",
    title_font_size=13,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(t=50, b=20, l=20, r=60),
    plot_bgcolor="white", paper_bgcolor="white",
)
fig_w.update_yaxes(gridcolor="#f0f0f0")

with col_g:
    st.plotly_chart(fig_w, use_container_width=True)

# ── Summary text block below chart ───────────────────────────────────────────
cur_total_w  = agg_cur["on_peak"]  + agg_cur["off_peak"]
prev_total_w = (agg_prev["on_peak"] + agg_prev["off_peak"]) if agg_prev is not None else 0
diff_w       = cur_total_w - prev_total_w
pct_w        = (diff_w / prev_total_w * 100) if prev_total_w else 0
cur_on_pct   = agg_cur["on_peak"]  / cur_total_w * 100 if cur_total_w else 0
cur_off_pct  = agg_cur["off_peak"] / cur_total_w * 100 if cur_total_w else 0

direction   = "เพิ่มขึ้น" if diff_w >= 0 else "ลดลง"
dir_color   = "#e53935"   if diff_w >= 0 else "#43a047"
dir_icon    = "▲"         if diff_w >= 0 else "▼"
summary_dept = dept_sel if dept_sel != "🏭 Factory (ทั้งหมด)" else "ทั้งโรงงาน"
prev_wk_txt  = f"เทียบกับสัปดาห์ก่อน {prev_total_w:,.0f} kWh" if prev_yw else ""

st.markdown(f"""
<div style="background:#f8f9ff;border-left:4px solid #1565c0;border-radius:8px;
            padding:14px 22px;margin-top:4px;font-size:14px;line-height:2.0;color:#333;">
  📋 <b>สรุปการใช้ไฟฟ้า &mdash; {summary_dept} &nbsp;|&nbsp; {sel_label}</b><br>
  สัปดาห์นี้ใช้ไฟฟ้ารวมทั้งสิ้น <b>{cur_total_w:,.0f} kWh</b><br>
  &nbsp;&nbsp;&nbsp;
  <span style="color:#e65100;font-weight:600;">● On Peak</span>&nbsp;&nbsp;
  <b>{agg_cur["on_peak"]:,.0f} kWh</b>
  &nbsp;<span style="color:#888;">({cur_on_pct:.1f}%)</span>
  &emsp;
  <span style="color:#1565c0;font-weight:600;">● Off Peak</span>&nbsp;
  <b>{agg_cur["off_peak"]:,.0f} kWh</b>
  &nbsp;<span style="color:#888;">({cur_off_pct:.1f}%)</span><br>
  {prev_wk_txt} &nbsp;→&nbsp;
  <span style="color:{dir_color};font-weight:700;">{dir_icon} {direction} {abs(diff_w):,.0f} kWh &nbsp;({abs(pct_w):.1f}%)</span>
</div>
""", unsafe_allow_html=True)

# ─── Section 3: Department Breakdown ──────────────────────────────────────────
st.markdown('<div class="section-header">🏭 Department Usage Breakdown</div>', unsafe_allow_html=True)

dept_cur  = dept_week_agg(df, selected_yw).set_index("department")
dept_prev = dept_week_agg(df, prev_yw).set_index("department") if prev_yw else None
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

    max_val = max(cur_on + cur_off, prv_on + prv_off, 1)
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
num_days_selected = df[df["year_week"] == selected_yw]["date"].nunique()
st.caption(
    f"📅 สัปดาห์ที่เลือก: **{selected_yw}** ({sel_label}) | "
    f"จำนวนข้อมูล: **{num_days_selected} วัน** | "
    f"สัปดาห์ก่อน: **{prev_yw or 'N/A'}** ({prev_label}) | "
    f"🕐 โหลดล่าสุด: {last_updated}"
)
