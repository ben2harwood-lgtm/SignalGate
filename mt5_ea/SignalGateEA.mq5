//+------------------------------------------------------------------+
//|                                                 SignalGateEA.mq5  |
//|   SignalGate demo-only trade execution Expert Advisor             |
//|                                                                   |
//|   SAFETY / SCOPE (v1):                                            |
//|     - DEMO ONLY. Refuses to trade on a live account.             |
//|     - Receives only structured, validated backend commands via    |
//|       WebRequest. Raw Telegram text NEVER reaches this EA.        |
//|     - Every position opens WITH an initial hard stop loss.        |
//|     - Each command is executed at most once (local idempotency).  |
//|     - No trailing stop. No full auto-copy. No live support.       |
//|                                                                   |
//|   This is a working skeleton. MQL5 has no standard JSON library,  |
//|   so a minimal deterministic extractor for the known backend      |
//|   command shape is bundled below (see JsonGet* functions).        |
//+------------------------------------------------------------------+
#property copyright "SignalGate (demo only)"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>

//--- Inputs --------------------------------------------------------------
input string BackendURL                 = "http://127.0.0.1:8000";
input string UserID                     = "USER-000001";
input string LicenseKey                 = "local-demo";
input string EAApiKey                   = "local-demo-ea-key";
input int    PollIntervalSeconds        = 2;
input double SingleTicketFixedLot       = 0.01;
input bool   SplitTicketDemoPartialMode = true;
input double TP1Lot                     = 0.02;
input double TP2Lot                     = 0.01;
input double TP3Lot                     = 0.01;
input long   MagicNumber                = 440044;
input bool   DemoOnlyMode               = true;
input int    MaxSpreadPoints            = 500;
input int    MaxSlippagePoints          = 100;
input bool   EnableTrading              = true;
input string SymbolOverride             = "";

//--- Globals -------------------------------------------------------------
CTrade        trade;
CPositionInfo posinfo;

// Local idempotency: list of processed command ids (in-memory while running).
string  g_processed_ids[];

// Active command tracking (one active command lifecycle at a time for v1).
string  g_active_command_id   = "";
string  g_active_symbol       = "";
int     g_active_direction    = 0;        // +1 BUY, -1 SELL
double  g_active_entry        = 0.0;
double  g_active_sl           = 0.0;
double  g_active_tp1          = 0.0;
double  g_active_tp2          = 0.0;
double  g_active_tp3          = 0.0;
ulong   g_child_tickets[3];               // opening deal tickets
ulong   g_child_pos_ids[3];               // broker position ids for close-reason lookup
int     g_child_count         = 0;
datetime g_open_time          = 0;
bool    g_tp1_done            = false;
bool    g_tp2_done            = false;
bool    g_tp3_done            = false;
double  g_effective_sl        = 0.0;
bool    g_split_mode          = true;

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("SignalGateEA starting. DEMO ONLY. No live trading.");

   if(!DemoOnlyMode)
   {
      Print("FATAL: DemoOnlyMode must be TRUE in v1. EA will not run.");
      return(INIT_FAILED);
   }

   // SAFETY: refuse to run against a live account.
   if(IsLiveAccount())
   {
      Print("FATAL: Account appears to be LIVE. SignalGate is demo only. Refusing.");
      ReportDemoOnlyViolation();
      return(INIT_FAILED);
   }

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(MaxSlippagePoints);

   // Split tickets require a hedging account. On netting accounts multiple
   // orders collapse into one position and count-based TP management becomes
   // unsafe, so fall back to a single ticket.
   g_split_mode = SplitTicketDemoPartialMode;
   long margin_mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(g_split_mode && margin_mode != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      Print("WARNING: non-hedging account detected; using single-ticket mode.");
      g_split_mode = false;
   }

   PrintWebRequestHint();
   SendHeartbeat();

   EventSetTimer(PollIntervalSeconds < 1 ? 1 : PollIntervalSeconds);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("SignalGateEA stopped.");
}

