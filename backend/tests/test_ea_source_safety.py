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
    assert "ChildClosedByReason(tp1_child, DEAL_REASON_TP)" in EA
    assert "ChildClosedByReason(tp2_child, DEAL_REASON_TP)" in EA
    assert "ChildClosedByReason(tp3_child, DEAL_REASON_TP)" in EA
    assert "DEAL_POSITION_ID" in EA
    assert "DEAL_TIME_MSC" in EA
    assert "STOP_LOSS_HIT" in EA
    manage = EA.split("void ManageActiveCommand()", 1)[1].split(
        "//| Broker execution / close-reason helpers", 1
    )[0]
    assert "fully_closed && CommandClosedByReason(DEAL_REASON_SL)" in manage
    assert "AllTrackedChildrenClosedWithEvidence()" in manage

def test_ea_resolves_broker_symbol_suffix_and_netting_fallback():
    assert "ResolveBrokerSymbol(requested)" in EA
    assert "SymbolsTotal(false)" in EA
    assert "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING" in EA
    assert "g_split_mode" in EA



def test_unknown_full_close_is_not_forced_to_tp3():
    block = EA.split("// Full close: TP3 is credited only to its own child", 1)[1].split(
        "//+------------------------------------------------------------------+", 1
    )[0]
    assert "if(fully_closed)" in block
    assert "ChildClosedByReason(tp3_child, DEAL_REASON_TP)" in block
    assert "preceding_tps" in block
    assert "FULLY_CLOSED" in block
    assert "CommandClosedByReason(DEAL_REASON_TP)" not in block


def test_tp_stage_receipts_require_exact_child_broker_deal_and_full_volume():
    manage = EA.split("void ManageActiveCommand()", 1)[1].split(
        "//| Broker execution / close-reason helpers", 1
    )[0]
    for stage in (1, 2, 3):
        assert f"ChildClosedByReason(tp{stage}_child, DEAL_REASON_TP)" in manage
    assert "open_children <= (g_child_count" not in manage
    assert "CommandClosedByReason(DEAL_REASON_TP)" not in manage
    stage = EA.split("bool ChildClosedByReason(", 1)[1].split(
        "bool AllTrackedChildrenClosedWithEvidence()", 1
    )[0]
    assert "ChildPositionStillOpen(position_id)" in stage
    assert "g_child_tickets[child_index]" in stage
    assert "HistoryDealGetInteger(deal, DEAL_MAGIC) != MagicNumber" in stage
    assert "HistoryDealGetInteger(deal, DEAL_POSITION_ID)" in stage
    assert "HistoryDealGetString(deal, DEAL_SYMBOL)" in stage
    assert "HistoryDealGetInteger(deal, DEAL_REASON) != required_reason" in stage
    assert "DEAL_ENTRY_OUT" in stage
    assert "DEAL_ENTRY_OUT_BY" in stage
    assert "exited_volume += volume" in stage
    assert "g_child_open_volumes[child_index] - 1e-8" in stage
    assert "else if(entry == DEAL_ENTRY_IN || entry == DEAL_ENTRY_INOUT)" in stage


def test_final_stop_reason_uses_latest_matching_child_exit_not_earlier_stop():
    helper = EA.split("bool CommandClosedByReason(", 1)[1].split(
        "void ClearActiveCommand()", 1
    )[0]
    assert "IsChildPosition(position_id)" in helper
    assert "DEAL_TIME_MSC" in helper
    assert "latest_ticket" in helper
    assert "latest_reason == reason" in helper
    assert "return(true)" not in helper


def test_tied_latest_broker_exit_reasons_refuse_stop_out_attribution():
    """Source guard only: actual equal-ms broker exit evidence is still required."""
    helper = EA.split("bool CommandClosedByReason(", 1)[1].split(
        "void ClearActiveCommand()", 1
    )[0]
    assert "DEAL_POSITION_ID" in helper
    assert "IsChildPosition(position_id)" in helper
    assert "HistoryDealGetInteger(deal, DEAL_TIME_MSC)" in helper
    assert "bool latest_ambiguous = false;" in helper
    assert "if(at_msc > latest_msc)" in helper
    assert "latest_ambiguous = false;" in helper
    assert "else if(at_msc == latest_msc && deal_reason != latest_reason)" in helper
    assert "latest_ambiguous = true;" in helper
    assert (
        "return(latest_ticket != 0 && !latest_ambiguous && latest_reason == reason);"
        in helper
    )
    assert "deal > latest_ticket" not in helper


