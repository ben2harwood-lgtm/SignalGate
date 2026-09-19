"""Source-level invariants for the MQL5 safety boundary.

MetaEditor is not available on GitHub's Linux runner, so these tests guard
critical source properties in addition to the manual/Windows compile gate.
"""
from pathlib import Path

EA = (Path(__file__).parents[2] / "mt5_ea" / "SignalGateEA.mq5").read_text()


def test_rollback_is_scoped_to_command_id():
    assert "void CloseAllChildren(const string symbol, const string command_id)" in EA
    assert "CloseAllChildren(symbol, command_id);" in EA
    rollback = EA.split("void CloseAllChildren(", 1)[1].split("//+------------------------------------------------------------------+", 1)[0]
    assert "POSITION_COMMENT" in rollback
    assert "command_id" in rollback


def test_hosted_license_is_sent_in_header_not_pending_url():
    assert "X-SG-License-Key: " in EA
    poll = EA.split("string PollPendingCommand()", 1)[1].split("}", 1)[0]
    assert "license_key=" not in poll.lower()


def test_ea_rejects_limit_and_verifies_broker_fill_retcode():
    assert 'entry_type != "MARKET"' in EA
    assert "UNSUPPORTED_ENTRY_TYPE" in EA
    assert "ExecutionFilled(trade.ResultRetcode())" in EA
    assert "TRADE_RETCODE_DONE" in EA
    assert "TRADE_RETCODE_DONE_PARTIAL" in EA


def test_ea_distinguishes_stop_and_tp_from_broker_deal_reason():
    assert "CommandClosedByReason(DEAL_REASON_SL)" in EA
    assert "CommandClosedByReason(DEAL_REASON_TP)" in EA
    assert "DEAL_POSITION_ID" in EA
    assert "STOP_LOSS_HIT" in EA
    full_close = EA.split("if(open_children == 0)", 1)[1]
    assert "CommandClosedByReason" in full_close


def test_ea_resolves_broker_symbol_suffix_and_netting_fallback():
    assert "ResolveBrokerSymbol(requested)" in EA
    assert "SymbolsTotal(false)" in EA
    assert "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING" in EA
    assert "g_split_mode" in EA


def test_unknown_full_close_is_not_forced_to_tp3():
    block = EA.split("// Full close. Only attribute TP3", 1)[1].split("//+------------------------------------------------------------------+", 1)[0]
    assert "CommandClosedByReason(DEAL_REASON_TP)" in block
    assert "FULLY_CLOSED" in block


def test_ea_continuously_reconciles_open_broker_positions():
    assert "int ReconcileOpenPositions()" in EA
    assert "/reconcile_open_position" in EA
    assert 'StringFind(comment, "SG:") != 0' in EA
    assert '"broker_tickets"' in EA
    timer = EA.split("void OnTimer()", 1)[1].split("//+------------------------------------------------------------------+", 1)[0]
    assert "ReconcileOpenPositions()" in timer
    assert "if(open_sg_commands > 0)" in timer
    assert "PollPendingCommand()" in timer
    assert timer.index("if(open_sg_commands > 0)") < timer.index("PollPendingCommand()")