//+------------------------------------------------------------------+
//| OnTimer                                                           |
//+------------------------------------------------------------------+
void OnTimer()
{
   if(!EnableTrading)
      return;

   // Continuously reconcile actual broker positions with backend state. This
   // recovers a lost execution callback after a network timeout.
   int open_sg_commands = ReconcileOpenPositions();

   // If we already manage an active command, run management instead of polling.
   if(g_active_command_id != "")
   {
      ManageActiveCommand();
      return;
   }

   // After an EA restart we may find an existing SignalGate position but no
   // in-memory lifecycle state. Fail safe: report the broker position and do
   // NOT claim a new command while that orphaned position remains open.
   if(open_sg_commands > 0)
   {
      Print("SignalGate position(s) found without active in-memory state; "
            "reconciled with backend and polling is blocked until flat.");
      return;
   }

   string json = PollPendingCommand();
   if(json == "")
      return;

   // No command case: backend returns {"command": null}.
   if(StringFind(json, "\"command\":null") >= 0 ||
      StringFind(json, "\"command\": null") >= 0)
      return;

   string command_id = JsonGetString(json, "command_id");
   if(command_id == "")
      return;

   // SAFETY: local idempotency — never trade the same command twice.
   if(AlreadyProcessed(command_id))
   {
      ReportError(command_id, "DUPLICATE_COMMAND", "Command already processed locally");
      return;
   }

   ProcessCommand(command_id, json);
}

