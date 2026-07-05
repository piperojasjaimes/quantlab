//+------------------------------------------------------------------+
//| Quant_XAUUSD_Alpha_StandAlone v1.0                                |
//| Sin restricciones FTMO — Optimizado para $500                    |
//| Compounding agresivo + Gestión de riesgo adaptativa              |
//+------------------------------------------------------------------+
#property copyright "QuantLab"
#property version   "1.0"
#property strict

#include <Trade\Trade.mqh>

//--- Inputs
input double InpInitialBalance   = 500.0;      // Balance Inicial
input double InpRiskPct          = 1.5;         // Riesgo por trade (%)
input double InpMaxRiskPct       = 3.0;         // Riesgo máximo (%)
input int    InpMaxTrades        = 3;           // Máximo trades simultáneos
input int    InpMaxDailyTrades   = 20;          // Máximo trades diarios
input double InpTargetRatio      = 4.0;         // Ratio R:R
input double InpSLmult           = 1.2;         // SL ATR multiplier
input double InpTrailMult        = 0.8;         // Trailing ATR multiplier
input double InpPartialPct       = 0.6;         // Partial profit %
input int    InpMaxDuration      = 180;         // Duración máxima (min)
input int    InpMagic            = 999999;      // Magic number

//--- Sessiones
input int    InpLondonStart      = 3;
input int    InpLondonEnd        = 12;
input int    InpNYStart          = 13;
input int    InpNYEnd            = 21;

//--- Filtros
input int    InpEMAfast          = 13;
input int    InpEMAslow          = 40;
input int    InpATRperiod        = 20;
input double InpMinEfficiency    = 0.06;
input int    InpMinVolume        = 10;
input int    InpMaxSpread        = 40;
input double InpSLmultMin        = 0.8;
input double InpSLmultMax        = 2.5;
input int    InpConsecLossLimit  = 5;

//--- Compounding
input bool   InpEnableCompounding = true;
input double InpCompoundStep     = 100.0;       // Cada $100 de ganancia, subir riesgo

//--- Globals
CTrade trade;
int gTicketCounter = 1000;
int gDailyTrades = 0;
int gConsecLosses = 0;
double gDayStartBalance = 0;
datetime gLastDay = 0;
double gCurrentRisk = 1.5;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(10);
   trade.SetTypeFilling(ORDER_FILLING_FOK);
   gDayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   gCurrentRisk = InpRiskPct;
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime now = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(now, dt);

   // Daily reset
   if(now - gLastDay >= 86400)
   {
      gDayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      gDailyTrades = 0;
      gConsecLosses = 0;
      gLastDay = now;
      UpdateCompounding();
   }

   // Weekends
   if(dt.day_of_week == 0 || dt.day_of_week == 6)
      return;

   // Kill switch 22-01 UTC
   if(dt.hour >= 22 || dt.hour < 1)
   {
      CloseAll();
      return;
   }

   // Friday close
   if(dt.day_of_week == 5 && dt.hour >= 20)
   {
      CloseAll();
      return;
   }

   // Manage positions
   ManagePositions();

   // Max trades check
   if(CountPositions() >= InpMaxTrades)
      return;

   // Daily trades limit
   if(gDailyTrades >= InpMaxDailyTrades)
      return;

   // Consecutive loss block
   if(gConsecLosses >= InpConsecLossLimit)
      return;

   // Spread check
   double spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpread)
      return;

   // Volume check
   long vol = iVolume(_Symbol, PERIOD_M1, 0);
   if(vol < InpMinVolume)
      return;

   // Session check
   if(!IsSession(dt.hour))
      return;

   // Analyze
   int bias = GetBias();
   if(bias == 0) return;

   double eff = GetEfficiency();
   if(eff < InpMinEfficiency) return;

   // ATR for SL/TP
   double atr = iATR(_Symbol, PERIOD_M15, InpATRperiod, 1);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double slPips = MathMax(10, atr * InpSLmult);
   slPips = MathMax(InpSLmultMin * atr, MathMin(slPips, InpSLmultMax * atr));
   double tpPips = slPips * InpTargetRatio;

   // Dynamic risk based on balance
   double riskPct = gCurrentRisk / 100.0;
   double lots = CalcLots(slPips, riskPct);
   if(lots <= 0) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(bias == 1)
   {
      double sl = ask - slPips * point * 10;
      double tp = ask + tpPips * point * 10;
      if(trade.Buy(lots, _Symbol, ask, sl, tp, "Alpha_SA_BUY"))
         gDailyTrades++;
   }
   else
   {
      double sl = bid + slPips * point * 10;
      double tp = bid - tpPips * point * 10;
      if(trade.Sell(lots, _Symbol, bid, sl, tp, "Alpha_SA_SELL"))
         gDailyTrades++;
   }
}

