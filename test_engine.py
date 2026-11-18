"""
V3 Multibagger Engine - Comprehensive Verification & Unit Tests
Tests setup detection, market regime filter, pyramiding sizing, trailing stop exits, and SQLite ledger.
"""

import unittest
import tempfile
import os
import pandas as pd
import numpy as np

from config import STARTING_CAPITAL
from strategy import (
    compute_weekly_indicators,
    compute_market_regime,
    check_exit_condition,
    check_pyramid_condition,
)
from v3_weekly_engine import V3Ledger


class TestV3Multibagger(unittest.TestCase):

    def setUp(self):
        # Create unique temporary database path
        self.db_path = os.path.join(tempfile.gettempdir(), f"test_v3_{os.getpid()}_{id(self)}.db")
        self.ledger = V3Ledger(db_path=self.db_path)

    def tearDown(self):
        import gc
        gc.collect()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_indicator_computation(self):
        """Verify that 30-week MA, 52-week High, and Breakout volume are computed properly."""
        dates = pd.date_range("2020-01-03", periods=80, freq="W-FRI")
        # Generate upward trending synthetic prices
        prices = np.linspace(100.0, 300.0, 80)
        vols = np.full(80, 600_000)
        # Spike volume on final bar
        vols[-1] = 1_500_000

        df = pd.DataFrame({
            "Open": prices * 0.99,
            "High": prices * 1.02,
            "Low": prices * 0.98,
            "Close": prices,
            "Volume": vols,
        }, index=dates)

        ind = compute_weekly_indicators(df)
        last_bar = ind.iloc[-1]

        self.assertTrue(last_bar["Is_Liquidity_OK"], "Liquidity filter failed")
        self.assertTrue(last_bar["MA30_trend_up"], "30-week MA trend up failed")
        self.assertTrue(last_bar["Breakout_Vol_OK"], "Volume breakout confirmation failed")
        self.assertTrue(last_bar["Stage2_Signal"], "Stage 2 Breakout Signal failed")

    def test_market_regime(self):
        """Verify Nifty 500 Market Regime Filter."""
        dates = pd.date_range("2020-01-03", periods=40, freq="W-FRI")
        # Nifty trading above its MA
        prices = np.linspace(10000, 15000, 40)
        nifty_df = pd.DataFrame({
            "Open": prices,
            "High": prices,
            "Low": prices,
            "Close": prices,
            "Volume": np.full(40, 1_000_000),
        }, index=dates)

        regime = compute_market_regime(nifty_df)
        self.assertTrue(regime.iloc[-1]["Regime_Bullish"])

    def test_pyramid_and_exit_conditions(self):
        """Verify pyramiding trigger (+20%) and exit trigger (Close < 0.85 * MA30)."""
        # Pyramiding: Entry 100, current 125 (+25%) -> should trigger
        self.assertTrue(check_pyramid_condition(125.0, 100.0, is_pyramided=False))
        # Pyramiding: Already pyramided -> should not trigger
        self.assertFalse(check_pyramid_condition(125.0, 100.0, is_pyramided=True))
        # Pyramiding: Less than +20% -> should not trigger
        self.assertFalse(check_pyramid_condition(115.0, 100.0, is_pyramided=False))

        # Exit: MA30 = 200, Stop = 170 (15% below). Close = 165 -> EXIT
        should_exit, stop_p = check_exit_condition(165.0, 200.0)
        self.assertTrue(should_exit)
        self.assertEqual(stop_p, 170.0)

        # Hold: Close = 175 -> HOLD
        should_exit, _ = check_exit_condition(175.0, 200.0)
        self.assertFalse(should_exit)

    def test_ledger_transactions(self):
        """Verify virtual buy, pyramiding, mark-to-market, and exit execution in SQLite ledger."""
        # 1. Initial State
        port = self.ledger.get_portfolio()
        self.assertEqual(port["cash_balance"], STARTING_CAPITAL)

        # 2. Buy 10 shares of TEST.NS @ ₹1,000 (Cost ~₹10,015 with fee)
        success = self.ledger.execute_initial_buy("TEST.NS", 1000.0, 10, "2024-01-05", ma30=900.0)
        self.assertTrue(success)
        port = self.ledger.get_portfolio()
        self.assertLess(port["cash_balance"], STARTING_CAPITAL)

        # 3. Pyramid Buy: Price rises to ₹1,200 (+20%). Buy 8 shares @ ₹1,200
        success_pyr = self.ledger.execute_pyramid_buy("TEST.NS", 1200.0, 8, "2024-03-01")
        self.assertTrue(success_pyr)
        pos = self.ledger.get_open_positions()[0]
        self.assertEqual(pos["total_shares"], 18)
        self.assertEqual(pos["is_pyramided"], 1)

        # 4. Exit: Price drops below stop level. Exit 18 shares @ ₹1,100
        success_exit = self.ledger.execute_exit("TEST.NS", 1100.0, "2024-06-01")
        self.assertTrue(success_exit)
        self.assertEqual(len(self.ledger.get_open_positions()), 0)

        # Verify trade history
        trades = self.ledger.get_closed_trades()
        self.assertEqual(len(trades), 3)  # INITIAL_BUY, PYRAMID_BUY, EXIT_STOP

    def test_fundamental_evaluation_rules(self):
        """Verify fundamental rules: ROCE > 15, Debt/Equity < 1.0, Pledging < 5%."""
        from playwright_fundamentals import evaluate_fundamental_rules

        # Good company: ROCE 22, D/E 0.05, Pledge 0.0 -> PASS
        good = {"roce": 22.0, "debt_to_equity": 0.05, "pledged_pct": 0.0}
        passed, reason = evaluate_fundamental_rules(good)
        self.assertTrue(passed)
        self.assertIn("PASS", reason)

        # Bad ROCE: ROCE 12, D/E 0.2, Pledge 0.0 -> REJECT
        bad_roce = {"roce": 12.0, "debt_to_equity": 0.2, "pledged_pct": 0.0}
        passed, reason = evaluate_fundamental_rules(bad_roce)
        self.assertFalse(passed)
        self.assertIn("ROCE", reason)

        # High Debt: ROCE 25, D/E 1.8, Pledge 0.0 -> REJECT
        high_debt = {"roce": 25.0, "debt_to_equity": 1.8, "pledged_pct": 0.0}
        passed, reason = evaluate_fundamental_rules(high_debt)
        self.assertFalse(passed)
        self.assertIn("Debt/Equity", reason)

        # High Pledging: ROCE 20, D/E 0.4, Pledge 12.0 -> REJECT
        high_pledge = {"roce": 20.0, "debt_to_equity": 0.4, "pledged_pct": 12.0}
        passed, reason = evaluate_fundamental_rules(high_pledge)
        self.assertFalse(passed)
        self.assertIn("Pledged", reason)

        # None / missing payload -> REJECT
        passed, reason = evaluate_fundamental_rules(None)
        self.assertFalse(passed)


if __name__ == "__main__":
    unittest.main()