//+------------------------------------------------------------------+
//| Process a freshly received command                               |
//+------------------------------------------------------------------+
void ProcessCommand(const string command_id, const string json)
{
   MarkProcessed(command_id);

   // --- Parse structured fields -------------------------------------
   string symbol      = JsonGetString(json, "symbol");
   string direction_s = JsonGetString(json, "direction");
   string entry_type  = JsonGetString(json, "entry_type");
   bool   demo_only   = JsonGetBool(json, "demo_only");
   double sl          = JsonGetDouble(json, "initial_stop_loss");

   // Take profits (fixed known shape: take_profits array with price/lot).
   double tp1 = JsonGetTpPrice(json, 1);
   double tp2 = JsonGetTpPrice(json, 2);
   double tp3 = JsonGetTpPrice(json, 3);

   string requested    = (SymbolOverride != "") ? SymbolOverride : symbol;
   string trade_symbol = ResolveBrokerSymbol(requested);

   // --- Validation (report and bail on failure) ---------------------
   if(!demo_only)
   {
      ReportError(command_id, "DEMO_ONLY_VIOLATION", "Command not flagged demo_only");
      return;
   }
   if(entry_type != "MARKET")
   {
      ReportError(command_id, "UNSUPPORTED_ENTRY_TYPE",
                  "Only MARKET entries are supported by this EA");
      return;
   }
   if(trade_symbol == "")
   {
      ReportError(command_id, "SYMBOL_NOT_FOUND",
                  "No exact or suffix broker symbol match: " + requested);
      return;
   }
   if(sl <= 0.0)
   {
      ReportError(command_id, "INVALID_STOP_LOSS", "Missing/invalid initial stop loss");
      return;
   }
   if(tp1 <= 0.0)
   {
      ReportError(command_id, "INVALID_TAKE_PROFIT", "Missing/invalid TP1");
      return;
   }

   int direction = (direction_s == "BUY") ? +1 : ((direction_s == "SELL") ? -1 : 0);
   if(direction == 0)
   {
      ReportError(command_id, "ORDER_SEND_FAILED", "Unknown direction");
      return;
   }

   // Spread check.
   double spread_points = (double)SymbolInfoInteger(trade_symbol, SYMBOL_SPREAD);
   if(spread_points > MaxSpreadPoints)
   {
      ReportError(command_id, "SPREAD_TOO_HIGH",
                  "Spread " + DoubleToString(spread_points,0) + " > max");
      return;
   }

   // Directional SL/TP sanity (defence in depth; backend already validated).
   double ask = SymbolInfoDouble(trade_symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(trade_symbol, SYMBOL_BID);
   double ref = (direction == +1) ? ask : bid;
   if(direction == +1 && (sl >= ref || tp1 <= ref))
   {
      ReportError(command_id, "INVALID_STOP_LOSS", "BUY SL/TP not consistent with price");
      return;
   }
   if(direction == -1 && (sl <= ref || tp1 >= ref))
   {
      ReportError(command_id, "INVALID_STOP_LOSS", "SELL SL/TP not consistent with price");
      return;
   }

   // Acknowledge receipt before execution.
   AckReceived(command_id);

   // --- Execute ------------------------------------------------------
   bool ok = false;
   if(g_split_mode)
      ok = ExecuteSplitTicket(command_id, trade_symbol, direction, sl, tp1, tp2, tp3);
   else
      ok = ExecuteSingleTicket(command_id, trade_symbol, direction, sl, tp1, tp2, tp3);

   if(!ok)
      return; // execution already reported failure

   // Begin managing this command.
   g_active_command_id = command_id;
   g_active_symbol     = trade_symbol;
   g_active_direction  = direction;
   g_active_sl         = sl;
   g_effective_sl      = sl;
   g_active_tp1        = tp1;
   g_active_tp2        = tp2;
   g_active_tp3        = tp3;
   g_tp1_done = false; g_tp2_done = false; g_tp3_done = false;
}

//+------------------------------------------------------------------+
//| Execute split-ticket demo partial mode                           |
//+------------------------------------------------------------------+
bool ExecuteSplitTicket(const string command_id, const string symbol,
                        const int direction, const double sl,
                        const double tp1, const double tp2, const double tp3)
{
   double lots[3]; double tps[3];
   lots[0] = TP1Lot; lots[1] = TP2Lot; lots[2] = TP3Lot;
   tps[0]  = tp1;    tps[1]  = tp2;    tps[2]  = tp3;

   g_child_count = 0;
   double exec_price = 0.0;

   for(int i = 0; i < 3; i++)
   {
      if(tps[i] <= 0.0)
         continue; // skip absent TP levels (e.g. only TP1/TP2 present)

      if(!NormalizeLot(symbol, lots[i]))
      {
         ReportError(command_id, "LOT_SIZE_INVALID",
                     "Lot invalid for child " + IntegerToString(i+1));
         CloseAllChildren(symbol, command_id);
         return(false);
      }

      bool sent;
      if(direction == +1)
         sent = trade.Buy(lots[i], symbol, 0.0, sl, tps[i], "SG:"+command_id);
      else
         sent = trade.Sell(lots[i], symbol, 0.0, sl, tps[i], "SG:"+command_id);

      if(!sent || !ExecutionFilled(trade.ResultRetcode()))
      {
         ReportError(command_id, RetcodeErrorCode(trade.ResultRetcode()),
                     "Child " + IntegerToString(i+1) + " retcode " +
                     IntegerToString(trade.ResultRetcode()));
         CloseAllChildren(symbol, command_id);
         return(false);
      }
      g_child_tickets[g_child_count] = trade.ResultDeal();
      g_child_pos_ids[g_child_count] = PositionIdOfDeal(trade.ResultDeal());
      exec_price = trade.ResultPrice();
      g_child_count++;
   }
   g_open_time = TimeCurrent();

   if(g_child_count == 0)
   {
      ReportError(command_id, "INVALID_TAKE_PROFIT", "No valid TP levels to open");
      return(false);
   }

   g_active_entry = exec_price;
   ReportExecutionSuccess(command_id, symbol, direction, exec_price, sl, tp1, tp2, tp3);
   ReportManagementEvent(command_id, "OPENED", "OPENED", "OPEN", "SUCCESS",
                         exec_price, 0,0,0,0);
   return(true);
}

//+------------------------------------------------------------------+
//| Execute single-ticket fallback mode                              |
//+------------------------------------------------------------------+
bool ExecuteSingleTicket(const string command_id, const string symbol,
                         const int direction, const double sl,
                         const double tp1, const double tp2, const double tp3)
{
   double lot = SingleTicketFixedLot;
   if(!NormalizeLot(symbol, lot))
   {
      ReportError(command_id, "LOT_SIZE_INVALID", "Single-ticket lot invalid");
      return(false);
   }

   // Single ticket: target the FINAL available TP (TP3, else TP2, else TP1).
   double final_tp = tp3 > 0 ? tp3 : (tp2 > 0 ? tp2 : tp1);

   bool sent;
   if(direction == +1)
      sent = trade.Buy(lot, symbol, 0.0, sl, final_tp, "SG:"+command_id);
   else
      sent = trade.Sell(lot, symbol, 0.0, sl, final_tp, "SG:"+command_id);

   if(!sent || !ExecutionFilled(trade.ResultRetcode()))
   {
      ReportError(command_id, RetcodeErrorCode(trade.ResultRetcode()),
                  "retcode " + IntegerToString(trade.ResultRetcode()));
      return(false);
   }

   g_child_tickets[0] = trade.ResultDeal();
   g_child_pos_ids[0] = PositionIdOfDeal(trade.ResultDeal());
   g_child_count = 1;
   g_open_time = TimeCurrent();
   g_active_entry = trade.ResultPrice();

   ReportExecutionSuccess(command_id, symbol, direction, g_active_entry,
                          sl, tp1, tp2, tp3);
   ReportManagementEvent(command_id, "OPENED", "OPENED", "OPEN", "SUCCESS",
                         g_active_entry, 0,0,0,0);
   return(true);
}

//+------------------------------------------------------------------+
//| Manage the active command: detect TP hits, move SLs              |
//+------------------------------------------------------------------+
void ManageActiveCommand()
{
   string cid = g_active_command_id;

   int open_children = CountOpenChildren(g_active_symbol, cid);

   // Broker deal history is authoritative for why a position closed. Never
   // infer a take-profit merely because the position disappeared.
   if(open_children == 0 && CommandClosedByReason(DEAL_REASON_SL))
   {
      ReportManagementEvent(cid, "STOP_LOSS_HIT", "FULLY_CLOSED", "", "SUCCESS",
                            g_effective_sl, 0,0, g_active_sl, g_effective_sl);
      ReportManagementEvent(cid, "FULLY_CLOSED", "FULLY_CLOSED", "", "SUCCESS",
                            0,0,0,0,0);
      ClearActiveCommand();
      return;
   }

   // TP1 stage: when the first child has closed (TP1 hit).
   if(!g_tp1_done && open_children <= (g_child_count - 1) && g_child_count >= 2)
   {
      g_tp1_done = true;
      ReportManagementEvent(cid, "TP1_REACHED", "OPENED", "", "SUCCESS",
                            g_active_tp1, 0,0,0,0);
      ReportManagementEvent(cid, "TP1_CLOSE_SUCCESS", "TP1_DONE", "CLOSE_TP1",
                            "SUCCESS", g_active_tp1, 0,0,0,0);
      // Move remaining SLs to breakeven (open price).
      bool moved = MoveRemainingSL(g_active_symbol, cid, g_active_entry);
      if(moved) g_effective_sl = g_active_entry;
      ReportManagementEvent(cid,
         moved ? "SL_MOVE_BREAKEVEN_SUCCESS" : "SL_MOVE_BREAKEVEN_FAILED",
         "TP1_DONE", "MOVE_SL_BREAKEVEN", moved ? "SUCCESS" : "FAILED",
         g_active_entry, 0,0, g_active_sl, g_active_entry);
   }

   // TP2 stage.
   if(g_tp1_done && !g_tp2_done && g_active_tp2 > 0 &&
      open_children <= (g_child_count - 2) && g_child_count >= 3)
   {
      g_tp2_done = true;
      ReportManagementEvent(cid, "TP2_REACHED", "TP1_DONE", "", "SUCCESS",
                            g_active_tp2, 0,0,0,0);
      ReportManagementEvent(cid, "TP2_CLOSE_SUCCESS", "TP2_DONE", "CLOSE_TP2",
                            "SUCCESS", g_active_tp2, 0,0,0,0);
      bool moved = MoveRemainingSL(g_active_symbol, cid, g_active_tp1);
      if(moved) g_effective_sl = g_active_tp1;
      ReportManagementEvent(cid,
         moved ? "SL_MOVE_TP1_SUCCESS" : "SL_MOVE_TP1_FAILED",
         "TP2_DONE", "MOVE_SL_TP1", moved ? "SUCCESS" : "FAILED",
         g_active_tp1, 0,0, g_active_entry, g_active_tp1);
   }

   // Full close. Only attribute TP3 when broker history says the final close
   // was a take-profit. A manual/unknown close remains unattributed in the
   // backend ledger rather than being fabricated as a win.
   if(open_children == 0)
   {
      if(!g_tp3_done && g_active_tp3 > 0 && CommandClosedByReason(DEAL_REASON_TP))
      {
         g_tp3_done = true;
         ReportManagementEvent(cid, "TP3_CLOSE_SUCCESS", "TP3_DONE",
                               "CLOSE_TP3", "SUCCESS", g_active_tp3, 0,0,0,0);
      }
      ReportManagementEvent(cid, "FULLY_CLOSED", "FULLY_CLOSED", "", "SUCCESS",
                            0,0,0,0,0);
      ClearActiveCommand();
   }
}

//+------------------------------------------------------------------+
//| Broker execution / close-reason helpers                          |
//+------------------------------------------------------------------+
string ResolveBrokerSymbol(const string requested)
{
   if(requested == "") return("");
   if(SymbolSelect(requested, true)) return(requested);
   int total = SymbolsTotal(false);
   for(int i = 0; i < total; i++)
   {
      string name = SymbolName(i, false);
      if(StringFind(name, requested) == 0 && SymbolSelect(name, true))
         return(name);
   }
   return("");
}

bool ExecutionFilled(const uint retcode)
{
   return(retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_DONE_PARTIAL);
}

string RetcodeErrorCode(const uint retcode)
{
   switch(retcode)
   {
      case TRADE_RETCODE_MARKET_CLOSED:  return("MARKET_CLOSED");
      case TRADE_RETCODE_NO_MONEY:       return("MARGIN_INSUFFICIENT");
      case TRADE_RETCODE_INVALID_STOPS:  return("INVALID_STOP_LOSS");
      case TRADE_RETCODE_TRADE_DISABLED: return("TRADING_DISABLED");
      default:                           return("ORDER_SEND_FAILED");
   }
}

ulong PositionIdOfDeal(const ulong deal_ticket)
{
   if(deal_ticket == 0) return(0);
   if(HistoryDealSelect(deal_ticket))
      return((ulong)HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID));
   return(0);
}

