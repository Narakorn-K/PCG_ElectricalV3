import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
from datetime import datetime
import sys

def fmt_day(dt, show_year=True):
    if sys.platform == 'win32':
        return dt.strftime('%#d %b %Y') if show_year else dt.strftime('%#d %b')
    return dt.strftime('%-d %b %Y') if show_year else dt.strftime('%-d %b')

def fmt_day_short(dt):
    return fmt_day(dt, show_year=False)

st.set_page_config(page_title="Energy Dashboard", layout="wide", page_icon="⚡")

SHEET_ID      = "1Ym2yfzkLTyLTtJtLZSSgWoeew_IPWUaI_u6d45jKUnw"
SHEET_NAME    = "Daily"
SHEET_TON     = "Product Ton"
ON_PEAK_RATE  = 4.1824
OFF_PEAK_RATE = 2.6369
FT_ADJ        = 0.1623

NON_PRODUCTION_DEPTS = {"Office", "Farm", "Coolroom"}

DAY_TH = {"อา": 6, "จ": 0, "อ": 1, "พ": 2, "พฤ": 3, "ศ": 4, "ส": 5}
MONTH_TH = {
    1: "ม.ค.", 2: "ก.พ.", 3: "มี.ค.", 4: "เม.ย.",
    5: "พ.ค.", 6: "มิ.ย.", 7: "ก.ค.", 8: "ส.ค.",
    9: "ก.ย.", 10: "ต.ค.", 11: "พ.ย.", 12: "ธ.ค.",
}

GROUP_BG = ["#f0f4ff", "#f0fff4", "#fff8f0", "#fdf0ff",
            "#f0f9ff", "#fffff0", "#fff0f5", "#f5fff0"]