def test_server_confirmed_stop_move_requires_readback_and_a_matching_child():
    guard = EA.split("bool MoveRemainingSL(", 1)[1].split(
        "//| Close all children", 1
    )[0]
    assert "IsChildPosition(position_id)" in guard
    assert "POSITION_IDENTIFIER" in guard
    assert 'PositionGetString(POSITION_COMMENT) != "SG:" + command_id' in guard
    assert "trade.ResultRetcode()" in guard
    assert "retcode != TRADE_RETCODE_DONE" in guard
    assert "PositionSelectByTicket(ticket)" in guard
    assert "MathAbs(PositionGetDouble(POSITION_SL) - new_sl) > tolerance" in guard
    assert "return(all_ok && seen > 0)" in guard


def test_trading_starts_explicitly_off_for_demo_account():
    assert "input bool   EnableTrading              = false;" in EA
    timer = EA.split("void OnTimer()", 1)[1].split(
        "void ProcessCommand(", 1
    )[0]
    assert "if(!EnableTrading)" in timer
    assert timer.index("if(!EnableTrading)") < timer.index("PollPendingCommand()")

def test_ea_continuously_reconciles_open_broker_positions():
    assert "int ReconcileOpenPositions()" in EA
    assert "/reconcile_open_position" in EA
    assert 'StringFind(comment, "SG:") != 0' in EA
    reconcile = EA.split("int ReconcileOpenPositions()", 1)[1].split(
        "void ReportExecutionSuccess(", 1
    )[0]
    assert 'tickets += "\\\"" + IntegerToString((long)ticket) + "\\\"";' in reconcile
    assert 'body += "\\\"broker_tickets\\\":[" + tickets + "],";' in reconcile
    assert 'body += "\\\"executed_symbol\\\":" + JsonEscapeString(symbol) + ",";' in reconcile
    assert 'body += "\\\"executed_direction\\\":" + JsonEscapeString(direction) + ",";' in reconcile
    assert 'body += "\\\"executed_price\\\":" + DoubleToString(avg_price, digits) + ",";' in reconcile
    assert 'body += "\\\"lot_size\\\":" + DoubleToString(total_volume, 8);' in reconcile
    assert 'body += ",\\\"stop_loss\\\":" + DoubleToString(current_sl, digits);' in reconcile
    assert '""broker_tickets"' not in reconcile
    timer = EA.split("void OnTimer()", 1)[1].split("//+------------------------------------------------------------------+", 1)[0]
    assert "ReconcileOpenPositions()" in timer
    assert "if(open_sg_commands > 0)" in timer
    assert "PollPendingCommand()" in timer
    assert timer.index("if(open_sg_commands > 0)") < timer.index("PollPendingCommand()")



def test_ea_child_position_ownership_uses_exact_command_comment():
    assert 'comment == "SG:" + command_id' in EA
    assert 'PositionGetString(POSITION_COMMENT) != "SG:" + command_id' in EA
    count = EA.split("int CountOpenChildren(", 1)[1].split(
        "//+------------------------------------------------------------------+", 1
    )[0]
    move = EA.split("bool MoveRemainingSL(", 1)[1].split(
        "//+------------------------------------------------------------------+", 1
    )[0]
    close = EA.split("void CloseAllChildren(", 1)[1].split(
        "//+------------------------------------------------------------------+", 1
    )[0]
    assert "StringFind(comment, command_id)" not in count
    assert "StringFind(PositionGetString(POSITION_COMMENT), command_id)" not in move
    assert "StringFind(PositionGetString(POSITION_COMMENT), command_id)" not in close


def test_ea_never_increases_configured_lot_to_broker_minimum_or_step():
    block = EA.split("bool NormalizeLot(", 1)[1].split(
        "//+------------------------------------------------------------------+", 1
    )[0]
    assert "if(lot < minlot || lot > maxlot)" in block
    assert "return(false);" in block
    assert "MathFloor" in block
    assert "MathRound" not in block
    assert "lot = minlot" not in block
    assert "lot = maxlot" not in block