bool IsChildPosition(const ulong position_id)
{
   for(int i = 0; i < g_child_count; i++)
      if(g_child_pos_ids[i] != 0 && g_child_pos_ids[i] == position_id)
         return(true);
   return(false);
}

bool CommandClosedByReason(const long reason)
{
   datetime from = (g_open_time > 0) ? g_open_time - 5 : 0;
   if(!HistorySelect(from, TimeCurrent() + 60))
      return(false);
   int total = HistoryDealsTotal();
   for(int i = total - 1; i >= 0; i--)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != MagicNumber) continue;
      if(HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      ulong posid = (ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      if(!IsChildPosition(posid)) continue;
      if(HistoryDealGetInteger(deal, DEAL_REASON) == reason)
         return(true);
   }
   return(false);
}

void ClearActiveCommand()
{
   g_active_command_id = "";
   g_child_count = 0;
   g_open_time = 0;
   g_effective_sl = 0.0;
   ArrayInitialize(g_child_pos_ids, 0);
}

//+------------------------------------------------------------------+
//| Count open child positions belonging to this command            |
//+------------------------------------------------------------------+
int CountOpenChildren(const string symbol, const string command_id)
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol) continue;
      string comment = PositionGetString(POSITION_COMMENT);
      if(StringFind(comment, command_id) >= 0)
         count++;
   }
   return(count);
}

