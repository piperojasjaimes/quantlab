//+------------------------------------------------------------------+
//| Quant_XAUUSD_Alpha_Aggressive v1.0                                |
//| 15% riesgo, R:R 1:2, Compounding agresivo                        |
//| $500 → Max Returns                                                |
//+------------------------------------------------------------------+
#property copyright "QuantLab"
#property version   "1.0"
#property strict

#include <Trade\Trade.mqh>

//--- Inputs
input double InpBalance       = 500.0;
input double InpRiskPct       = 15.0;
input double InpMaxRiskPct    = 25.0;
input double InpTargetRatio   = 2.0;
input double InpSLmult        = 0.5;
input double InpTrailMult     = 0.3;
input double InpPartialPct    = 0.5;
input int    InpMaxPos        = 3;
input int    InpMaxDaily      = 40;
input int    InpConsecLimit   = 10;
input int    InpMaxDuration   = 240;
input int    InpMagic         = 888888;
input int    InpEMAfast       = 8;
input int    InpEMAslow       = 26;
input int    InpATRperiod     = 20;
input double InpMinEff        = 0.05;
input int    InpMinVol        = 5;
input int    InpMaxSpread     = 50;

CTrade trade;
int gDailyTrades = 0;
int gConsecLosses = 0;
double gDayStart = 0;
datetime gLastDay = 0;
double gCurrentRisk = 15.0;

int OnInit() {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(10);
   trade.SetTypeFilling(ORDER_FILLING_FOK);
   gDayStart = AccountInfoDouble(ACCOUNT_BALANCE);
   gCurrentRisk = InpRiskPct;
   return INIT_SUCCEEDED;
}

void OnTick() {
   datetime now = TimeCurrent();
   MqlDateTime dt; TimeToStruct(now, dt);

   if(now - gLastDay >= 86400) {
      gDayStart = AccountInfoDouble(ACCOUNT_BALANCE);
      gDailyTrades = 0; gConsecLosses = 0; gLastDay = now;
      UpdateCompound();
   }

   if(dt.day_of_week == 0 || dt.day_of_week == 6) return;
   if(dt.hour >= 22 || dt.hour < 1) { CloseAll(); return; }
   if(dt.day_of_week == 5 && dt.hour >= 20) { CloseAll(); return; }

   ManagePositions();

   if(CountPos() >= InpMaxPos) return;
   if(gDailyTrades >= InpMaxDaily) return;
   if(gConsecLosses >= InpConsecLimit) return;

   double spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpread) return;

   long vol = iVolume(_Symbol, PERIOD_M1, 0);
   if(vol < InpMinVol) return;

   int hour = dt.hour;
   if(!(hour >= 3 && hour < 12) && !(hour >= 13 && hour < 21)) return;

   int bias = GetBias();
   if(bias == 0) return;

   double eff = GetEfficiency();
   if(eff < InpMinEff) return;

   double atr = iATR(_Symbol, PERIOD_M15, InpATRperiod, 1);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double slPips = MathMax(10, atr * InpSLmult);
   double tpPips = slPips * InpTargetRatio;
   double lots = CalcLots(slPips);
   if(lots <= 0) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(bias == 1) {
      if(trade.Buy(lots, _Symbol, ask, ask - slPips * point * 10, ask + tpPips * point * 10, "AG_BUY"))
         gDailyTrades++;
   } else {
      if(trade.Sell(lots, _Symbol, bid, bid + slPips * point * 10, bid - tpPips * point * 10, "AG_SELL"))
         gDailyTrades++;
   }
}

