import streamlit as st
import numpy as np
import pandas as pd
import math
from datetime import datetime
from scipy.optimize import brentq
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import os

# ========== ページ設定 ==========
st.set_page_config(page_title="YAMATO 炉体熱計算ツール", page_icon="🔥", layout="wide")

# ========== 🔐 パスワード認証 ==========
def check_password():
    """シンプルなパスワード認証"""
    def password_entered():
        if st.session_state["password"] == "yamato5360":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.markdown("""
        <div style="text-align:center; padding:2rem;">
            <h1 style="color:#FF6B35;">🔥 YAMATO 炉体熱計算ツール</h1>
            <p style="color:#888;">🔒 社内専用ツール｜パスワードを入力してください</p>
        </div>
        """, unsafe_allow_html=True)
        st.text_input("パスワード", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.markdown("""
        <div style="text-align:center; padding:2rem;">
            <h1 style="color:#FF6B35;">🔥 YAMATO 炉体熱計算ツール</h1>
            <p style="color:#888;">🔒 社内専用ツール｜パスワードを入力してください</p>
        </div>
        """, unsafe_allow_html=True)
        st.text_input("パスワード", type="password", on_change=password_entered, key="password")
        st.error("❌ パスワードが違います")
        return False
    else:
        return True

if not check_password():
    st.stop()

# ========== カスタムCSS ==========
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #FF6B35 0%, #F7931E 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .stMetric {
        background: rgba(255, 107, 53, 0.05);
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid rgba(255, 107, 53, 0.2);
    }
    .footer {
        text-align: center;
        color: #888;
        font-size: 0.85rem;
        margin-top: 3rem;
        padding-top: 1rem;
        border-top: 1px solid #333;
    }
</style>
""", unsafe_allow_html=True)

# ========== ヘッダー ==========
st.markdown("""
<div class="main-header">
    <h1>🔥 YAMATO 炉体熱計算ツール</h1>
    <p style="margin:0; opacity:0.9;">1層断熱・3面合算＋開口部 / 放散熱量＆ヒータ容量算出</p>