//+------------------------------------------------------------------+
//| Move SL on remaining open children of this command              |
//+------------------------------------------------------------------+
bool MoveRemainingSL(const string symbol, const string command_id,
                     const double new_sl)
{
   bool all_ok = true;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), command_id) < 0) continue;

      double tp = PositionGetDouble(POSITION_TP);
      if(!trade.PositionModify(ticket, new_sl, tp))
         all_ok = false;
   }
   return(all_ok);
}

//+------------------------------------------------------------------+
//| Close all children (used on partial execution failure rollback) |
//+------------------------------------------------------------------+
void CloseAllChildren(const string symbol, const string command_id)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol) continue;
      // CRITICAL: rollback belongs only to the command that partially opened.
      // Never close another SignalGate command on the same symbol/magic.
      if(StringFind(PositionGetString(POSITION_COMMENT), command_id) < 0) continue;
      trade.PositionClose(ticket);
   }
}

//+------------------------------------------------------------------+
//| Lot normalisation to broker min/step                            |
//+------------------------------------------------------------------+
bool NormalizeLot(const string symbol, double &lot)
{
   double minlot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxlot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0) step = 0.01;

   if(lot < minlot) lot = minlot;
   if(lot > maxlot) lot = maxlot;
   // Round to nearest step.
   lot = MathRound(lot / step) * step;
   return(lot >= minlot && lot <= maxlot);
}