def test_execution_report_uses_actual_broker_filled_volume_and_weighted_price():
    split = EA.split("bool ExecuteSplitTicket(", 1)[1].split(
        "//+------------------------------------------------------------------+", 1
    )[0]
    single = EA.split("bool ExecuteSingleTicket(", 1)[1].split(
        "//+------------------------------------------------------------------+", 1
    )[0]
    report = EA.split("void ReportExecutionSuccess(", 1)[1].split(
        "void ReportManagementEvent(", 1
    )[0]
    assert "trade.ResultVolume()" in split
    assert "weighted_exec_price" in split
    assert "weighted_exec_price / executed_lot" in split
    assert "trade.ResultVolume()" in single
    assert "const double executed_lot" in report
    assert 'body += "\\\"lot_size\\\":" + DoubleToString(executed_lot, 8)' in report
    assert "TP1Lot + TP2Lot + TP3Lot" not in report


def test_execution_report_uses_executed_symbol_precision():
    report = EA.split("void ReportExecutionSuccess(", 1)[1].split(
        "void ReportManagementEvent(", 1
    )[0]
    assert "SymbolInfoInteger(symbol, SYMBOL_DIGITS)" in report
    assert "DoubleToString(exec_price, digits)" in report
    assert "DoubleToString(sl, digits)" in report


def test_ea_fails_closed_if_backend_does_not_acknowledge_command():
    process = EA.split("void ProcessCommand(", 1)[1].split(
        "//+------------------------------------------------------------------+", 1
    )[0]
    ack = EA.split("bool AckReceived(", 1)[1].split(
        "void SendHeartbeat(", 1
    )[0]
    assert "if(!AckReceived(command_id))" in process
    assert "refusing broker execution" in process
    assert "g_last_http_code >= 200 && g_last_http_code < 300" in ack


def test_http_helpers_reject_non_2xx_responses():
    http = EA.split("string HttpGet(", 1)[1].split(
        "//+------------------------------------------------------------------+\n//| Backend calls", 1
    )[0]
    assert http.count("code < 200 || code >= 300") >= 2
    assert "g_last_http_code = code" in http


def test_broker_suffix_resolution_refuses_ambiguous_matches():
    block = EA.split("string ResolveBrokerSymbol(", 1)[1].split(
        "bool ExecutionFilled(", 1
    )[0]
    assert "matches != 1" in block
    assert "Ambiguous broker symbol suffix match" in block
    assert "refusing to guess" in block


def test_ea_accepts_only_positive_demo_account_mode_at_start_and_each_timer():
    """Source guard: no negative-only 'not REAL' account classification."""
    helper = EA.split("bool IsDemoAccount()", 1)[1].split(
        "//+------------------------------------------------------------------+", 1
    )[0]
    assert "ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO" in helper
    assert "IsLiveAccount" not in EA
    init = EA.split("int OnInit()", 1)[1].split("void OnDeinit(", 1)[0]
    timer = EA.split("void OnTimer()", 1)[1].split("void ProcessCommand(", 1)[0]
    assert "if(!IsDemoAccount())" in init
    assert "if(!IsDemoAccount())" in timer
    assert timer.index("if(!IsDemoAccount())") < timer.index("if(!EnableTrading)")


def test_unidentified_or_broker_mutated_open_positions_block_new_demo_orders():
    """All existing positions/orders block even if comment or magic is lost."""
    timer = EA.split("void OnTimer()", 1)[1].split("void ProcessCommand(", 1)[0]
    process = EA.split("void ProcessCommand(", 1)[1].split(
        "bool ExecuteSplitTicket(", 1
    )[0]
    account_flat_guard = "PositionsTotal() != 0 || OrdersTotal() != 0"
    assert account_flat_guard in timer
    assert timer.index(account_flat_guard) < timer.index("PollPendingCommand()")
    assert process.count(account_flat_guard) >= 2
    assert process.index(account_flat_guard) < process.index("AckReceived(command_id)")
    assert process.rindex(account_flat_guard) > process.index("AckReceived(command_id)")
    assert process.count("!IsDemoAccount()") >= 2