st.markdown("""
<style>
.kpi-card {
    border: 1px solid #e8eaf0;
    border-radius: 12px;
    padding: 16px 18px 12px;
    text-align: center;
    border-top: 4px solid #1565c0;
    background: #fff;
}
.kpi-label { font-size: 12px; color: #666; font-weight: 600; text-transform: uppercase;
             letter-spacing: 0.5px; margin-bottom: 4px; }
.kpi-value { font-size: 22px; font-weight: 800; color: #1a237e; line-height: 1.2; }
.kpi-unit  { font-size: 13px; font-weight: 400; }
.kpi-sub   { font-size: 12px; color: #999; margin-top: 4px; }
.summary-box {
    border-left: 4px solid #1565c0;
    border-radius: 0 8px 8px 0;
    padding: 12px 20px;
    margin-top: 4px;
    margin-bottom: 4px;
    font-size: 14px;
    line-height: 2.0;
    color: #333;
    background: rgba(255,255,255,0.75);
}
.section-header {
    font-size: 15px; font-weight: 700; color: #1a237e;
    border-left: 4px solid #1565c0; padding-left: 10px;
    margin: 20px 0 10px;
}
.group-block {
    border-radius: 10px;
    padding: 16px 20px 12px;
    margin-bottom: 12px;
}
.dept-name {
    font-size: 15px; font-weight: 700; color: #1a237e; margin-bottom: 6px;
}
</style>
""", unsafe_allow_html=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────
def parse_date_col(raw_val, fallback_year=2026):
    match = re.match(r"(\d{2}/\d{2})", str(raw_val))
    if not match:
        return None, None
    d, m = map(int, match.group(1).split("/"))
    for yr in [fallback_year, fallback_year - 1, datetime.now().year]:
        try:
            dt = datetime(yr, m, d)
            dm = re.search(r"\((.+?)\)", str(raw_val))
            wd = DAY_TH.get(dm.group(1), dt.weekday()) if dm else dt.weekday()
            return dt, wd
        except ValueError:
            continue
    return None, None


def pct_diff(cur, prev):
    if prev and prev != 0:
        return (cur - prev) / abs(prev) * 100
    return 0.0


def diff_badge(pct, invert=False):
    if abs(pct) < 0.05:
        return '<span style="color:#999;font-size:13px;">— 0%</span>'
    up_color   = "#43a047" if invert else "#e53935"
    down_color = "#e53935" if invert else "#43a047"
    color = up_color if pct > 0 else down_color
    arrow = "▲" if pct > 0 else "▼"
    return f'<span style="color:{color};font-weight:700;font-size:13px;">{arrow} {abs(pct):.1f}%</span>'


def diff_text(pct, invert=False):
    if abs(pct) < 0.05:
        return '<span style="color:#999;">ไม่เปลี่ยนแปลง</span>'
    up_color   = "#43a047" if invert else "#e53935"
    down_color = "#e53935" if invert else "#43a047"
    arrow = "▲" if pct >= 0 else "▼"
    word  = "เพิ่มขึ้น" if pct >= 0 else "ลดลง"
    color = up_color if pct >= 0 else down_color
    return f'<span style="color:{color};font-weight:700;">{arrow} {word} {abs(pct):.1f}%</span>'


def build_kpi_card(label, value, unit, sub, pct, accent_color="#1565c0", invert=False):
    return f"""
<div class="kpi-card" style="border-top-color:{accent_color}">
    <div class="kpi-label">{label}</div>
    <div class="kpi-value">{value} <span class="kpi-unit">{unit}</span></div>
    <div class="kpi-sub">{sub}</div>
    <div style="margin-top:6px">{diff_badge(pct, invert=invert)}</div>
</div>"""


# ─── Data loaders ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_all_bytes():
    import urllib.request
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
    try:
        req  = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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


# ─── Aggregation ──────────────────────────────────────────────────────────────
def agg_kwh(data, period_col, period_val):
    sub = data[data[period_col] == period_val]
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


# ─── Chart: LEFT — Ton bar + kWh/Ton line (70%) ───────────────────────────────
def make_kpt_chart(cur_label, prev_label, cur_ton, prev_ton,
                   cur_kwh, prev_kwh, height=320):
    cur_kpt  = cur_kwh  / cur_ton  if cur_ton  > 0 else 0.0
    prev_kpt = prev_kwh / prev_ton if prev_ton > 0 else 0.0
    x = [f"ก่อนหน้า\n({prev_label})", f"ปัจจุบัน\n({cur_label})"]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        name="Ton ผลิต", x=x, y=[prev_ton, cur_ton],
        marker_color=["#90caf9", "#1565c0"],
        text=[f"{v:,.1f} Ton" for v in [prev_ton, cur_ton]],
        textposition="inside", insidetextanchor="middle",
        textfont=dict(color="white", size=13),
        width=0.45,
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

    max_ton = max(prev_ton, cur_ton, 1)
    max_kpt = max(prev_kpt, cur_kpt, 1)
    fig.update_layout(
        height=height, barmode="group", showlegend=True,
        legend=dict(orientation="h", y=1.12, x=1, xanchor="right", font=dict(size=11)),
        margin=dict(t=40, b=30, l=10, r=55),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(title_text="Ton", gridcolor="#eee",
                     range=[0, max_ton * 1.28], secondary_y=False)
    fig.update_yaxes(title_text="kWh/Ton", showgrid=False,
                     range=[0, max_kpt * 1.40], secondary_y=True)
    fig.update_xaxes(gridcolor="#eee")
    return fig


# ─── Chart: RIGHT — On/Off Peak stacked bar + kWh/Ton line (70%) ─────────────
def make_onoff_chart(cur_label, prev_label, cur_on, prev_on,
                     cur_off, prev_off,
                     cur_ton=0.0, prev_ton=0.0,
                     height=320):
    x        = [f"ก่อนหน้า\n({prev_label})", f"ปัจจุบัน\n({cur_label})"]
    on_vals  = [prev_on,  cur_on]
    off_vals = [prev_off, cur_off]
    tot_vals = [prev_on + prev_off, cur_on + cur_off]
    kpt_vals = [
        tot_vals[0] / prev_ton if prev_ton > 0 else None,
        tot_vals[1] / cur_ton  if cur_ton  > 0 else None,
    ]
    has_kpt  = any(v is not None for v in kpt_vals)

    def pct_lbl(v, tot):
        return f"{v/tot*100:.0f}%" if tot > 0 else ""

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Bar(
        name="Off Peak", x=x, y=off_vals,
        marker_color="#1565c0",
        text=[f"{off_vals[i]:,.0f} kWh ({pct_lbl(off_vals[i], tot_vals[i])})"
              for i in range(2)],
        textposition="inside", insidetextanchor="middle",
        textfont=dict(color="white", size=11),
    ), secondary_y=False)

    fig.add_trace(go.Bar(
        name="On Peak", x=x, y=on_vals,
        marker_color="#e65100",
        text=[f"{on_vals[i]:,.0f} kWh ({pct_lbl(on_vals[i], tot_vals[i])})"
              for i in range(2)],
        textposition="inside", insidetextanchor="middle",
        textfont=dict(color="white", size=11),
    ), secondary_y=False)

    # total annotation on top of bars
    max_tot = max(tot_vals[0], tot_vals[1], 1)
    for xl, tv in zip(x, tot_vals):
        fig.add_annotation(
            x=xl, y=tv, text=f"<b>{tv:,.0f} kWh</b>",
            showarrow=False, yshift=10,
            font=dict(size=12, color="#1a237e"),
        )

    # kWh/Ton line on secondary y
    if has_kpt:
        y_kpt = [v if v is not None else 0 for v in kpt_vals]
        max_kpt = max(v for v in y_kpt if v)
        fig.add_trace(go.Scatter(
            name="kWh/Ton", x=x, y=y_kpt,
            mode="lines+markers+text",
            line=dict(color="#43a047", width=3),
            marker=dict(size=10, color="#43a047"),
            text=[f"{v:,.2f}" if v else "" for v in y_kpt],
            textposition="top center",
            textfont=dict(size=13, color="#43a047"),
        ), secondary_y=True)

    fig.update_layout(
        barmode="stack", height=height, showlegend=True,
        legend=dict(orientation="h", y=1.12, x=1, xanchor="right", font=dict(size=11)),
        margin=dict(t=40, b=30, l=10, r=60),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(title_text="kWh", gridcolor="#eee",
                     range=[0, max_tot * 1.22], secondary_y=False)
    if has_kpt:
        fig.update_yaxes(title_text="kWh/Ton", showgrid=False,
                         range=[0, max_kpt * 1.40], secondary_y=True)
    fig.update_xaxes(gridcolor="#eee")
    return fig


# ─── Chart: kWh-only bar (non-production, no ton) ─────────────────────────────
def make_kwh_only_chart(cur_label, prev_label, cur_on, prev_on,
                        cur_off, prev_off, height=260):
    """Same On/Off stacked style for non-production depts — full width"""
    x        = [f"ก่อนหน้า\n({prev_label})", f"ปัจจุบัน\n({cur_label})"]
    on_vals  = [prev_on,  cur_on]
    off_vals = [prev_off, cur_off]
    tot_vals = [prev_on + prev_off, cur_on + cur_off]

    def pct_lbl(v, tot):
        return f"{v/tot*100:.0f}%" if tot > 0 else ""

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Off Peak", x=x, y=off_vals,
        marker_color="#1565c0",
        text=[f"{off_vals[i]:,.0f} kWh ({pct_lbl(off_vals[i], tot_vals[i])})"
              for i in range(2)],
        textposition="inside", insidetextanchor="middle",
        textfont=dict(color="white", size=12),
    ))
    fig.add_trace(go.Bar(
        name="On Peak", x=x, y=on_vals,
        marker_color="#e65100",
        text=[f"{on_vals[i]:,.0f} kWh ({pct_lbl(on_vals[i], tot_vals[i])})"
              for i in range(2)],
        textposition="inside", insidetextanchor="middle",
        textfont=dict(color="white", size=12),
    ))
    for i, (xl, tv) in enumerate(zip(x, tot_vals)):
        fig.add_annotation(
            x=xl, y=tv, text=f"<b>{tv:,.0f} kWh</b>",
            showarrow=False, yshift=10, font=dict(size=12, color="#1a237e"),
        )
    max_tot = max(tot_vals[0], tot_vals[1], 1)
    fig.update_layout(
        barmode="stack", height=height, showlegend=True,
        legend=dict(orientation="h", y=1.12, x=1, xanchor="right", font=dict(size=11)),
        margin=dict(t=40, b=30, l=10, r=15),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(title_text="kWh", gridcolor="#eee", range=[0, max_tot * 1.22])
    fig.update_xaxes(gridcolor="#eee")
    return fig


# ─── Summary boxes ────────────────────────────────────────────────────────────
def summary_kpt_html(cur_kwh, prev_kwh, cur_ton, prev_ton, period_name):
    cur_kpt  = cur_kwh  / cur_ton  if cur_ton  > 0 else None
    prev_kpt = prev_kwh / prev_ton if prev_ton > 0 else None
    pct_kwh  = pct_diff(cur_kwh, prev_kwh)
    pct_ton  = pct_diff(cur_ton,  prev_ton)
    pct_kpt  = pct_diff(cur_kpt,  prev_kpt) if (cur_kpt and prev_kpt) else None

    kpt_line = ""
    if cur_kpt is not None:
        kpt_line = (f"• Unit ต่อตัน <b>{cur_kpt:,.2f} kWh/Ton</b> &nbsp;"
                    f"{diff_text(pct_kpt) if pct_kpt is not None else ''}<br>")

    ton_str = diff_text(pct_ton, invert=True) if cur_ton > 0 else '<span style="color:#999">ไม่มีข้อมูล Ton</span>'

    return f"""<div class="summary-box">
• Total Energy <b>{cur_kwh:,.0f} kWh</b> &nbsp; {diff_text(pct_kwh)} vs {period_name}<br>
{kpt_line}• Production <b>{cur_ton:,.1f} Ton</b> &nbsp; {ton_str} vs {period_name}
</div>"""


def summary_kwh_html(cur_kwh, prev_kwh, period_name):
    pct = pct_diff(cur_kwh, prev_kwh)
    return f"""<div class="summary-box">
• Total Energy <b>{cur_kwh:,.0f} kWh</b> &nbsp; {diff_text(pct)} vs {period_name}
</div>"""


# ─── Main renderer: one group block ───────────────────────────────────────────
def render_group(dept_name, bg,
                 cur_label, prev_label, period_name,
                 cur_on, prev_on, cur_off, prev_off,
                 cur_ton, prev_ton,
                 is_production=True, chart_height=320):

    cur_kwh  = cur_on  + cur_off
    prev_kwh = prev_on + prev_off

    st.markdown(f'<div class="group-block" style="background:{bg}">', unsafe_allow_html=True)
    st.markdown(f'<div class="dept-name">📌 {dept_name}</div>', unsafe_allow_html=True)

    if is_production:
        # 70 / 30 layout
        col_left, col_right = st.columns([3, 7])
        with col_left:
            title_left = f"On Peak vs Off Peak — 📊 {dept_name}"
            fig_l = make_kpt_chart(cur_label, prev_label,
                                   cur_ton, prev_ton,
                                   cur_kwh, prev_kwh,
                                   height=chart_height)
            fig_l.update_layout(title_text=f"Ton ผลิต & kWh/Ton — {dept_name}",
                                 title_font_size=13)
            st.plotly_chart(fig_l, use_container_width=True)

        with col_right:
            fig_r = make_onoff_chart(cur_label, prev_label,
                                     cur_on, prev_on,
                                     cur_off, prev_off,
                                     cur_ton=cur_ton, prev_ton=prev_ton,
                                     height=chart_height)
            fig_r.update_layout(title_text=f"On Peak vs Off Peak — {dept_name}",
                                 title_font_size=13)
            st.plotly_chart(fig_r, use_container_width=True)

        st.markdown(summary_kpt_html(cur_kwh, prev_kwh, cur_ton, prev_ton, period_name),
                    unsafe_allow_html=True)

    else:
        # kWh only — full width On/Off stacked
        fig = make_kwh_only_chart(cur_label, prev_label,
                                  cur_on, prev_on, cur_off, prev_off,
                                  height=chart_height - 60)
        fig.update_layout(title_text=f"On Peak vs Off Peak — {dept_name}", title_font_size=13)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown(summary_kwh_html(cur_kwh, prev_kwh, period_name), unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


def render_all_blocks(period_col, period_val, prev_val,
                      cur_label, prev_label, period_name):
    cur_da   = dept_agg(df, period_col, period_val)
    prev_da  = dept_agg(df, period_col, prev_val) if prev_val else pd.DataFrame()
    cur_ton  = agg_ton(ton, period_col, period_val)
    prev_ton = agg_ton(ton, period_col, prev_val) if prev_val else 0.0

    prod_depts    = [d for d in cur_da.index if d not in NON_PRODUCTION_DEPTS]
    nonprod_depts = [d for d in cur_da.index if d in NON_PRODUCTION_DEPTS]

    # ── กลุ่มเกี่ยวกับการผลิต ─────────────────────────────────────────────────
    st.markdown('<div class="section-header">🏭 ส่วนที่เกี่ยวข้องกับการผลิต kWh/Ton</div>',
                unsafe_allow_html=True)
    for i, dept in enumerate(prod_depts):
        c_row = cur_da.loc[dept]
        p_row = prev_da.loc[dept] if (not prev_da.empty and dept in prev_da.index) else None
        render_group(
            dept_name=dept, bg=GROUP_BG[i % len(GROUP_BG)],
            cur_label=cur_label, prev_label=prev_label, period_name=period_name,
            cur_on=c_row["on_peak"],   prev_on=p_row["on_peak"]   if p_row is not None else 0.0,
            cur_off=c_row["off_peak"], prev_off=p_row["off_peak"] if p_row is not None else 0.0,
            cur_ton=cur_ton, prev_ton=prev_ton,
            is_production=True,
        )

    # ── กลุ่มไม่เกี่ยวกับการผลิต ──────────────────────────────────────────────
    if nonprod_depts:
        st.markdown('<div class="section-header">💡 ส่วนที่ไม่เกี่ยวข้องกับการผลิต kWh</div>',
                    unsafe_allow_html=True)
        for i, dept in enumerate(nonprod_depts):
            c_row = cur_da.loc[dept]
            p_row = prev_da.loc[dept] if (not prev_da.empty and dept in prev_da.index) else None
            render_group(
                dept_name=dept, bg=GROUP_BG[(len(prod_depts) + i) % len(GROUP_BG)],
                cur_label=cur_label, prev_label=prev_label, period_name=period_name,
                cur_on=c_row["on_peak"],   prev_on=p_row["on_peak"]   if p_row is not None else 0.0,
                cur_off=c_row["off_peak"], prev_off=p_row["off_peak"] if p_row is not None else 0.0,
                cur_ton=cur_ton, prev_ton=prev_ton,
                is_production=False,
            )


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

    col_s1, _, _ = st.columns([2, 2, 2])
    with col_s1:
        yw_labels   = [f"{yw}  ({week_label(yw)})" for yw in all_weeks]
        sel_display = st.selectbox("📅 เลือกสัปดาห์", yw_labels,
                                   index=len(all_weeks) - 1, key="w_week")
        sel_yw  = all_weeks[yw_labels.index(sel_display)]
        sel_idx = all_weeks.index(sel_yw)
        prev_yw = all_weeks[sel_idx - 1] if sel_idx > 0 else None

    sel_lbl  = week_label(sel_yw)
    prev_lbl = week_label(prev_yw) if prev_yw else "N/A"

    st.markdown(f"### ⚡ สัปดาห์ {sel_yw} &nbsp;|&nbsp; {sel_lbl}")
    st.markdown("---")

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    cur_e    = agg_kwh(df, "year_week", sel_yw)
    prev_e   = agg_kwh(df, "year_week", prev_yw) if prev_yw else pd.Series({"on_peak": 0, "off_peak": 0})
    cur_ton  = agg_ton(ton, "year_week", sel_yw)
    prev_ton = agg_ton(ton, "year_week", prev_yw) if prev_yw else 0.0

    cur_on  = cur_e["on_peak"];  cur_off  = cur_e["off_peak"]
    prev_on = prev_e["on_peak"]; prev_off = prev_e["off_peak"]
    cur_tot  = cur_on  + cur_off;  prev_tot  = prev_on + prev_off
    cur_cost  = cur_on  * (ON_PEAK_RATE + FT_ADJ) + cur_off  * (OFF_PEAK_RATE + FT_ADJ)
    prev_cost = prev_on * (ON_PEAK_RATE + FT_ADJ) + prev_off * (OFF_PEAK_RATE + FT_ADJ)
    cur_kpt   = cur_tot  / cur_ton  if cur_ton  > 0 else None
    prev_kpt  = prev_tot / prev_ton if prev_ton > 0 else None
    on_pct    = cur_on  / cur_tot * 100 if cur_tot else 0
    off_pct   = cur_off / cur_tot * 100 if cur_tot else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.markdown(build_kpi_card("Production Ton", f"{cur_ton:,.1f}", "Ton",
            f"ก่อน {prev_ton:,.1f} Ton", pct_diff(cur_ton, prev_ton), "#00838f", invert=True),
            unsafe_allow_html=True)
    with c2:
        st.markdown(build_kpi_card("Total Energy", f"{cur_tot:,.0f}", "kWh",
            f"ก่อน {prev_tot:,.0f} kWh", pct_diff(cur_tot, prev_tot), "#1565c0"),
            unsafe_allow_html=True)
    with c3:
        st.markdown(build_kpi_card("On Peak", f"{cur_on:,.0f}", "kWh",
            f"สัดส่วน {on_pct:.1f}%", pct_diff(cur_on, prev_on), "#e65100"),
            unsafe_allow_html=True)
    with c4:
        st.markdown(build_kpi_card("Off Peak", f"{cur_off:,.0f}", "kWh",
            f"สัดส่วน {off_pct:.1f}%", pct_diff(cur_off, prev_off), "#2e7d32", invert=True),
            unsafe_allow_html=True)
    with c5:
        st.markdown(build_kpi_card("ค่าไฟโดยประมาณ", f"{cur_cost:,.0f}", "฿",
            "อัตรา TOU + Ft", pct_diff(cur_cost, prev_cost), "#6a1b9a"),
            unsafe_allow_html=True)
    with c6:
        kpt_val = f"{cur_kpt:,.2f}" if cur_kpt else "N/A"
        kpt_sub = f"ก่อน {prev_kpt:.2f}" if prev_kpt else "ไม่มีข้อมูล Ton"
        st.markdown(build_kpi_card("kWh / Ton", kpt_val, "",
            kpt_sub, pct_diff(cur_kpt, prev_kpt) if (cur_kpt and prev_kpt) else 0, "#00897b"),
            unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Factory รวม ───────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">📊 kWh/Ton — ทั้งโรงงาน (Factory)</div>',
                unsafe_allow_html=True)
    render_group(
        dept_name="ทั้งโรงงาน", bg=GROUP_BG[0],
        cur_label=sel_lbl, prev_label=prev_lbl, period_name="สัปดาห์ที่แล้ว",
        cur_on=cur_on, prev_on=prev_on, cur_off=cur_off, prev_off=prev_off,
        cur_ton=cur_ton, prev_ton=prev_ton, is_production=True, chart_height=340,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── รายแผนก ───────────────────────────────────────────────────────────────
    render_all_blocks("year_week", sel_yw, prev_yw, sel_lbl, prev_lbl, "สัปดาห์ที่แล้ว")

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

    col_s1, _, _ = st.columns([2, 2, 2])
    with col_s1:
        ym_labels   = [month_label(ym) for ym in all_ym]
        sel_ym_disp = st.selectbox("📅 เลือกเดือน", ym_labels,
                                   index=len(all_ym) - 1, key="m_month")
        sel_ym     = all_ym[ym_labels.index(sel_ym_disp)]
        sel_ym_idx = all_ym.index(sel_ym)
        prev_ym    = all_ym[sel_ym_idx - 1] if sel_ym_idx > 0 else None

    sel_mlbl  = month_label(sel_ym)
    prev_mlbl = month_label(prev_ym) if prev_ym else "N/A"

    st.markdown(f"### ⚡ เดือน {sel_mlbl}")
    st.markdown("---")

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    cur_me    = agg_kwh(df, "ym", sel_ym)
    prev_me   = agg_kwh(df, "ym", prev_ym) if prev_ym else pd.Series({"on_peak": 0, "off_peak": 0})
    cur_mton  = agg_ton(ton, "ym", sel_ym)
    prev_mton = agg_ton(ton, "ym", prev_ym) if prev_ym else 0.0

    cur_mon  = cur_me["on_peak"];  cur_moff  = cur_me["off_peak"]
    prev_mon = prev_me["on_peak"]; prev_moff = prev_me["off_peak"]
    cur_mtot  = cur_mon  + cur_moff;  prev_mtot = prev_mon + prev_moff
    cur_mcost  = cur_mon  * (ON_PEAK_RATE + FT_ADJ) + cur_moff  * (OFF_PEAK_RATE + FT_ADJ)
    prev_mcost = prev_mon * (ON_PEAK_RATE + FT_ADJ) + prev_moff * (OFF_PEAK_RATE + FT_ADJ)
    cur_mkpt   = cur_mtot  / cur_mton  if cur_mton  > 0 else None
    prev_mkpt  = prev_mtot / prev_mton if prev_mton > 0 else None
    mon_pct    = cur_mon  / cur_mtot * 100 if cur_mtot else 0
    moff_pct   = cur_moff / cur_mtot * 100 if cur_mtot else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.markdown(build_kpi_card("Production Ton", f"{cur_mton:,.1f}", "Ton",
            f"ก่อน {prev_mton:,.1f} Ton", pct_diff(cur_mton, prev_mton), "#00838f", invert=True),
            unsafe_allow_html=True)
    with c2:
        st.markdown(build_kpi_card("Total Energy", f"{cur_mtot:,.0f}", "kWh",
            f"ก่อน {prev_mtot:,.0f} kWh", pct_diff(cur_mtot, prev_mtot), "#1565c0"),
            unsafe_allow_html=True)
    with c3:
        st.markdown(build_kpi_card("On Peak", f"{cur_mon:,.0f}", "kWh",
            f"สัดส่วน {mon_pct:.1f}%", pct_diff(cur_mon, prev_mon), "#e65100"),
            unsafe_allow_html=True)
    with c4:
        st.markdown(build_kpi_card("Off Peak", f"{cur_moff:,.0f}", "kWh",
            f"สัดส่วน {moff_pct:.1f}%", pct_diff(cur_moff, prev_moff), "#2e7d32", invert=True),
            unsafe_allow_html=True)
    with c5:
        st.markdown(build_kpi_card("ค่าไฟโดยประมาณ", f"{cur_mcost:,.0f}", "฿",
            "อัตรา TOU + Ft", pct_diff(cur_mcost, prev_mcost), "#6a1b9a"),
            unsafe_allow_html=True)
    with c6:
        mkpt_val = f"{cur_mkpt:,.2f}" if cur_mkpt else "N/A"
        mkpt_sub = f"ก่อน {prev_mkpt:.2f}" if prev_mkpt else "ไม่มีข้อมูล Ton"
        st.markdown(build_kpi_card("kWh / Ton", mkpt_val, "",
            mkpt_sub, pct_diff(cur_mkpt, prev_mkpt) if (cur_mkpt and prev_mkpt) else 0, "#00897b"),
            unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Factory รวม ───────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">📊 kWh/Ton — ทั้งโรงงาน (Factory)</div>',
                unsafe_allow_html=True)
    render_group(
        dept_name="ทั้งโรงงาน", bg=GROUP_BG[0],
        cur_label=sel_mlbl, prev_label=prev_mlbl, period_name="เดือนก่อน",
        cur_on=cur_mon, prev_on=prev_mon, cur_off=cur_moff, prev_off=prev_moff,
        cur_ton=cur_mton, prev_ton=prev_mton, is_production=True, chart_height=340,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── รายแผนก ───────────────────────────────────────────────────────────────
    render_all_blocks("ym", sel_ym, prev_ym, sel_mlbl, prev_mlbl, "เดือนก่อน")

    st.markdown("---")
    st.caption(f"📅 {sel_mlbl} | เทียบ: {prev_mlbl} | 🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