//+------------------------------------------------------------------+
//| Account demo/live detection                                     |
//+------------------------------------------------------------------+
bool IsLiveAccount()
{
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   // ACCOUNT_TRADE_MODE_DEMO=0, _CONTEST=1, _REAL=2
   if(mode == ACCOUNT_TRADE_MODE_REAL)
      return(true);
   return(false);
}

//+------------------------------------------------------------------+
//| HTTP via WebRequest                                              |
//+------------------------------------------------------------------+
string HttpGet(const string url)
{
   string headers = "X-EA-API-Key: " + EAApiKey + "\r\n" +
                    "X-SG-License-Key: " + LicenseKey + "\r\n";
   char   post[];
   char   result[];
   string result_headers;
   int timeout = 5000;

   ResetLastError();
   int code = WebRequest("GET", url, headers, timeout, post, result, result_headers);
   if(code == -1)
   {
      Print("WEBREQUEST_FAILED GET ", url, " err=", GetLastError(),
            " (allow URL in Tools>Options>Expert Advisors>WebRequest)");
      return("");
   }
   return(CharArrayToString(result));
}

string HttpPost(const string url, const string body)
{
   string headers = "Content-Type: application/json\r\nX-EA-API-Key: " +
                    EAApiKey + "\r\nX-SG-License-Key: " + LicenseKey + "\r\n";
   char   post[];
   char   result[];
   string result_headers;
   int timeout = 5000;

   StringToCharArray(body, post, 0, StringLen(body), CP_UTF8);
   // Remove trailing null added by StringToCharArray.
   int len = ArraySize(post);
   if(len > 0 && post[len-1] == 0) ArrayResize(post, len-1);

   ResetLastError();
   int code = WebRequest("POST", url, headers, timeout, post, result, result_headers);
   if(code == -1)
   {
      Print("WEBREQUEST_FAILED POST ", url, " err=", GetLastError());
      return("");
   }
   return(CharArrayToString(result));
}

//+------------------------------------------------------------------+
//| Backend calls                                                   |
//+------------------------------------------------------------------+
string PollPendingCommand()
{
   string url = BackendURL + "/commands/pending?user_id=" + UserID;
   return(HttpGet(url));
}

void AckReceived(const string command_id)
{
   string url = BackendURL + "/commands/" + command_id + "/received";
   HttpPost(url, "{\"note\":\"EA received\"}");
}

void SendHeartbeat()
{
   HttpGet(BackendURL + "/ea/heartbeat");
}

// Reconcile all currently-open SignalGate broker positions. Positions are
// grouped by command id from the immutable SG:<command_id> broker comment.
int ReconcileOpenPositions()
{
   string command_ids[];
   int command_count = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      string comment = PositionGetString(POSITION_COMMENT);
      if(StringFind(comment, "SG:") != 0) continue;
      string cid = StringSubstr(comment, 3);
      if(cid == "") continue;

      bool seen = false;
      for(int j = 0; j < command_count; j++)
         if(command_ids[j] == cid) { seen = true; break; }
      if(!seen)
      {
         ArrayResize(command_ids, command_count + 1);
         command_ids[command_count] = cid;
         command_count++;
      }
   }

   for(int g = 0; g < command_count; g++)
   {
      string cid = command_ids[g];
      string tickets = "";
      string symbol = "";
      string direction = "";
      double total_volume = 0.0;
      double weighted_price = 0.0;
      double current_sl = 0.0;

      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
         if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
         string comment = PositionGetString(POSITION_COMMENT);
         if(comment != "SG:" + cid) continue;

         double volume = PositionGetDouble(POSITION_VOLUME);
         double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
         if(tickets != "") tickets += ",";
         tickets += "\"" + IntegerToString((long)ticket) + "\"";
         total_volume += volume;
         weighted_price += open_price * volume;
         if(symbol == "") symbol = PositionGetString(POSITION_SYMBOL);
         if(direction == "")
            direction = (
               PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY
               ? "BUY" : "SELL"
            );
         double sl = PositionGetDouble(POSITION_SL);
         if(current_sl == 0.0 && sl > 0.0) current_sl = sl;
      }

      if(total_volume <= 0.0 || tickets == "" || symbol == "" || direction == "")
         continue;

      double avg_price = weighted_price / total_volume;
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
      string body = "{";
      body += "\"broker_tickets\":[" + tickets + "],";
      body += "\"executed_symbol\":" + JsonEscapeString(symbol) + ",";
      body += "\"executed_direction\":" + JsonEscapeString(direction) + ",";
      body += "\"executed_price\":" + DoubleToString(avg_price, digits) + ",";
      body += "\"lot_size\":" + DoubleToString(total_volume, 8);
      if(current_sl > 0.0)
         body += ",\"stop_loss\":" + DoubleToString(current_sl, digits);
      body += "}";
      HttpPost(
         BackendURL + "/commands/" + cid + "/reconcile_open_position",
         body
      );
   }
   return(command_count);
}