void ManagePositions() {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      double openP = PositionGetDouble(POSITION_PRICE_OPEN);
      double curSL = PositionGetDouble(POSITION_SL);
      double curTP = PositionGetDouble(POSITION_TP);
      datetime openT = (datetime)PositionGetInteger(POSITION_TIME);
      double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

      int mins = (int)((TimeCurrent() - openT) / 60);
      if(mins >= InpMaxDuration) { trade.PositionClose(ticket); continue; }

      double atr = iATR(_Symbol, PERIOD_M15, InpATRperiod, 1);

      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) {
         double trail = SymbolInfoDouble(_Symbol, SYMBOL_BID) - atr * InpTrailMult;
         if(trail > curSL && trail > openP) trade.PositionModify(ticket, trail, curTP);
         double partialP = openP + (curTP - openP) * InpPartialPct;
         if(SymbolInfoDouble(_Symbol, SYMBOL_BID) >= partialP && curSL < openP)
            trade.PositionModify(ticket, openP, curTP);
      } else {
         double trail = SymbolInfoDouble(_Symbol, SYMBOL_ASK) + atr * InpTrailMult;
         if(trail < curSL && trail < openP) trade.PositionModify(ticket, trail, curTP);
         double partialP = openP - MathAbs(curTP - openP) * InpPartialPct;
         if(SymbolInfoDouble(_Symbol, SYMBOL_ASK) <= partialP && curSL > openP)
            trade.PositionModify(ticket, openP, curTP);
      }
   }
}

void CloseAll() {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
         if(PositionGetInteger(POSITION_MAGIC) == InpMagic)
            trade.PositionClose(ticket);
   }
}

int CountPos() {
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
         if(PositionGetInteger(POSITION_MAGIC) == InpMagic) c++;
   }
   return c;
}

int GetBias() {
   double emaF = iMA(_Symbol, PERIOD_M1, InpEMAfast, 0, MODE_EMA, PRICE_CLOSE, 0);
   double emaS = iMA(_Symbol, PERIOD_M1, InpEMAslow, 0, MODE_EMA, PRICE_CLOSE, 0);
   double emaM15 = iMA(_Symbol, PERIOD_M15, 50, 0, MODE_EMA, PRICE_CLOSE, 0);
   double priceM15 = iClose(_Symbol, PERIOD_M15, 0);
   bool bull1 = emaF > emaS;
   bool bull15 = priceM15 > emaM15;
   if(bull1 && bull15) return 1;
   if(!bull1 && !bull15) return -1;
   return 0;
}

double GetEfficiency() {
   int p = InpATRperiod;
   double net = MathAbs(iClose(_Symbol, PERIOD_M1, 0) - iClose(_Symbol, PERIOD_M1, p));
   double sv = 0;
   for(int i = 1; i <= p; i++) sv += MathAbs(iClose(_Symbol, PERIOD_M1, i-1) - iClose(_Symbol, PERIOD_M1, i));
   return sv > 0 ? net / sv : 0;
}

double CalcLots(double slPips) {
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk = balance * gCurrentRisk / 100.0;
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double tickVal = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(tickVal <= 0 || tickSize <= 0 || price <= 0) return 0;
   double lots = risk / (slPips * 10 * tickVal / tickSize);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots / step) * step;
   lots = MathMax(lots, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN));
   lots = MathMin(lots, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX));
   double margin = lots * price * SymbolInfoInteger(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE) / AccountInfoInteger(ACCOUNT_LEVERAGE);
   if(margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.5) lots = 0;
   return lots;
}

void UpdateCompound() {
   double profit = AccountInfoDouble(ACCOUNT_BALANCE) - InpBalance;
   double extra = MathFloor(profit / 100.0) * 2.0;
   gCurrentRisk = MathMin(InpMaxRiskPct, InpRiskPct + extra);
}

void OnTrade() {
   if(HistorySelect(0, TimeCurrent())) {
      int total = HistoryDealsTotal();
      if(total > 0) {
         ulong lastDeal = HistoryDealGetTicket(total - 1);
         if(HistoryDealGetInteger(lastDeal, DEAL_MAGIC) == InpMagic) {
            double profit = HistoryDealGetDouble(lastDeal, DEAL_PROFIT);
            if(profit < 0) gConsecLosses++;
            else gConsecLosses = 0;
         }
      }
   }
}
