import streamlit as st
import numpy as np
import pandas as pd
import math
import datetime
import io
import os
from scipy.optimize import brentq
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ===== 日本語フォント登録 =====
FONT_PATH = os.path.join(os.path.dirname(__file__), "ipaexg.ttf")
JP_FONT = "IPAexGothic"
try:
    pdfmetrics.registerFont(TTFont(JP_FONT, FONT_PATH))
    FONT_LOADED = True
except Exception as e:
    FONT_LOADED = False
    st.warning(f"日本語フォント読み込み失敗: {e}")

# ===== ページ設定 =====
st.set_page_config(
    page_title="YAMATO 炉体熱計算ツール",
    page_icon="🔥",
    layout="wide"
)

# ===== カスタムCSS =====
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #FF6B35 0%, #F7931E 100%);
        padding: 2rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
    }
    .main-header h1 { color: white; margin: 0; font-size: 2.2rem; }
    .main-header p { color: white; margin: 0.5rem 0 0 0; }
    .stMetric { background-color: #FFF5EE; padding: 1rem; border-radius: 8px; border-left: 4px solid #FF6B35; }
</style>
""", unsafe_allow_html=True)

# ===== パスワード認証 =====
def check_password():
    def password_entered():
        if st.session_state["password"] == "yamato5360":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.markdown("### 🔒 YAMATO 炉体熱計算ツール")
        st.text_input("パスワードを入力してください", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.markdown("### 🔒 YAMATO 炉体熱計算ツール")
        st.text_input("パスワードを入力してください", type="password", on_change=password_entered, key="password")
        st.error("😕 パスワードが違います")
        return False
    else:
        return True

if not check_password():
    st.stop()

# ===== ヘッダー =====
st.markdown("""
<div class='main-header'>
    <h1>🔥 YAMATO 炉体熱計算ツール</h1>
    <p>1層断熱・3面合算＋開口部 / 放散熱量＆ヒータ容量算出</p>
</div>
""", unsafe_allow_html=True)

# ===== サイドバー =====
with st.sidebar:
    st.header("📋 案件情報")
    project_name = st.text_input("案件名", "")
    customer = st.text_input("お客様名", "")
    author = st.text_input("担当者", "あっくん")

    st.header("🌡️ 共通条件")
    Ts = st.number_input("炉内温度 Ts [℃]", value=750, min_value=0, max_value=1500, step=10)
    Tw = st.number_input("外気温度 Tw [℃]", value=20, min_value=-20, max_value=50, step=1)

    st.header("⚙️ 物性値")
    epsilon = st.number_input("輻射率 ε", value=0.5, min_value=0.0, max_value=1.0, step=0.05,
                              help="SS銀ペ塗装の標準値: 0.5")
    insulation = st.selectbox("断熱材", ["カオウール", "その他（手入力）"])
    lambda_user = None
    if insulation == "その他（手入力）":
        lambda_user = st.number_input("熱伝導率 λ [kcal/m·h·℃]", value=0.10, min_value=0.0, max_value=1.0, step=0.01)

    safety_factor = st.slider("🛡️ 安全率", min_value=1.0, max_value=2.5, value=1.5, step=0.1)

# ===== 計算関数 =====
def lambda_kaowool(Tm):
    return (0.0247 + 1.14e-4 * Tm + 7.55e-8 * Tm**2) / 1.1628

def calc_face(Ts, Tw, L_mm, A, Cc, epsilon, insulation, lambda_user):
    L = L_mm / 1000.0
    def lambda_calc(Tm):
        if insulation == "カオウール":
            return lambda_kaowool(Tm)
        return lambda_user
    def residual(T2):
        dt = T2 - Tw
        Tm = (Ts + T2) / 2.0
        lam = lambda_calc(Tm)
        qr = epsilon * 4.88 * (((273 + T2) / 100)**4 - ((273 + Tw) / 100)**4)
        alpha_r = qr / dt
        alpha_c = Cc * dt**0.25
        q_conv = (alpha_r + alpha_c) * dt
        q_cond = lam * (Ts - T2) / L
        return q_cond - q_conv
    T2 = brentq(residual, Tw + 0.1, Ts - 0.1, xtol=1e-4)
    dt = T2 - Tw
    Tm = (Ts + T2) / 2.0
    lam = lambda_calc(Tm)
    qr = epsilon * 4.88 * (((273 + T2) / 100)**4 - ((273 + Tw) / 100)**4)
    alpha_r = qr / dt
    alpha_c = Cc * dt**0.25
    q = (alpha_r + alpha_c) * dt
    Q = q * A
    return {"T2": T2, "Tm": Tm, "λ": lam, "αr": alpha_r, "αc": alpha_c,
            "α": alpha_r + alpha_c, "q": q, "Q": Q, "A": A, "L": L_mm}

# ===== 炉体寸法 =====
st.markdown("## 📐 炉体寸法")
shape = st.radio("炉の形状", ["角型", "円筒型", "手入力（特殊形状）"], horizontal=True)

if shape == "角型":
    c1, c2, c3 = st.columns(3)
    with c1:
        W = st.number_input("幅 W [mm]", value=600, min_value=0, step=10)
    with c2:
        D = st.number_input("奥行 D [mm]", value=440, min_value=0, step=10)
    with c3:
        H = st.number_input("高さ H [mm]", value=500, min_value=0, step=10)
    side_A = 2 * (W + D) * H / 1_000_000
    top_A = W * D / 1_000_000
    bot_A = W * D / 1_000_000
    st.success(f"✅ 自動算出：側面 = {side_A:.3f} m² / 上面 = {top_A:.3f} m² / 底面 = {bot_A:.3f} m²")
elif shape == "円筒型":
    c1, c2 = st.columns(2)
    with c1:
        Phi = st.number_input("外径 Φ [mm]", value=500, min_value=0, step=10)
    with c2:
        H = st.number_input("高さ H [mm]", value=2000, min_value=0, step=10)
    side_A = math.pi * Phi * H / 1_000_000
    top_A = math.pi * (Phi / 2)**2 / 1_000_000
    bot_A = math.pi * (Phi / 2)**2 / 1_000_000
    st.success(f"✅ 自動算出：側面 = {side_A:.3f} m² / 上面 = {top_A:.3f} m² / 底面 = {bot_A:.3f} m²")
else:
    c1, c2, c3 = st.columns(3)
    with c1:
        side_A = st.number_input("側面 面積 [m²]", value=1.0, min_value=0.0, step=0.01)
    with c2:
        top_A = st.number_input("上面 面積 [m²]", value=0.3, min_value=0.0, step=0.01)
    with c3:
        bot_A = st.number_input("底面 面積 [m²]", value=0.3, min_value=0.0, step=0.01)

# ===== 断熱材厚み =====
st.markdown("## 🧱 各面の断熱材厚み")
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("### 🟪 側面")
    side_L = st.number_input("厚み [mm]", value=50, min_value=0, step=5, key="side_L")
    st.caption("Cc = 1.71")
with c2:
    st.markdown("### ⬆️ 上面")
    top_L = st.number_input("厚み [mm]", value=120, min_value=0, step=5, key="top_L")
    st.caption("Cc = 1.98")
with c3:
    st.markdown("### ⬇️ 底面")
    bot_L = st.number_input("厚み [mm]", value=100, min_value=0, step=5, key="bot_L")
    st.caption("Cc = 1.98")

# ===== 開口部 =====
st.markdown("## 🕳️ 開口部（炉口）")
has_opening = st.checkbox("開口部あり", value=True)
opening_A = 0.0
opening_count = 0
opening_size = ""
q_open = 12000
if has_opening:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        op_shape = st.radio("形状", ["円形", "角型"], horizontal=True)
    with c2:
        if op_shape == "円形":
            op_phi = st.number_input("Φ [mm]", value=300, min_value=0, step=10)
            opening_unit_A = math.pi * (op_phi / 2)**2 / 1_000_000
            opening_size = f"Φ{op_phi}mm"
        else:
            op_w = st.number_input("幅 [mm]", value=300, min_value=0, step=10)
            op_d = st.number_input("奥行 [mm]", value=300, min_value=0, step=10)
            opening_unit_A = op_w * op_d / 1_000_000
            opening_size = f"{op_w}×{op_d}mm"
    with c3:
        opening_count = st.number_input("個数", value=1, min_value=0, step=1)
    with c4:
        q_open = st.number_input("単位放熱量 [kcal/m²h]", value=12000, min_value=0, step=500)
    opening_A = opening_unit_A * opening_count
    st.success(f"✅ 開口部合計面積 = {opening_A:.4f} m²")

# ===== 備考欄 =====
st.markdown("## 📝 備考")
remarks = st.text_area("備考欄（PDFに記載されます）", value="", height=100)

# ===== 計算実行 =====
if st.button("🔥 計算実行", type="primary", use_container_width=True):
    faces = {
        "側面": calc_face(Ts, Tw, side_L, side_A, 1.71, epsilon, insulation, lambda_user),
        "上面": calc_face(Ts, Tw, top_L, top_A, 1.98, epsilon, insulation, lambda_user),
        "底面": calc_face(Ts, Tw, bot_L, bot_A, 1.98, epsilon, insulation, lambda_user),
    }
    Q_wall = sum(f["Q"] for f in faces.values())
    Q_opening = q_open * opening_A
    Q_total = Q_wall + Q_opening
    kW_total = Q_total / 860
    kW_heater = kW_total * safety_factor

    st.markdown("## 📊 計算結果サマリー")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("炉壁放散熱量", f"{Q_wall:,.1f} kcal/h")
    c2.metric("開口部放散熱量", f"{Q_opening:,.1f} kcal/h")
    c3.metric("総放散熱量", f"{kW_total:.3f} kW")
    c4.metric(f"必要ヒータ容量 (×{safety_factor})", f"{kW_heater:.2f} kW")

    st.markdown("## 📋 各面の詳細")
    df = pd.DataFrame({
        "面": list(faces.keys()),
        "表面積 [m²]": [round(f["A"], 4) for f in faces.values()],
        "厚み [mm]": [f["L"] for f in faces.values()],
        "T2 [℃]": [round(f["T2"], 1) for f in faces.values()],
        "λ": [round(f["λ"], 5) for f in faces.values()],
        "α(c+r)": [round(f["α"], 3) for f in faces.values()],
        "q [kcal/m²h]": [round(f["q"], 1) for f in faces.values()],
        "Q [kcal/h]": [round(f["Q"], 1) for f in faces.values()],
    })
    st.dataframe(df, hide_index=True, use_container_width=True)

    # ===== PDF生成 =====
    def make_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm,
                                leftMargin=20*mm, rightMargin=20*mm)
        font_name = JP_FONT if FONT_LOADED else "Helvetica"
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("title", parent=styles["Title"], fontName=font_name,
                                     fontSize=18, textColor=colors.HexColor("#FF6B35"), alignment=1)
        h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=font_name, fontSize=12,
                            textColor=colors.HexColor("#FF6B35"), spaceBefore=12, spaceAfter=6)
        normal = ParagraphStyle("normal", parent=styles["Normal"], fontName=font_name, fontSize=10)

        story = []
        story.append(Paragraph("炉体熱計算書", title_style))
        story.append(Spacer(1, 8*mm))

        # 案件情報
        story.append(Paragraph("■ 案件情報", h2))
        info_data = [
            ["作成日", datetime.date.today().strftime("%Y/%m/%d")],
            ["案件名", project_name or "(未入力)"],
            ["お客様名", customer or "(未入力)"],
            ["担当者", author or "(未入力)"],
        ]
        t = Table(info_data, colWidths=[40*mm, 100*mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), font_name),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#FFF5EE")),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(t)

        # 計算条件
        story.append(Paragraph("■ 計算条件", h2))
        cond_data = [
            ["炉内温度 Ts", f"{Ts} ℃"],
            ["外気温度 Tw", f"{Tw} ℃"],
            ["輻射率 ε", f"{epsilon}"],
            ["断熱材", insulation + (f" (λ={lambda_user})" if lambda_user else "")],
            ["安全率", f"×{safety_factor}"],
        ]
        t = Table(cond_data, colWidths=[40*mm, 100*mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), font_name),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#FFF5EE")),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(t)

        # 面仕様
        story.append(Paragraph("■ 面仕様", h2))
        face_spec = [["面", "面積 [m²]", "厚み [mm]", "Cc"]]
        for name, f, cc in zip(faces.keys(), faces.values(), [1.71, 1.98, 1.98]):
            face_spec.append([name, f"{f['A']:.3f}", f"{f['L']}", f"{cc}"])
        t = Table(face_spec, colWidths=[30*mm, 35*mm, 35*mm, 25*mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), font_name),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#FF6B35")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("ALIGN", (1,1), (-1,-1), "RIGHT"),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(t)

        # 計算結果（炉壁）
        story.append(Paragraph("■ 計算結果：炉壁", h2))
        wall_result = [["面", "T2 [℃]", "q [kcal/m²h]", "Q [kcal/h]"]]
        for name, f in faces.items():
            wall_result.append([name, f"{f['T2']:.1f}", f"{f['q']:.1f}", f"{f['Q']:.1f}"])
        t = Table(wall_result, colWidths=[30*mm, 35*mm, 45*mm, 35*mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), font_name),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#FF6B35")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("ALIGN", (1,1), (-1,-1), "RIGHT"),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(t)

        # 開口部
        if has_opening and opening_A > 0:
            story.append(Paragraph("■ 計算結果：開口部", h2))
            op_result = [
                ["形状", op_shape],
                ["サイズ", f"{opening_size} × {opening_count}個"],
                ["合計面積", f"{opening_A:.4f} m²"],
                ["単位放熱量 q", f"{q_open:,} kcal/m²h"],
                ["放散熱量 Q", f"{Q_opening:,.1f} kcal/h"],
            ]
            t = Table(op_result, colWidths=[40*mm, 100*mm])
            t.setStyle(TableStyle([
                ("FONTNAME", (0,0), (-1,-1), font_name),
                ("FONTSIZE", (0,0), (-1,-1), 10),
                ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#FFF5EE")),
                ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("LEFTPADDING", (0,0), (-1,-1), 6),
                ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ]))
            story.append(t)

        # 総合計
        story.append(PageBreak())
        story.append(Paragraph("■ 総合計", h2))
        total_data = [
            ["炉壁放散熱量", f"{Q_wall:,.1f} kcal/h"],
            ["開口部放散熱量", f"{Q_opening:,.1f} kcal/h"],
            ["総放散熱量", f"{Q_total:,.1f} kcal/h ({kW_total:.3f} kW)"],
            [f"必要ヒータ容量 (×{safety_factor})", f"{kW_heater:.2f} kW"],
        ]
        t = Table(total_data, colWidths=[60*mm, 80*mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), font_name),
            ("FONTSIZE", (0,0), (-1,-1), 11),
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#FFF5EE")),
            ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#FF6B35")),
            ("TEXTCOLOR", (0,-1), (-1,-1), colors.white),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("RIGHTPADDING", (0,0), (-1,-1), 8),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(t)

        # 備考
        if remarks:
            story.append(Paragraph("■ 備考", h2))
            story.append(Paragraph(remarks.replace("\n", "<br/>"), normal))

        # フッター
        story.append(Spacer(1, 15*mm))
        footer_style = ParagraphStyle("footer", parent=normal, fontName=font_name,
                                       fontSize=8, textColor=colors.grey, alignment=1)
        story.append(Paragraph("※本計算は理論値です。実機性能を保証するものではありません。", footer_style))
        story.append(Paragraph("株式会社ヤマト | YAMATO SPIRITS 100", footer_style))

        doc.build(story)
        buffer.seek(0)
        return buffer

    pdf_buffer = make_pdf()
    fname = f"furnace_calc_{project_name or 'untitled'}_{datetime.date.today().strftime('%Y%m%d')}.pdf"
    st.download_button(
        label="📥 PDF計算書をダウンロード",
        data=pdf_buffer,
        file_name=fname,
        mime="application/pdf",
        use_container_width=True,
    )
    st.info("💡 本計算は理論値です。実機性能を保証するものではありません。")

st.markdown("---")
st.markdown("<div style='text-align:center;color:gray;font-size:0.85rem;'>🏭 株式会社ヤマト | YAMATO SPIRITS 100</div>", unsafe_allow_html=True)