void ReportExecutionSuccess(const string command_id, const string symbol,
                            const int direction, const double exec_price,
                            const double sl, const double tp1,
                            const double tp2, const double tp3)
{
   string child_json = "[";
   for(int i = 0; i < g_child_count; i++)
   {
      if(i > 0) child_json += ",";
      child_json += "\"" + IntegerToString((long)g_child_tickets[i]) + "\"";
   }
   child_json += "]";

   double total_lot = 0.0;
   if(SplitTicketDemoPartialMode) total_lot = TP1Lot + TP2Lot + TP3Lot;
   else total_lot = SingleTicketFixedLot;

   double spread = (double)SymbolInfoInteger(symbol, SYMBOL_SPREAD);

   string body = "{";
   body += "\"status\":\"SUCCESS\",";
   body += "\"broker_ticket\":\"" + IntegerToString((long)g_child_tickets[0]) + "\",";
   body += "\"child_tickets_json\":" + JsonEscapeString(child_json) + ",";
   body += "\"executed_symbol\":\"" + symbol + "\",";
   body += "\"executed_direction\":\"" + (direction==+1?"BUY":"SELL") + "\",";
   body += "\"executed_price\":" + DoubleToString(exec_price, _Digits) + ",";
   body += "\"lot_size\":" + DoubleToString(total_lot, 2) + ",";
   body += "\"initial_stop_loss\":" + DoubleToString(sl, _Digits) + ",";
   body += "\"tp1\":" + DoubleToString(tp1, _Digits) + ",";
   body += "\"tp2\":" + (tp2>0?DoubleToString(tp2,_Digits):"null") + ",";
   body += "\"tp3\":" + (tp3>0?DoubleToString(tp3,_Digits):"null") + ",";
   body += "\"spread_at_execution\":" + DoubleToString(spread, 0) + ",";
   body += "\"slippage\":0";
   body += "}";

   HttpPost(BackendURL + "/commands/" + command_id + "/execution", body);
}

void ReportManagementEvent(const string command_id, const string event_type,
                           const string stage, const string requested_action,
                           const string result, const double price,
                           const double lot_before, const double lot_after,
                           const double sl_before, const double sl_after)
{
   string body = "{";
   body += "\"event_type\":\"" + event_type + "\",";
   body += "\"stage\":\"" + stage + "\",";
   body += "\"requested_action\":\"" + requested_action + "\",";
   body += "\"result\":\"" + result + "\",";
   body += "\"price\":" + DoubleToString(price, _Digits) + ",";
   body += "\"lot_size_before\":" + DoubleToString(lot_before, 2) + ",";
   body += "\"lot_size_after\":" + DoubleToString(lot_after, 2) + ",";
   body += "\"stop_loss_before\":" + DoubleToString(sl_before, _Digits) + ",";
   body += "\"stop_loss_after\":" + DoubleToString(sl_after, _Digits);
   body += "}";
   HttpPost(BackendURL + "/commands/" + command_id + "/management_event", body);
}

