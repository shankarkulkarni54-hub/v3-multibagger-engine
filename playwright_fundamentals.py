"""
V3 Multibagger Engine - Playwright Fundamental Engine
Asynchronous browser automation using Playwright to extract core institutional quality
metrics from Screener.in: ROCE (%), Debt to Equity, and Pledged Percentage (%).
"""

import re
import asyncio
import logging
from typing import Dict, Optional, Tuple
from playwright.async_api import async_playwright

logger = logging.getLogger("PlaywrightFundamentals")

# Fundamental Thresholds
MIN_ROCE_PCT = 15.0  # ROCE must be > 15%
MAX_DEBT_TO_EQUITY = 1.0  # Debt/Equity must be < 1.0
MAX_PLEDGED_PCT = 5.0  # Pledged promoter shares must be < 5%


def clean_ticker_symbol(ticker: str) -> str:
    """Strips exchange suffixes (.NS, .BO) and cleans ticker for Screener.in URL."""
    clean = ticker.replace(".NS", "").replace(".BO", "").replace("^", "").strip().upper()
    return clean


async def fetch_screener_metrics_async(ticker: str, timeout: int = 18000) -> Optional[Dict[str, float]]:
    """
    Launches headless Chromium, navigates to Screener.in company page,
    and extracts ROCE, Debt to Equity, and Pledged Percentage.
    
    Returns:
        dict: {'roce': float, 'debt_to_equity': float, 'pledged_pct': float}
        or None if page fails to load or metrics cannot be retrieved.
    """
    clean_sym = clean_ticker_symbol(ticker)
    url_consolidated = f"https://www.screener.in/company/{clean_sym}/consolidated/"
    url_standalone = f"https://www.screener.in/company/{clean_sym}/"

    try:
        async with async_playwright() as p:
            # Launch headless Chromium
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()

            # Navigate to consolidated view first
            response = None
            try:
                response = await page.goto(url_consolidated, wait_until="domcontentloaded", timeout=timeout)
            except Exception:
                pass

            # Fallback to standalone if consolidated fails or 404
            if not response or response.status >= 400:
                try:
                    response = await page.goto(url_standalone, wait_until="domcontentloaded", timeout=timeout)
                except Exception:
                    pass

            if not response or response.status >= 400:
                logger.warning(f"Screener page failed to load for {ticker} (HTTP {response.status if response else 'ERR'})")
                await browser.close()
                return None

            # Verify top-ratios grid is present
            top_ratios_el = await page.query_selector("#top-ratios")
            if not top_ratios_el:
                logger.warning(f"No #top-ratios container found for {ticker}")
                await browser.close()
                return None

            metrics: Dict[str, float] = {}

            # 1. Extract metrics directly from #top-ratios grid
            items = await page.query_selector_all("#top-ratios li")
            for item in items:
                name_el = await item.query_selector(".name")
                val_el = await item.query_selector(".value")
                if not name_el or not val_el:
                    continue

                name_txt = (await name_el.inner_text()).strip().lower()
                val_txt = (await val_el.inner_text()).strip()

                # Parse float value
                nums = re.findall(r"[-+]?\d*\.\d+|\d+", val_txt.replace(",", ""))
                if not nums:
                    continue
                num_val = float(nums[0])

                if "roce" in name_txt:
                    metrics["roce"] = num_val
                elif "debt to equity" in name_txt or "debt/equity" in name_txt:
                    metrics["debt_to_equity"] = num_val
                elif "pledge" in name_txt:
                    metrics["pledged_pct"] = num_val

            # 2. Extract Debt to Equity from Balance Sheet if not present in #top-ratios
            if "debt_to_equity" not in metrics:
                bs = await page.query_selector("#balance-sheet")
                if bs:
                    borrowings = 0.0
                    equity_cap = 0.0
                    reserves = 0.0
                    rows = await bs.query_selector_all("tr")
                    for r in rows:
                        txt = (await r.inner_text()).strip()
                        cols = [c.strip() for c in txt.split("\t") if c.strip()]
                        if not cols:
                            continue
                        row_name = cols[0].lower()
                        # Extract latest numerical column
                        vals = []
                        for col in cols[1:]:
                            extracted = re.findall(r"[-+]?\d*\.\d+|\d+", col.replace(",", ""))
                            if extracted:
                                vals.append(float(extracted[0]))
                        latest_col = vals[-1] if vals else 0.0

                        if "borrowings" in row_name:
                            borrowings = latest_col
                        elif "equity share capital" in row_name or "equity capital" in row_name:
                            equity_cap = latest_col
                        elif "reserves" in row_name:
                            reserves = latest_col

                    total_equity = equity_cap + reserves
                    if total_equity > 0:
                        metrics["debt_to_equity"] = round(borrowings / total_equity, 2)
                    elif borrowings > 0:
                        metrics["debt_to_equity"] = 999.0
                    else:
                        metrics["debt_to_equity"] = 0.0

            # 3. Extract Pledged Percentage from Shareholding section if not in #top-ratios
            if "pledged_pct" not in metrics:
                sh = await page.query_selector("#shareholding")
                pledged_val = 0.0
                if sh:
                    sh_text = (await sh.inner_text()).lower()
                    if "pledge" in sh_text:
                        rows = await sh.query_selector_all("tr")
                        for r in rows:
                            txt = (await r.inner_text()).strip()
                            if "pledge" in txt.lower():
                                cols = [c.strip() for c in txt.split("\t") if c.strip()]
                                vals = []
                                for col in cols[1:]:
                                    extracted = re.findall(r"[-+]?\d*\.\d+|\d+", col.replace(",", ""))
                                    if extracted:
                                        vals.append(float(extracted[0]))
                                if vals:
                                    pledged_val = vals[-1]
                    else:
                        # No pledge reported -> 0.0%
                        pledged_val = 0.0
                metrics["pledged_pct"] = pledged_val

            await browser.close()

            # Ensure all three required metrics are identified
            if "roce" not in metrics or "debt_to_equity" not in metrics or "pledged_pct" not in metrics:
                logger.warning(f"Incomplete metrics extracted for {ticker}: {metrics}")
                return None

            return metrics

    except Exception as e:
        logger.error(f"Playwright browser exception for {ticker}: {e}")
        return None