</div>
""", unsafe_allow_html=True)

# ========== 計算関数 ==========
def lambda_kaowool(Tm):
    return (0.0247 + 1.14e-4 * Tm + 7.55e-8 * Tm**2) / 1.1628

def calc_face(Ts, Tw, L_mm, A, Cc, epsilon, insulation, lambda_user):
    L = L_mm / 1000.0
    def lam_fn(Tm):
        return lambda_kaowool(Tm) if insulation == "カオウール" else lambda_user
    def residual(T2):
        dt = T2 - Tw
        Tm = (Ts + T2) / 2.0
        lam = lam_fn(Tm)
        qr = epsilon * 4.88 * (((273 + T2) / 100)**4 - ((273 + Tw) / 100)**4)
        alpha_r = qr / dt
        alpha_c = Cc * dt**0.25
        q_conv = (alpha_r + alpha_c) * dt
        q_cond = lam * (Ts - T2) / L
        return q_cond - q_conv
    T2 = brentq(residual, Tw + 0.1, Ts - 0.1, xtol=1e-4)
    dt = T2 - Tw
    Tm = (Ts + T2) / 2.0
    lam = lam_fn(Tm)
    qr = epsilon * 4.88 * (((273 + T2) / 100)**4 - ((273 + Tw) / 100)**4)
    alpha_r = qr / dt
    alpha_c = Cc * dt**0.25
    q = (alpha_r + alpha_c) * dt
    Q = q * A
    return {"T2": T2, "Tm": Tm, "λ": lam, "αr": alpha_r, "αc": alpha_c,
            "α": alpha_r + alpha_c, "q": q, "Q": Q, "A": A}

# ========== サイドバー ==========
with st.sidebar:
    st.header("📋 案件情報")
    project_name = st.text_input("案件名", value="")
    customer = st.text_input("お客様名", value="")
    author = st.text_input("担当者", value="あっくん")

    st.divider()
    st.header("⚙️ 共通条件")
    Ts = st.number_input("炉内温度 Ts [℃]", value=750, min_value=0, max_value=1500, step=10)
    Tw = st.number_input("外気温度 Tw [℃]", value=20, min_value=-20, max_value=50, step=1)
    
    st.divider()
    st.subheader("📐 物性値")
    epsilon = st.number_input("輻射率 ε", value=0.5, min_value=0.0, max_value=1.0, step=0.05,
                              help="SS銀ペ塗装=0.5（標準）")
    insulation = st.selectbox("断熱材", ["カオウール", "その他(手入力)"])
    lambda_user = None
    if insulation == "その他(手入力)":
        lambda_user = st.number_input("熱伝導率 λ [kcal/m·h·℃]", value=0.10, step=0.01)
    
    st.divider()
    safety_factor = st.slider("🛡️ 安全率", min_value=1.0, max_value=2.5, value=1.5, step=0.1)

# ========== 炉体寸法 ==========
st.subheader("📐 炉体寸法")
shape = st.radio("炉の形状", ["角型", "円筒型", "手入力(特殊形状)"], horizontal=True)

if shape == "角型":
    c1, c2, c3 = st.columns(3)
    W = c1.number_input("幅 W [mm]", value=600, step=10)
    D = c2.number_input("奥行 D [mm]", value=440, step=10)
    H = c3.number_input("高さ H [mm]", value=500, step=10)
    W_m, D_m, H_m = W/1000, D/1000, H/1000
    side_A = 2 * (W_m + D_m) * H_m
    top_A = W_m * D_m
    bot_A = W_m * D_m
    st.success(f"✅ 自動算出： 側面 = {side_A:.3f} m² / 上面 = {top_A:.3f} m² / 底面 = {bot_A:.3f} m²")
elif shape == "円筒型":
    c1, c2 = st.columns(2)
    Phi = c1.number_input("外径 Φ [mm]", value=600, step=10)
    H = c2.number_input("高さ H [mm]", value=500, step=10)
    Phi_m, H_m = Phi/1000, H/1000
    side_A = math.pi * Phi_m * H_m
    top_A = math.pi * (Phi_m/2)**2
    bot_A = math.pi * (Phi_m/2)**2
    st.success(f"✅ 自動算出： 側面 = {side_A:.3f} m² / 上面 = {top_A:.3f} m² / 底面 = {bot_A:.3f} m²")
else:
    c1, c2, c3 = st.columns(3)
    side_A = c1.number_input("側面 表面積 [m²]", value=0.88, step=0.01)
    top_A = c2.number_input("上面 表面積 [m²]", value=0.264, step=0.01)
    bot_A = c3.number_input("底面 表面積 [m²]", value=0.264, step=0.01)

st.divider()

# ========== 各面の断熱材厚み ==========
st.subheader("🧱 各面の断熱材厚み")
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("#### 🔲 側面")
    side_L = st.number_input("厚み [mm]", value=50, step=5, key="side_L")
    st.caption(f"表面積 = {side_A:.3f} m² / Cc = 1.71(固定)")
with col2:
    st.markdown("#### ⬆️ 上面")
    top_L = st.number_input("厚み [mm]", value=120, step=5, key="top_L")
    st.caption(f"表面積 = {top_A:.3f} m² / Cc = 1.98(固定)")
with col3:
    st.markdown("#### ⬇️ 底面")
    bot_L = st.number_input("厚み [mm]", value=100, step=5, key="bot_L")
    st.caption(f"表面積 = {bot_A:.3f} m² / Cc = 1.98(固定)")

st.divider()

# ========== 開口部の入力 ==========
st.subheader("🕳️ 開口部（炉口）")
has_opening = st.checkbox("開口部あり", value=True)

opening_A = 0.0
opening_q = 12000
opening_count = 0
opening_shape = "-"
opening_dim_text = "-"

if has_opening:
    oc1, oc2 = st.columns(2)
    opening_shape = oc1.radio("開口形状", ["円形", "角型"], horizontal=True)
    opening_count = oc2.number_input("開口部の数", value=1, min_value=1, step=1)

    if opening_shape == "円形":
        Phi_o = st.number_input("開口径 Φ [mm]", value=300, step=10)
        opening_A_single = math.pi * (Phi_o/1000/2)**2
        opening_dim_text = f"Φ{Phi_o}mm × {opening_count}個"
    else:
        oc3, oc4 = st.columns(2)
        W_o = oc3.number_input("開口 幅 W [mm]", value=300, step=10)
        D_o = oc4.number_input("開口 奥行 D [mm]", value=300, step=10)
        opening_A_single = (W_o/1000) * (D_o/1000)
        opening_dim_text = f"{W_o}×{D_o}mm × {opening_count}個"

    opening_A = opening_A_single * opening_count
    opening_q = st.number_input("開口部 単位放熱量 [kcal/m²h]", value=12000, step=500,
                                help="一般値=12,000 kcal/m²h(炉内温度により可変)")

    st.success(f"✅ 開口部総面積 = {opening_A:.4f} m² ／ 単位放熱量 = {opening_q:,} kcal/m²h")

st.divider()
remarks = st.text_area("📝 備考欄", value="", height=100, placeholder="特記事項や設計メモなど自由記入")

st.divider()

# ========== 計算実行 ==========
if st.button("🔥 計算実行", type="primary", use_container_width=True):
    faces = {
        "側面": calc_face(Ts, Tw, side_L, side_A, 1.71, epsilon, insulation, lambda_user),
        "上面": calc_face(Ts, Tw, top_L,  top_A,  1.98, epsilon, insulation, lambda_user),
        "底面": calc_face(Ts, Tw, bot_L,  bot_A,  1.98, epsilon, insulation, lambda_user),
    }
    Q_wall = sum(f["Q"] for f in faces.values())
    Q_opening = opening_q * opening_A if has_opening else 0.0
    Q_total = Q_wall + Q_opening
    kW_total = Q_total / 860
    kW_heater = kW_total * safety_factor

    st.subheader("📊 計算結果サマリー")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("炉壁放熱", f"{Q_wall:,.0f} kcal/h")
    c2.metric("開口部放熱", f"{Q_opening:,.0f} kcal/h")
    c3.metric("総放散熱量", f"{kW_total:.3f} kW", delta=f"{Q_total:,.0f} kcal/h")
    c4.metric(f"必要ヒータ容量 (×{safety_factor})", f"{kW_heater:.2f} kW",
              delta=f"+{(kW_heater-kW_total):.2f} kW")

    st.divider()
    st.subheader("📋 各面の詳細")
    df = pd.DataFrame({
        "面": list(faces.keys()),
        "表面積 [m²]": [round(f["A"], 3) for f in faces.values()],
        "外壁温度 T2 [℃]": [round(f["T2"], 1) for f in faces.values()],
        "λ [kcal/m·h·℃]": [round(f["λ"], 5) for f in faces.values()],
        "α(c+r) [kcal/m²h℃]": [round(f["α"], 3) for f in faces.values()],
        "q [kcal/m²h]": [round(f["q"], 1) for f in faces.values()],
        "放散熱量 Q [kcal/h]": [round(f["Q"], 1) for f in faces.values()],
    })
    st.dataframe(df, use_container_width=True, hide_index=True)

    if has_opening:
        st.markdown(f"**🕳️ 開口部**：{opening_dim_text} ／ 総面積 {opening_A:.4f} m² ／ q = {opening_q:,} kcal/m²h ／ **Q = {Q_opening:,.1f} kcal/h**")

    st.subheader("📈 放散熱量の内訳")
    import plotly.express as px
    chart_items = list(faces.keys()) + (["開口部"] if has_opening else [])
    chart_vals = [round(f["Q"], 1) for f in faces.values()] + ([round(Q_opening, 1)] if has_opening else [])
    chart_df = pd.DataFrame({"部位": chart_items, "放散熱量 [kcal/h]": chart_vals})
    fig = px.bar(chart_df, x="部位", y="放散熱量 [kcal/h]",
                 color="部位",
                 color_discrete_sequence=["#FF6B35", "#F7931E", "#FFB347", "#C0392B"],
                 text="放散熱量 [kcal/h]")
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False, height=400)
    st.plotly_chart(fig, use_container_width=True)

    st.info("💡 本計算は理論値です。実機性能を保証するものではありません。")

    # ========== PDF生成 ==========
    st.divider()
    st.subheader("📥 PDF出力")

    def make_pdf():
        buffer = io.BytesIO()
        # フォント登録（ローカルWindowsとクラウドの両方に対応）
        jp_font = 'Helvetica'
        font_paths = [
            'C:/Windows/Fonts/meiryo.ttc',
            '/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf',
            '/usr/share/fonts/truetype/fonts-japanese-gothic.ttf',
            'fonts/ipaexg.ttf',
            'ipaexg.ttf',
        ]
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    pdfmetrics.registerFont(TTFont('Japanese', fp))
                    jp_font = 'Japanese'
                    break
                except:
                    continue

        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                leftMargin=15*mm, rightMargin=15*mm,
                                topMargin=15*mm, bottomMargin=15*mm)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('jp_title', parent=styles['Title'],
                                     fontName=jp_font, fontSize=18, textColor=colors.HexColor("#FF6B35"))
        h2_style = ParagraphStyle('jp_h2', parent=styles['Heading2'],
                                  fontName=jp_font, fontSize=12, textColor=colors.HexColor("#333333"), spaceAfter=6)
        body_style = ParagraphStyle('jp_body', parent=styles['Normal'],
                                    fontName=jp_font, fontSize=10, leading=14)
        small_style = ParagraphStyle('jp_small', parent=styles['Normal'],
                                     fontName=jp_font, fontSize=8, textColor=colors.grey)

        story = []
        story.append(Paragraph("炉体放熱量計算書", title_style))
        story.append(Paragraph("株式会社ヤマト", body_style))
        story.append(Spacer(1, 8*mm))

        story.append(Paragraph("【案件情報】", h2_style))
        info_data = [
            ["作成日", datetime.now().strftime("%Y/%m/%d")],
            ["案件名", project_name or "-"],
            ["お客様", customer or "-"],
            ["担当者", author or "-"],
        ]
        info_tbl = Table(info_data, colWidths=[40*mm, 130*mm])
        info_tbl.setStyle(TableStyle([
            ('FONT', (0,0), (-1,-1), jp_font, 10),
            ('GRID', (0,0), (-1,-1), 0.3, colors.grey),
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#FFF3E0")),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(info_tbl)
        story.append(Spacer(1, 6*mm))

        story.append(Paragraph("【計算条件】", h2_style))
        cond_data = [
            ["炉内温度 Ts", f"{Ts} ℃"],
            ["外気温度 Tw", f"{Tw} ℃"],
            ["輻射率 ε", f"{epsilon}"],
            ["断熱材", insulation if insulation == "カオウール" else f"その他 (λ={lambda_user})"],
            ["安全率", f"×{safety_factor}"],
        ]
        cond_tbl = Table(cond_data, colWidths=[40*mm, 130*mm])
        cond_tbl.setStyle(TableStyle([
            ('FONT', (0,0), (-1,-1), jp_font, 10),
            ('GRID', (0,0), (-1,-1), 0.3, colors.grey),
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#FFF3E0")),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(cond_tbl)
        story.append(Spacer(1, 6*mm))

        story.append(Paragraph("【各面仕様】", h2_style))
        spec_data = [
            ["面", "表面積 [m²]", "厚み [mm]", "Cc"],
            ["側面", f"{side_A:.3f}", f"{side_L}", "1.71"],
            ["上面", f"{top_A:.3f}", f"{top_L}", "1.98"],
            ["底面", f"{bot_A:.3f}", f"{bot_L}", "1.98"],
        ]
        spec_tbl = Table(spec_data, colWidths=[30*mm, 45*mm, 45*mm, 30*mm])
        spec_tbl.setStyle(TableStyle([
            ('FONT', (0,0), (-1,-1), jp_font, 10),
            ('GRID', (0,0), (-1,-1), 0.3, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#FF6B35")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ]))
        story.append(spec_tbl)
        story.append(Spacer(1, 6*mm))

        story.append(Paragraph("【計算結果：炉壁】", h2_style))
        result_data = [["面", "T2 [℃]", "q [kcal/m²h]", "Q [kcal/h]"]]
        for name, f in faces.items():
            result_data.append([name, f"{f['T2']:.1f}", f"{f['q']:.1f}", f"{f['Q']:.1f}"])
        result_tbl = Table(result_data, colWidths=[30*mm, 45*mm, 45*mm, 45*mm])
        result_tbl.setStyle(TableStyle([
            ('FONT', (0,0), (-1,-1), jp_font, 10),
            ('GRID', (0,0), (-1,-1), 0.3, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#FF6B35")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ]))
        story.append(result_tbl)
        story.append(Spacer(1, 6*mm))

        if has_opening:
            story.append(Paragraph("【計算結果：開口部】", h2_style))
            open_data = [
                ["形状", opening_shape],
                ["寸法・個数", opening_dim_text],
                ["総面積", f"{opening_A:.4f} m²"],
                ["単位放熱量 q", f"{opening_q:,} kcal/m²h"],
                ["開口部放熱量 Q", f"{Q_opening:,.1f} kcal/h"],
            ]
            open_tbl = Table(open_data, colWidths=[50*mm, 120*mm])
            open_tbl.setStyle(TableStyle([
                ('FONT', (0,0), (-1,-1), jp_font, 10),
                ('GRID', (0,0), (-1,-1), 0.3, colors.grey),
                ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#FFF3E0")),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
            ]))
            story.append(open_tbl)
            story.append(Spacer(1, 6*mm))

        story.append(Paragraph("【総合計】", h2_style))
        total_data = [
            ["炉壁放熱量", f"{Q_wall:,.1f} kcal/h"],
            ["開口部放熱量", f"{Q_opening:,.1f} kcal/h"],
            ["総放散熱量", f"{Q_total:,.1f} kcal/h  ({kW_total:.3f} kW)"],
            [f"必要ヒータ容量 (×{safety_factor})", f"{kW_heater:.2f} kW"],
        ]
        total_tbl = Table(total_data, colWidths=[60*mm, 110*mm])
        total_tbl.setStyle(TableStyle([
            ('FONT', (0,0), (-1,-1), jp_font, 11),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#FF6B35")),
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#FFF3E0")),
            ('TEXTCOLOR', (1,-1), (1,-1), colors.HexColor("#FF6B35")),
            ('FONTSIZE', (1,-1), (1,-1), 13),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(total_tbl)
        story.append(Spacer(1, 6*mm))

        if remarks.strip():
            story.append(Paragraph("【備考】", h2_style))
            for line in remarks.split("\n"):
                story.append(Paragraph(line if line.strip() else "&nbsp;", body_style))
            story.append(Spacer(1, 6*mm))

        story.append(Spacer(1, 4*mm))
        story.append(Paragraph("※ 本計算は理論値であり、実機性能を保証するものではありません。", small_style))
        story.append(Paragraph("株式会社ヤマト | YAMATO SPIRITS 100", small_style))

        doc.build(story)
        buffer.seek(0)
        return buffer

    pdf_buffer = make_pdf()
    filename = f"furnace_calc_{project_name or 'untitled'}_{datetime.now().strftime('%Y%m%d')}.pdf"
    st.download_button(
        label="📥 PDF計算書をダウンロード",
        data=pdf_buffer,
        file_name=filename,
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )

st.markdown("""
<div class="footer">
    🏭 株式会社ヤマト | YAMATO SPIRITS 100 | Powered by アルハイパー技術
</div>
""", unsafe_allow_html=True)