void ReportError(const string command_id, const string error_code,
                 const string error_message)
{
   Print("ERROR [", command_id, "] ", error_code, ": ", error_message);
   if(command_id == "") return;
   string body = "{";
   body += "\"status\":\"FAILED\",";
   body += "\"error_code\":\"" + error_code + "\",";
   body += "\"error_message\":" + JsonEscapeString(error_message);
   body += "}";
   HttpPost(BackendURL + "/commands/" + command_id + "/execution", body);
}

void ReportDemoOnlyViolation()
{
   // No command context at init; just log. Backend learns via absent heartbeat.
   Print("DEMO_ONLY_VIOLATION reported (live account refused).");
}

//+------------------------------------------------------------------+
//| Local idempotency helpers                                        |
//+------------------------------------------------------------------+
bool AlreadyProcessed(const string command_id)
{
   for(int i = 0; i < ArraySize(g_processed_ids); i++)
      if(g_processed_ids[i] == command_id)
         return(true);
   return(false);
}

void MarkProcessed(const string command_id)
{
   int n = ArraySize(g_processed_ids);
   ArrayResize(g_processed_ids, n + 1);
   g_processed_ids[n] = command_id;
}

//+------------------------------------------------------------------+
//| Minimal JSON extraction for the KNOWN backend command shape.     |
//| NOTE: This is NOT a general JSON parser. It deterministically     |
//| extracts the specific keys the backend emits. Documented in the   |
//| README_MT5_SETUP.md as a known limitation.                        |
//+------------------------------------------------------------------+
string JsonGetString(const string json, const string key)
{
   string pat = "\"" + key + "\":\"";
   int p = StringFind(json, pat);
   if(p < 0) return("");
   p += StringLen(pat);
   int e = StringFind(json, "\"", p);
   if(e < 0) return("");
   return(StringSubstr(json, p, e - p));
}

double JsonGetDouble(const string json, const string key)
{
   string pat = "\"" + key + "\":";
   int p = StringFind(json, pat);
   if(p < 0) return(0.0);
   p += StringLen(pat);
   // Skip spaces.
   while(p < StringLen(json) && StringGetCharacter(json, p) == ' ') p++;
   // Read until delimiter.
   int start = p;
   while(p < StringLen(json))
   {
      ushort c = StringGetCharacter(json, p);
      if((c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+')
         p++;
      else
         break;
   }
   string num = StringSubstr(json, start, p - start);
   if(num == "" || num == "null") return(0.0);
   return(StringToDouble(num));
}

bool JsonGetBool(const string json, const string key)
{
   string pat = "\"" + key + "\":";
   int p = StringFind(json, pat);
   if(p < 0) return(false);
   p += StringLen(pat);
   return(StringFind(json, "true", p) == p);
}

// Extract a take-profit price for a given level from the take_profits array.
// The array objects look like: {"level":1,"price":2353.0,"close_percent":50,...}
double JsonGetTpPrice(const string json, const int level)
{
   string lvl = "\"level\":" + IntegerToString(level);
   int p = StringFind(json, lvl);
   if(p < 0) return(0.0);
   // Find "price": after this level marker.
   int pp = StringFind(json, "\"price\":", p);
   if(pp < 0) return(0.0);
   pp += StringLen("\"price\":");
   int start = pp;
   while(pp < StringLen(json))
   {
      ushort c = StringGetCharacter(json, pp);
      if((c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+')
         pp++;
      else
         break;
   }
   string num = StringSubstr(json, start, pp - start);
   if(num == "" || num == "null") return(0.0);
   return(StringToDouble(num));
}

// Wrap a string value as a JSON string literal (basic escaping of quotes).
string JsonEscapeString(const string s)
{
   string out = "\"";
   for(int i = 0; i < StringLen(s); i++)
   {
      ushort c = StringGetCharacter(s, i);
      if(c == '"' || c == '\\')
         out += "\\";
      out += ShortToString(c);
   }
   out += "\"";
   return(out);
}

//+------------------------------------------------------------------+
//| Setup hint for WebRequest                                        |
//+------------------------------------------------------------------+
void PrintWebRequestHint()
{
   Print("If polling fails: Tools > Options > Expert Advisors > ",
         "'Allow WebRequest for listed URL' and add: ", BackendURL);
}
//+------------------------------------------------------------------+
