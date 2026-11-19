"""
Script to generate the V3 Multibagger Strategy Guide (.docx)
Creates a beautifully formatted, executive-ready technical and operational manual.
"""

import os
from pathlib import Path
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

DOC_PATH = Path("D:/v3_multibagger/V3_Multibagger_Strategy_Guide.docx")

# Palette
COLOR_PRIMARY = RGBColor(15, 37, 55)       # Deep Navy #0F2537
COLOR_SECONDARY = RGBColor(13, 148, 136)   # Teal #0D9488
COLOR_ACCENT = RGBColor(30, 136, 229)      # Vibrant Blue #1E88E5
COLOR_TEXT = RGBColor(51, 65, 85)          # Slate #334155
COLOR_MUTED = RGBColor(100, 116, 139)      # Muted #64748B
HEX_PRIMARY = "0F2537"
HEX_LIGHT_BG = "F8FAFC"
HEX_BORDER = "CBD5E1"
HEX_SUCCESS_BG = "F0FDF4"
HEX_SUCCESS_BORDER = "22C55E"
HEX_INFO_BG = "F0F9FF"
HEX_INFO_BORDER = "0284C7"


def set_cell_margins(cell, top=120, bottom=120, left=150, right=150):
    """Sets internal padding for a table cell (in twips, 20 twips = 1 pt)."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('w:top', top), ('w:bottom', bottom), ('w:left', left), ('w:right', right)]:
        node = OxmlElement(m)
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)


def set_cell_shading(cell, color_hex):
    """Sets background fill color of a cell."""
    shading_xml = f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>'
    cell._tc.get_or_add_tcPr().append(parse_xml(shading_xml))


def set_table_borders(table, color="CBD5E1", sz="4", val="single"):
    """Applies clean subtle borders to a table."""
    tblPr = table._tbl.tblPr
    borders_xml = f"""
    <w:tblBorders {nsdecls("w")}>
        <w:top w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
        <w:left w:val="none"/>
        <w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
        <w:right w:val="none"/>
        <w:insideH w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
        <w:insideV w:val="none"/>
    </w:tblBorders>
    """
    tblPr.append(parse_xml(borders_xml))


def add_callout_box(doc, text, title="KEY TAKEAWAY", box_type="info"):
    """Creates a callout card with a colored left accent border."""
    border_color = HEX_SUCCESS_BORDER if box_type == "success" else HEX_INFO_BORDER
    bg_color = HEX_SUCCESS_BG if box_type == "success" else HEX_INFO_BG

    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    tbl.columns[0].width = Inches(6.5)

    cell = tbl.cell(0, 0)
    set_cell_margins(cell, top=140, bottom=140, left=180, right=180)
    set_cell_shading(cell, bg_color)

    # Set left border only
    tcPr = cell._tc.get_or_add_tcPr()
    borders_xml = f"""
    <w:tcBorders {nsdecls("w")}>
        <w:top w:val="none"/>
        <w:left w:val="single" w:sz="24" w:space="0" w:color="{border_color}"/>
        <w:bottom w:val="none"/>
        <w:right w:val="none"/>
    </w:tcBorders>
    """
    tcPr.append(parse_xml(borders_xml))

    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.15
    run_t = p.add_run(f"📌 {title}: ")
    run_t.bold = True
    run_t.font.name = "Calibri"
    run_t.font.size = Pt(10)
    run_t.font.color.rgb = COLOR_PRIMARY

    run_b = p.add_run(text)
    run_b.font.name = "Calibri"
    run_b.font.size = Pt(10)
    run_b.font.color.rgb = COLOR_TEXT

    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def build_guide_document():
    doc = docx.Document()

    # Set 1-inch margins
    sections = doc.sections
    for s in sections:
        s.top_margin = Inches(1.0)
        s.bottom_margin = Inches(1.0)
        s.left_margin = Inches(1.0)
        s.right_margin = Inches(1.0)
        s.header.is_linked_to_previous = False
        s.footer.is_linked_to_previous = False

        # Header
        hp = s.header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        hrun = hp.add_run("V3 Multibagger Engine — Strategy & Operational Guide")
        hrun.font.name = "Calibri"
        hrun.font.size = Pt(8.5)
        hrun.font.color.rgb = COLOR_MUTED

        # Footer
        fp = s.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        frun = fp.add_run("Confidential Quantitative Strategy Manual | Indian Equities (NSE)")
        frun.font.name = "Calibri"
        frun.font.size = Pt(8.5)
        frun.font.color.rgb = COLOR_MUTED

    # -------------------------------------------------------------------------
    # Document Title Block
    # -------------------------------------------------------------------------
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(4)
    run_title = title_p.add_run("V3 MULTIBAGGER ENGINE")
    run_title.bold = True
    run_title.font.name = "Calibri"
    run_title.font.size = Pt(24)
    run_title.font.color.rgb = COLOR_PRIMARY

    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_before = Pt(0)
    sub_p.paragraph_format.space_after = Pt(16)
    run_sub = sub_p.add_run("A Complete Plain-English Guide to Autonomous Trend-Following, Fundamentals & Taxes in Indian Equities")
    run_sub.font.name = "Calibri"
    run_sub.font.size = Pt(12)
    run_sub.font.color.rgb = COLOR_SECONDARY

    # Metadata pill box
    meta_p = doc.add_paragraph()
    meta_p.paragraph_format.space_before = Pt(0)
    meta_p.paragraph_format.space_after = Pt(16)
    run_m = meta_p.add_run("Author: Quantitative Engineering Team  |  System Version: 3.2 Live  |  Universe: NSE Nifty 500  |  Capital Base: ₹1,00,000 INR")
    run_m.font.name = "Calibri"
    run_m.font.size = Pt(9.5)
    run_m.font.color.rgb = COLOR_MUTED

    # -------------------------------------------------------------------------
    # SECTION 1: EXECUTIVE OVERVIEW
    # -------------------------------------------------------------------------
    h1 = doc.add_heading("1. Executive Overview (The Core Philosophy)", level=1)
    h1.paragraph_format.space_before = Pt(12)
    h1.paragraph_format.space_after = Pt(6)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run(
        "Most retail stock market participants fail not because they pick the wrong companies, but because they behave like day-traders: "
        "they panic at everyday news, book tiny 10% profits prematurely, and hold on to catastrophic 60% losers hoping they bounce back. "
        "The "
    )
    r_bold = p.add_run("V3 Multibagger Engine")
    r_bold.bold = True
    p.add_run(
        " is engineered to do the exact opposite. It acts like a disciplined, unemotional fund manager working 100% on autopilot."
    )

    p2 = doc.add_paragraph()
    p2.paragraph_format.line_spacing = 1.15
    p2.paragraph_format.space_after = Pt(6)
    p2.add_run(
        "The entire philosophy of the engine rests on three fundamental pillars:"
    )

    bullets = [
        ("Catch Big Secular Winners:", " In the Indian stock market, great structural growth stories (like Trent, Dixon Technologies, Bharat Electronics, or Bajaj Finance) do not stop after moving up 20%. They trend relentlessly upward for 3 to 7 years, multiplying capital by 300% to 1,000%+."),
        ("Ignore Daily Noise:", " Indian markets are full of daily volatility, rumors, and news television noise. The V3 system never looks at daily price charts. It evaluates stocks only once a week on Friday evening after the market closes."),
        ("Asymmetric Risk & Reward:", " When a trade is wrong, the engine cuts the loss promptly. When a trade is right, it pyramids (buys more) and holds through 10% to 20% intermediate pullbacks using a wide trailing cushion."),
    ]
    for b_title, b_desc in bullets:
        bp = doc.add_paragraph(style='List Bullet')
        bp.paragraph_format.line_spacing = 1.15
        bp.paragraph_format.space_after = Pt(3)
        rt = bp.add_run(b_title)
        rt.bold = True
        bp.add_run(b_desc)

    add_callout_box(
        doc,
        "The V3 Engine aims for asymmetric payoff: a modest 40% to 60% win-rate produces enormous returns because average winning trades (+160%+) are more than 12 times larger than average losing trades (-13%).",
        title="CORE MATHEMATICAL ADVANTAGE",
        box_type="success"
    )

    # -------------------------------------------------------------------------
    # SECTION 2: STEP-BY-STEP STRATEGY RULES
    # -------------------------------------------------------------------------
    h2 = doc.add_heading("2. Step-by-Step Strategy Rules", level=1)
    h2.paragraph_format.space_before = Pt(14)
    h2.paragraph_format.space_after = Pt(6)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run(
        "Every single decision in the V3 Engine follows objective quantitative formulas. There are no gut feelings, no tips, and no subjective opinions."
    )

    # 2.1 Market Safety Switch
    h2_1 = doc.add_heading("2.1 The Market Safety Switch (Regime Filter)", level=2)
    h2_1.paragraph_format.space_before = Pt(10)
    h2_1.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(4)
    p.add_run(
        "Before the engine even looks at an individual stock, it inspects the broader health of the entire Indian economy by evaluating the "
    )
    p.add_run("Nifty 500 Index (^CRSLDX)").bold = True
    p.add_run(":")

    regime_points = [
        ("The Rule: ", "The Nifty 500 weekly close must be trading strictly above its 30-week Moving Average (MA)."),
        ("Why 30 Weeks? ", "A 30-week moving average equals roughly 150 trading days (7.5 months). It smoothly separates multi-year secular bull markets from bear phases."),
        ("Capital Preservation: ", "If the Nifty 500 drops below its 30-week MA (as happened during the COVID crash in early 2020 or the 2018 midcap crash), the Safety Switch flips to RED. The system stops buying new stocks completely and stays in cash."),
    ]
    for b_title, b_desc in regime_points:
        bp = doc.add_paragraph(style='List Bullet')
        bp.paragraph_format.line_spacing = 1.15
        bp.paragraph_format.space_after = Pt(3)
        bp.add_run(b_title).bold = True
        bp.add_run(b_desc)

    # 2.2 Technical Entry Setup
    h2_2 = doc.add_heading("2.2 Technical Entry Setup (Stage 2 Breakout)", level=2)
    h2_2.paragraph_format.space_before = Pt(10)
    h2_2.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run("If the Market Safety Switch is GREEN, the engine scans the Nifty 500 universe for structural leaders meeting five specific criteria:")

    tech_rules = [
        ("Rule 1: Liquidity & Penny Stock Filter", "Close > ₹50 and 10-Week Average Volume > 500,000 shares", "Filters out illiquid micro-caps, penny stocks, and easily manipulated operators."),
        ("Rule 2: Stage 2 Uptrend Confirmation", "Weekly Close > 30-Week MA", "Ensures we only buy stocks in confirmed primary upward trends, never falling knives."),
        ("Rule 3: Moving Average Upward Slope", "MA30[current] > MA30[4 weeks ago]", "Confirms that the institutional trend is actively accelerating upwards rather than flattening out."),
        ("Rule 4: 52-Week High Breakout", "Current High >= Highest High of prior 52 weeks", "Human intuition mistakenly prefers buying 'cheap' 52-week lows. Real multibaggers consistently break into 52-week new all-time highs with zero overhead supply resistance."),
        ("Rule 5: Institutional Volume Surge", "Breakout Week Volume > 1.5x 10-Week Average Volume", "Ensures the breakout is driven by large domestic and foreign institutions (DIIs/FIIs), not retail hype."),
    ]

    t_tech = doc.add_table(rows=len(tech_rules) + 1, cols=3)
    t_tech.alignment = WD_TABLE_ALIGNMENT.CENTER
    t_tech.autofit = False
    set_table_borders(t_tech)
    col_widths = [Inches(1.8), Inches(2.2), Inches(2.5)]

    headers = ["Criterion", "Quantitative Condition", "Why It Protects You"]
    for i, h in enumerate(headers):
        cell = t_tech.cell(0, i)
        cell.width = col_widths[i]
        set_cell_margins(cell, top=140, bottom=140, left=100, right=100)
        set_cell_shading(cell, HEX_PRIMARY)
        hp = cell.paragraphs[0]
        hp.paragraph_format.space_before = Pt(0)
        hp.paragraph_format.space_after = Pt(0)
        hrun = hp.add_run(h)
        hrun.bold = True
        hrun.font.name = "Calibri"
        hrun.font.size = Pt(9.5)
        hrun.font.color.rgb = RGBColor(255, 255, 255)

    for row_idx, (c1, c2, c3) in enumerate(tech_rules, start=1):
        shading = HEX_LIGHT_BG if row_idx % 2 == 1 else "FFFFFF"
        for col_idx, text in enumerate([c1, c2, c3]):
            cell = t_tech.cell(row_idx, col_idx)
            cell.width = col_widths[col_idx]
            set_cell_margins(cell, top=100, bottom=100, left=100, right=100)
            set_cell_shading(cell, shading)
            cp = cell.paragraphs[0]
            cp.paragraph_format.space_before = Pt(0)
            cp.paragraph_format.space_after = Pt(0)
            cp.paragraph_format.line_spacing = 1.15
            crun = cp.add_run(text)
            crun.font.name = "Calibri"
            crun.font.size = Pt(9)
            crun.font.color.rgb = COLOR_TEXT
            if col_idx == 0:
                crun.bold = True

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # 2.3 Fundamental Gatekeeper
    h2_3 = doc.add_heading("2.3 The Automated Fundamental Gatekeeper (Playwright Engine)", level=2)
    h2_3.paragraph_format.space_before = Pt(10)
    h2_3.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run(
        "Even if a stock makes a stunning technical breakout, it could be a fraudulent company with excessive debt. "
        "The V3 Engine contains an autonomous "
    )
    p.add_run("Playwright headless browser").bold = True
    p.add_run(" that launches in the background and navigates to Screener.in to audit company fundamentals:")

    fund_bullets = [
        ("ROCE > 15% (Return on Capital Employed): ", "Measures how efficiently management generates profit from every Rupee invested. Companies with ROCE > 15% have strong economic moats and pricing power."),
        ("Debt to Equity < 1.0: ", "Ensures the company is not over-leveraged. Excessive debt kills companies during economic downturns; V3 only buys financially resilient balance sheets."),
        ("Promoter Pledging < 5%: ", "Promoters who pledge their personal shares to borrow money pose extreme risk of margin call crashes. V3 strictly rejects any company where promoters have pledged more than 5% of their holdings."),
    ]
    for b_title, b_desc in fund_bullets:
        bp = doc.add_paragraph(style='List Bullet')
        bp.paragraph_format.line_spacing = 1.15
        bp.paragraph_format.space_after = Pt(3)
        bp.add_run(b_title).bold = True
        bp.add_run(b_desc)

    add_callout_box(
        doc,
        "A stock must pass BOTH the Stage 2 technical breakout AND all three Playwright fundamental rules. If either fails, the stock is automatically skipped.",
        title="DUAL-GATE VERIFICATION",
        box_type="info"
    )

    # 2.4 Sizing & Pyramiding
    h2_4 = doc.add_heading("2.4 Position Sizing & Pyramiding (Adding to Winners)", level=2)
    h2_4.paragraph_format.space_before = Pt(10)
    h2_4.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(4)
    p.add_run("Starting from ₹1,00,000 INR virtual capital, the engine manages risk with strict allocation ceilings:")

    size_bullets = [
        ("Starter Position (10% / ₹10,000): ", "When a stock triggers a buy, the engine allocates exactly 10% of portfolio capital. This allows holding up to 10 distinct high-conviction winners simultaneously."),
        ("Pyramid Add-on (+10% / ₹10,000): ", "If the stock advances +20% above its initial entry price, the engine buys a second 10% tranche at the current market price. This increases exposure strictly on proven winning trades using house money."),
        ("Max Allocation Ceiling (20%): ", "No single company is ever permitted to exceed 20% of total portfolio capital, safeguarding against catastrophic single-stock collapses."),
    ]
    for b_title, b_desc in size_bullets:
        bp = doc.add_paragraph(style='List Bullet')
        bp.paragraph_format.line_spacing = 1.15
        bp.paragraph_format.space_after = Pt(3)
        bp.add_run(b_title).bold = True
        bp.add_run(b_desc)

    # 2.5 Exit & Trailing Stop
    h2_5 = doc.add_heading("2.5 The Exit & Trailing Stop Rule (Surviving Secular Corrections)", level=2)
    h2_5.paragraph_format.space_before = Pt(10)
    h2_5.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run(
        "Standard retail stop losses are too tight (typically 5% or 8%). In a secular bull run, a great stock regularly pulls back 10% to 15% to shake out nervous traders before surging higher. "
        "The V3 Engine uses a wide, patient trailing stop: "
    )
    p.add_run("Sell ONLY if the Friday weekly close drops 15% below the 30-week Moving Average (Close < 0.85 * MA30).").bold = True

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run(
        "As the stock climbs higher over months and years, the 30-week MA naturally rises beneath it, locking in hundreds of percentage points in accumulated profit while giving the company room to breathe."
    )

    # -------------------------------------------------------------------------
    # SECTION 3: CHARGES, SLIPPAGE & INDIAN TAXES
    # -------------------------------------------------------------------------
    h3 = doc.add_heading("3. Complete Breakdown of Charges, Slippage & Indian Taxes", level=1)
    h3.paragraph_format.space_before = Pt(14)
    h3.paragraph_format.space_after = Pt(6)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run(
        "A quantitative strategy that looks profitable on paper can fail in the real world if it ignores transaction fees and taxes. "
        "The V3 Multibagger Engine has been designed from day one with realistic Indian equity market frictions."
    )

    # 3.1 Coded Friction
    h3_1 = doc.add_heading("3.1 Frictional Costs Coded in the System", level=2)
    h3_1.paragraph_format.space_before = Pt(10)
    h3_1.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(4)
    p.add_run("Inside ")
    p.add_run("config.py").bold = True
    p.add_run(", ")
    p.add_run("v3_backtest.py").bold = True
    p.add_run(", and ")
    p.add_run("v3_weekly_engine.py").bold = True
    p.add_run(", the engine applies: ")
    p.add_run("TRANSACTION_COST_PCT = 0.0015 (0.15% per trade)").bold = True
    p.add_run(
        ". This means on every entry, pyramid addition, and exit, ₹15 per ₹10,000 trade (or ₹150 per ₹1,00,000 turnover) is automatically deducted to model broker fees, statutory levies, and bid-ask slippage."
    )

    # 3.2 Real-World Indian Equity Delivery Cost Table
    h3_2 = doc.add_heading("3.2 Real-World Indian Equity Delivery Cost Structure", level=2)
    h3_2.paragraph_format.space_before = Pt(10)
    h3_2.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run(
        "When moving this engine from virtual paper trading to real money with standard Indian discount brokers (e.g., Zerodha, Groww, AngelOne), "
        "the actual statutory cost breakdown is detailed below:"
    )

    charge_rows = [
        ("Brokerage Fee", "₹0 (Zero)", "₹0 (Zero)", "Standard discount brokers charge zero brokerage for equity delivery holdings."),
        ("Securities Transaction Tax (STT)", "0.10%", "0.10%", "Levied by the Government of India on both purchase and sale turnover."),
        ("Exchange Transaction Charge", "0.00297%", "0.00297%", "Charged by the National Stock Exchange (NSE) per traded value."),
        ("SEBI Turnover Fee", "0.0001% (₹10/Cr)", "0.0001% (₹10/Cr)", "Regulatory fee collected on behalf of SEBI."),
        ("Stamp Duty (Govt of India)", "0.015% (₹15/Lakh)", "Nil (₹0)", "State stamp duty collected only on the buy side."),
        ("Goods & Services Tax (GST)", "18% on fees", "18% on fees", "18% GST applied on (Brokerage + Exchange Charges + SEBI Fees)."),
        ("Depository (DP) Charges", "Nil (₹0)", "₹13.50 + GST (₹15.93)", "Flat per-stock debit charge by CDSL/NSDL upon selling, regardless of quantity."),
        ("Effective Combined Friction", "~0.118%", "~0.119% + DP", "Matches our coded 0.15% model with extra margin for execution slippage!"),
    ]

    t_charge = doc.add_table(rows=len(charge_rows) + 1, cols=4)
    t_charge.alignment = WD_TABLE_ALIGNMENT.CENTER
    t_charge.autofit = False
    set_table_borders(t_charge)
    c_widths = [Inches(1.8), Inches(1.1), Inches(1.3), Inches(2.3)]

    c_headers = ["Fee / Levy Component", "Buy Side Rate", "Sell Side Rate", "Statutory Explanation"]
    for i, h in enumerate(c_headers):
        cell = t_charge.cell(0, i)
        cell.width = c_widths[i]
        set_cell_margins(cell, top=140, bottom=140, left=80, right=80)
        set_cell_shading(cell, HEX_PRIMARY)
        hp = cell.paragraphs[0]
        hp.paragraph_format.space_before = Pt(0)
        hp.paragraph_format.space_after = Pt(0)
        hrun = hp.add_run(h)
        hrun.bold = True
        hrun.font.name = "Calibri"
        hrun.font.size = Pt(9.5)
        hrun.font.color.rgb = RGBColor(255, 255, 255)

    for row_idx, (c1, c2, c3, c4) in enumerate(charge_rows, start=1):
        shading = HEX_LIGHT_BG if row_idx % 2 == 1 else "FFFFFF"
        if row_idx == len(charge_rows):
            shading = HEX_SUCCESS_BG
        for col_idx, text in enumerate([c1, c2, c3, c4]):
            cell = t_charge.cell(row_idx, col_idx)
            cell.width = c_widths[col_idx]
            set_cell_margins(cell, top=90, bottom=90, left=80, right=80)
            set_cell_shading(cell, shading)
            cp = cell.paragraphs[0]
            cp.paragraph_format.space_before = Pt(0)
            cp.paragraph_format.space_after = Pt(0)
            cp.paragraph_format.line_spacing = 1.15
            crun = cp.add_run(text)
            crun.font.name = "Calibri"
            crun.font.size = Pt(8.5)
            crun.font.color.rgb = COLOR_TEXT
            if col_idx == 0 or row_idx == len(charge_rows):
                crun.bold = True

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # 3.3 Indian Capital Gains Taxes
    h3_3 = doc.add_heading("3.3 Indian Capital Gains Tax Framework (2026 Updated Rules)", level=2)
    h3_3.paragraph_format.space_before = Pt(10)
    h3_3.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run(
        "Taxes represent the single largest drag on investment compounding. Under the current Indian income tax rules (updated post-July 2024 Union Budget):"
    )

    tax_bullets = [
        ("Short-Term Capital Gains (STCG — 20%): ", "Applies to listed equity shares sold within 12 months (1 year or less). Flat tax of 20% on all net realized gains, with zero exemption limit."),
        ("Long-Term Capital Gains (LTCG — 12.5%): ", "Applies to listed equity shares held for more than 12 months. Tax rate drops to 12.5% flat."),
        ("₹1,25,000 Annual Tax-Free Exemption: ", "Under Section 112A, the first ₹1,25,000 of LTCG profit realized in every financial year is completely tax-free!"),
    ]
    for b_title, b_desc in tax_bullets:
        bp = doc.add_paragraph(style='List Bullet')
        bp.paragraph_format.line_spacing = 1.15
        bp.paragraph_format.space_after = Pt(3)
        bp.add_run(b_title).bold = True
        bp.add_run(b_desc)

    add_callout_box(
        doc,
        "WHY V3 SAVES MASSIVE TAXES: A high-frequency swing trader holding positions for 2 weeks pays 20% STCG every year on profits, triggering tax events 50+ times and draining capital. "
        "The V3 Multibagger Engine holds structural winners for 100 to 220 weeks (2 to 4+ years). During those years, capital compounds completely tax-deferred! "
        "When an exit finally occurs, the tax rate drops from 20% to 12.5% (a 37.5% relative tax cut), plus the first ₹1.25 Lakh profit per year is completely tax-free.",
        title="THE MULTIBAGGER TAX ADVANTAGE",
        box_type="success"
    )

    # -------------------------------------------------------------------------
    # SECTION 4: 10-YEAR BACKTEST SUMMARY & SYSTEM ARCHITECTURE
    # -------------------------------------------------------------------------
    h4 = doc.add_heading("4. 10-Year Backtest Summary & Autonomous Architecture", level=1)
    h4.paragraph_format.space_before = Pt(14)
    h4.paragraph_format.space_after = Pt(6)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run(
        "The strategy was rigorously backtested across 10+ years of weekly market history (2014 to 2026) encompassing major market regimes: "
        "the 2014-2017 Modi bull run, the 2018 midcap crash, the 2020 COVID crash, and the 2021-2026 secular growth phase."
    )

    # Metrics Summary Table
    metric_rows = [
        ("Initial Capital", "₹1,00,000 INR", "Starting bankroll"),
        ("Final Ending Equity", "₹17,93,330 INR", "~17.9x capital growth over period"),
        ("Strategy CAGR", "27.20% per year", "Compound Annual Growth Rate"),
        ("Benchmark (Nifty 500) CAGR", "10.92% per year", "Outperformed index by +16.28% Alpha per year!"),
        ("Win Rate", "60.5%", "23 Winning Trades / 15 Losing Trades"),
        ("Profit Factor", "16.74", "Gross Profit / Gross Loss ratio"),
        ("Win / Loss Ratio", "12.12x", "Average Win (+163.9%) vs Average Loss (-13.5%)"),
        ("Pyramided Trades", "29 Positions", "Successfully added +10% on +20% price gain"),
        ("Maximum Drawdown", "-37.01%", "Controlled peak-to-trough decline (managed via Regime Filter)"),
    ]

    t_metric = doc.add_table(rows=len(metric_rows) + 1, cols=3)
    t_metric.alignment = WD_TABLE_ALIGNMENT.CENTER
    t_metric.autofit = False
    set_table_borders(t_metric)
    m_widths = [Inches(2.2), Inches(1.8), Inches(2.5)]

    m_headers = ["Performance Metric", "Strategy Result", "Institutional Context"]
    for i, h in enumerate(m_headers):
        cell = t_metric.cell(0, i)
        cell.width = m_widths[i]
        set_cell_margins(cell, top=140, bottom=140, left=100, right=100)
        set_cell_shading(cell, HEX_PRIMARY)
        hp = cell.paragraphs[0]
        hp.paragraph_format.space_before = Pt(0)
        hp.paragraph_format.space_after = Pt(0)
        hrun = hp.add_run(h)
        hrun.bold = True
        hrun.font.name = "Calibri"
        hrun.font.size = Pt(9.5)
        hrun.font.color.rgb = RGBColor(255, 255, 255)

    for row_idx, (c1, c2, c3) in enumerate(metric_rows, start=1):
        shading = HEX_LIGHT_BG if row_idx % 2 == 1 else "FFFFFF"
        for col_idx, text in enumerate([c1, c2, c3]):
            cell = t_metric.cell(row_idx, col_idx)
            cell.width = m_widths[col_idx]
            set_cell_margins(cell, top=90, bottom=90, left=100, right=100)
            set_cell_shading(cell, shading)
            cp = cell.paragraphs[0]
            cp.paragraph_format.space_before = Pt(0)
            cp.paragraph_format.space_after = Pt(0)
            cp.paragraph_format.line_spacing = 1.15
            crun = cp.add_run(text)
            crun.font.name = "Calibri"
            crun.font.size = Pt(9)
            crun.font.color.rgb = COLOR_TEXT
            if col_idx == 0:
                crun.bold = True

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # Top Multibaggers Table
    h4_1 = doc.add_heading("Top Structural Multibagger Trades Captured", level=2)
    h4_1.paragraph_format.space_before = Pt(10)
    h4_1.paragraph_format.space_after = Pt(4)

    winners = [
        ("ATGL.NS", "2020-09-04", "2023-02-03", "₹187.59", "₹1,620.13", "+678.5%", "126 wks (2.4 yrs)", "YES"),
        ("ACUTAAS.NS", "2023-05-19", "2026-11-20", "₹576.80", "₹3,947.30", "+575.4%", "183 wks (3.5 yrs)", "YES"),
        ("BDL.NS", "2020-07-10", "2024-10-25", "₹189.07", "₹1,025.69", "+425.0%", "224 wks (4.3 yrs)", "YES"),
        ("ADANIENT.NS", "2020-08-28", "2023-01-27", "₹287.42", "₹2,756.43", "+392.3%", "126 wks (2.4 yrs)", "YES"),
        ("BEL.NS", "2022-08-05", "2026-11-20", "₹87.88", "₹401.40", "+351.7%", "224 wks (4.3 yrs)", "YES"),
        ("BAJFINANCE.NS", "2016-04-22", "2020-03-20", "₹67.25", "₹287.39", "+282.6%", "204 wks (3.9 yrs)", "YES"),
        ("AARTIIND.NS", "2017-12-29", "2022-05-06", "₹267.55", "₹783.30", "+190.9%", "227 wks (4.4 yrs)", "YES"),
        ("BAJAJFINSV.NS", "2016-07-01", "2020-03-20", "₹234.38", "₹621.38", "+132.5%", "194 wks (3.7 yrs)", "YES"),
    ]

    t_win = doc.add_table(rows=len(winners) + 1, cols=8)
    t_win.alignment = WD_TABLE_ALIGNMENT.CENTER
    t_win.autofit = False
    set_table_borders(t_win)
    w_widths = [Inches(1.1), Inches(0.8), Inches(0.8), Inches(0.7), Inches(0.8), Inches(0.8), Inches(0.9), Inches(0.6)]

    w_headers = ["Ticker", "Entry", "Exit", "Buy (₹)", "Exit (₹)", "Return %", "Holding Duration", "Pyr?"]
    for i, h in enumerate(w_headers):
        cell = t_win.cell(0, i)
        cell.width = w_widths[i]
        set_cell_margins(cell, top=120, bottom=120, left=60, right=60)
        set_cell_shading(cell, HEX_PRIMARY)
        hp = cell.paragraphs[0]
        hp.paragraph_format.space_before = Pt(0)
        hp.paragraph_format.space_after = Pt(0)
        hrun = hp.add_run(h)
        hrun.bold = True
        hrun.font.name = "Calibri"
        hrun.font.size = Pt(8.5)
        hrun.font.color.rgb = RGBColor(255, 255, 255)

    for row_idx, row_data in enumerate(winners, start=1):
        shading = HEX_LIGHT_BG if row_idx % 2 == 1 else "FFFFFF"
        for col_idx, text in enumerate(row_data):
            cell = t_win.cell(row_idx, col_idx)
            cell.width = w_widths[col_idx]
            set_cell_margins(cell, top=80, bottom=80, left=60, right=60)
            set_cell_shading(cell, shading)
            cp = cell.paragraphs[0]
            cp.paragraph_format.space_before = Pt(0)
            cp.paragraph_format.space_after = Pt(0)
            crun = cp.add_run(text)
            crun.font.name = "Calibri"
            crun.font.size = Pt(8)
            crun.font.color.rgb = COLOR_TEXT
            if col_idx == 0 or col_idx == 5:
                crun.bold = True

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # 4.2 System Architecture
    h4_2 = doc.add_heading("4.2 Autonomous System Architecture (How It Works 100% Hands-Free)", level=2)
    h4_2.paragraph_format.space_before = Pt(10)
    h4_2.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.space_after = Pt(6)
    p.add_run("The entire V3 ecosystem is wired together into an autonomous pipeline:")

    arch_points = [
        ("Windows Task Scheduler (Every Friday @ 16:00 IST): ", "Wakes up automatically post-market close and executes 'v3_weekly_engine.py --scan --tickers 150'."),
        ("Local SQLite Database (v3_multibagger_ledger.db): ", "Maintains the authoritative ledger of cash, open positions, trailing stop prices, trade logs, and weekly snapshots."),
        ("Headless Playwright Browser: ", "Navigates to Screener.in in real-time, scraping ROCE, Debt/Equity, and Pledged holdings for any stock triggering a technical breakout."),
        ("Automated Telegram Alerts: ", "Formats an HTML summary report and sends it immediately to your private Telegram chat, detailing new buys, trailing stop exits, and live portfolio NAV."),
        ("Automated GitHub Sync: ", "At the end of each Friday scan, the engine automatically commits and pushes the updated database ledger to your remote GitHub repository."),
        ("Live Streamlit Cloud Dashboard (v3_dashboard.py): ", "Connects to the database and renders clean KPI metric cards, active positions tables, and Plotly asset allocation charts accessible from any browser or phone."),
    ]
    for b_title, b_desc in arch_points:
        bp = doc.add_paragraph(style='List Bullet')
        bp.paragraph_format.line_spacing = 1.15
        bp.paragraph_format.space_after = Pt(3)
        bp.add_run(b_title).bold = True
        bp.add_run(b_desc)

    doc.save(DOC_PATH)
    print(f"Document successfully created at: {DOC_PATH.resolve()}")


if __name__ == "__main__":
    build_guide_document()
