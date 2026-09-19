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
    assert '"lot_size\":" + DoubleToString(executed_lot, 8)' in report
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