//+------------------------------------------------------------------+
void ManagePositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;

      double openP = PositionGetDouble(POSITION_PRICE_OPEN);
      double curSL = PositionGetDouble(POSITION_SL);
      double curTP = PositionGetDouble(POSITION_TP);
      datetime openT = (datetime)PositionGetInteger(POSITION_TIME);
      double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

      int mins = (int)((TimeCurrent() - openT) / 60);
      if(mins >= InpMaxDuration) { trade.PositionClose(ticket); continue; }

      double atr = iATR(_Symbol, PERIOD_M15, InpATRperiod, 1);

      // Trailing
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
      {
         double trail = SymbolInfoDouble(_Symbol, SYMBOL_BID) - atr * InpTrailMult;
         if(trail > curSL && trail > openP)
            trade.PositionModify(ticket, trail, curTP);

         // Partial
         double partialP = openP + (curTP - openP) * InpPartialPct;
         if(SymbolInfoDouble(_Symbol, SYMBOL_BID) >= partialP && curSL < openP)
            trade.PositionModify(ticket, openP, curTP);
      }
      else
      {
         double trail = SymbolInfoDouble(_Symbol, SYMBOL_ASK) + atr * InpTrailMult;
         if(trail < curSL && trail < openP)
            trade.PositionModify(ticket, trail, curTP);

         double partialP = openP - MathAbs(curTP - openP) * InpPartialPct;
         if(SymbolInfoDouble(_Symbol, SYMBOL_ASK) <= partialP && curSL > openP)
            trade.PositionModify(ticket, openP, curTP);
      }
   }
}

//+------------------------------------------------------------------+
void CloseAll()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      trade.PositionClose(ticket);
   }
}

//+------------------------------------------------------------------+
int CountPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
         if(PositionGetInteger(POSITION_MAGIC) == InpMagic)
            count++;
   }
   return count;
}

//+------------------------------------------------------------------+
int GetBias()
{
   double emaF = iMA(_Symbol, PERIOD_M1, InpEMAfast, 0, MODE_EMA, PRICE_CLOSE, 0);
   double emaS = iMA(_Symbol, PERIOD_M1, InpEMAslow, 0, MODE_EMA, PRICE_CLOSE, 0);
   double price = iClose(_Symbol, PERIOD_M1, 0);

   // Multi-TF: confirm with M15
   double emaM15 = iMA(_Symbol, PERIOD_M15, 50, 0, MODE_EMA, PRICE_CLOSE, 0);
   double priceM15 = iClose(_Symbol, PERIOD_M15, 0);

   bool bullM1 = emaF > emaS;
   bool bullM15 = priceM15 > emaM15;

   if(bullM1 && bullM15) return 1;
   if(!bullM1 && !bullM15) return -1;
   return 0;
}

//+------------------------------------------------------------------+
double GetEfficiency()
{
   int period = InpATRperiod;
   double net = MathAbs(iClose(_Symbol, PERIOD_M1, 0) - iClose(_Symbol, PERIOD_M1, period));
   double sumV = 0;
   for(int i = 1; i <= period; i++)
      sumV += MathAbs(iClose(_Symbol, PERIOD_M1, i-1) - iClose(_Symbol, PERIOD_M1, i));
   return sumV > 0 ? net / sumV : 0;
}

//+------------------------------------------------------------------+
bool IsSession(int hour)
{
   if(hour >= InpLondonStart && hour < InpLondonEnd) return true;
   if(hour >= InpNYStart && hour < InpNYEnd) return true;
   return false;
}

//+------------------------------------------------------------------+
double CalcLots(double slPips, double riskPct)
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk = balance * riskPct;
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

   // Margin check
   double margin = lots * price * SymbolInfoInteger(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE) / AccountInfoInteger(ACCOUNT_LEVERAGE);
   if(margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.5)
      lots = 0;

   return lots;
}

//+------------------------------------------------------------------+
void UpdateCompounding()
{
   if(!InpEnableCompounding) return;
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double profit = balance - InpInitialBalance;
   double extraRisk = MathFloor(profit / InpCompoundStep) * 0.2;
   gCurrentRisk = MathMin(InpMaxRiskPct, InpRiskPct + extraRisk);
}

//+------------------------------------------------------------------+
void OnTrade()
{
   if(HistorySelect(0, TimeCurrent()))
   {
      int total = HistoryDealsTotal();
      if(total > 0)
      {
         ulong lastDeal = HistoryDealGetTicket(total - 1);
         if(HistoryDealGetInteger(lastDeal, DEAL_MAGIC) == InpMagic)
         {
            double profit = HistoryDealGetDouble(lastDeal, DEAL_PROFIT);
            if(profit < 0)
               gConsecLosses++;
            else
               gConsecLosses = 0;
         }
      }
   }
}