def fetch_screener_metrics(ticker: str, timeout: int = 18000) -> Optional[Dict[str, float]]:
    """Synchronous wrapper for fetch_screener_metrics_async."""
    try:
        return asyncio.run(fetch_screener_metrics_async(ticker, timeout=timeout))
    except Exception as e:
        logger.error(f"Sync runner failed for {ticker}: {e}")
        return None


def evaluate_fundamental_rules(metrics: Optional[Dict[str, float]]) -> Tuple[bool, str]:
    """
    Evaluates whether the extracted fundamental metrics pass our hard quantitative rules:
    - ROCE > 15%
    - Debt to Equity < 1.0
    - Pledged percentage < 5%
    
    Returns:
        (passed: bool, reason: str)
    """
    if metrics is None:
        return False, "REJECT: Failed to fetch fundamentals from Screener.in or metrics hidden"

    roce = metrics.get("roce")
    debt_to_equity = metrics.get("debt_to_equity")
    pledged_pct = metrics.get("pledged_pct")

    if roce is None or debt_to_equity is None or pledged_pct is None:
        return False, f"REJECT: Missing metric values in extracted payload: {metrics}"

    # Rule 1: ROCE > 15
    if roce <= MIN_ROCE_PCT:
        return False, f"REJECT: ROCE ({roce:.1f}%) <= {MIN_ROCE_PCT}% threshold"

    # Rule 2: Debt to Equity < 1.0
    if debt_to_equity >= MAX_DEBT_TO_EQUITY:
        return False, f"REJECT: Debt/Equity ({debt_to_equity:.2f}) >= {MAX_DEBT_TO_EQUITY} threshold"

    # Rule 3: Pledged percentage < 5
    if pledged_pct >= MAX_PLEDGED_PCT:
        return False, f"REJECT: Pledged Promoters ({pledged_pct:.1f}%) >= {MAX_PLEDGED_PCT}% threshold"

    return True, (
        f"PASS: ROCE={roce:.1f}% (>15%), "
        f"Debt/Eq={debt_to_equity:.2f} (<1.0), "
        f"Pledged={pledged_pct:.1f}% (<5%)"
    )


if __name__ == "__main__":
    import sys
    test_tickers = sys.argv[1:] if len(sys.argv) > 1 else ["DIVISLAB", "SUZLON"]
    print("=" * 70)
    print("  PLAYWRIGHT FUNDAMENTAL ENGINE - TEST RUN")
    print("=" * 70)
    for sym in test_tickers:
        print(f"\n[+] Extracting Screener fundamentals for '{sym}'...")
        res = fetch_screener_metrics(sym)
        passed, reason = evaluate_fundamental_rules(res)
        print(f"    Raw Metrics : {res}")
        print(f"    Verdict     : {'APPROVED ✅' if passed else 'REJECTED ❌'}")
        print(f"    Reason      : {reason}")
    print("\n" + "=" * 70)
