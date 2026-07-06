//+------------------------------------------------------------------+
//| Quant_XAUUSD_Alpha_Final v2.0                                      |
//| Con filtro de mercado neutral + Compounding agresivo              |
//| $1,000 → Max Returns                                              |
//+------------------------------------------------------------------+
#property copyright "QuantLab"
#property version   "2.0"
#property strict

#include <Trade\Trade.mqh>

//--- Risk Management
input double InpBalance         = 1000.0;    // Balance Inicial
input double InpRiskPct         = 10.0;      // Riesgo por trade (%)
input double InpMaxRiskPct      = 20.0;      // Riesgo máximo compounding (%)
input double InpTargetRatio     = 2.0;       // Ratio R:R
input int    InpMaxPositions    = 3;         // Máximo trades simultáneos
input int    InpMaxDailyTrades  = 50;        // Máximo trades diarios
input int    InpMaxDuration     = 240;       // Duración máxima (min)
input int    InpConsecLimit     = 10;        // Pérdidas consecutivas → stop
input int    InpMagic           = 777777;    // Magic number

//--- Exit Strategy
input double InpSLmult          = 0.5;       // SL ATR multiplier
input double InpSLmultMin       = 0.3;       // SL mínimo (ATR x)
input double InpSLmultMax       = 1.5;       // SL máximo (ATR x)
input double InpTrailMult       = 0.3;       // Trailing ATR multiplier
input double InpPartialPct      = 0.5;       // Partial profit % del TP

//--- Indicadores
input int    InpEMAfast         = 8;         // EMA rápida M1
input int    InpEMAslow         = 26;        // EMA lenta M1
input int    InpATRperiod       = 20;        // Período ATR
input int    InpRegimePeriod    = 20;        // Período régimen

//--- Filtros de Entrada
input double InpMinEfficiency   = 0.05;      // Eficiencia mínima
input int    InpMinVolume       = 5;         // Volumen mínimo
input int    InpMaxSpread       = 50;        // Spread máximo

//--- Filtro de Mercado Neutral (NUEVO)
input bool   InpEnableNeutralFilter = true;  // Activar filtro neutral
input double InpNeutralThreshold    = 0.12;  // Umbral eficiencia neutral
input int    InpNeutralBars         = 8;     // Barras para detectar neutral
input double InpADXthreshold        = 20.0;  // ADX mínimo para tendencia
input int    InpADXperiod           = 14;    // Período ADX

//--- Sesiones
input int    InpLondonStart     = 3;         // London start UTC
input int    InpLondonEnd       = 12;        // London end UTC
input int    InpNYStart         = 13;        // NY start UTC
input int    InpNYEnd           = 21;        // NY end UTC

//--- Compounding
input bool   InpEnableCompound  = true;      // Compounding activo
input double InpCompoundStep    = 100.0;     // Cada $100 ganancia → + riesgo

//--- Comisiones/Swaps
input double InpCommission      = 3.5;       // Comisión por lote
input double InpSwapLong        = -2.5;      // Swap long (puntos/día)
input double InpSwapShort       = -0.5;      // Swap short (puntos/día)

//--- Globals
CTrade trade;
int gDailyTrades = 0;
int gConsecLosses = 0;
double gDayStartBalance = 0;
datetime gLastDay = 0;
double gCurrentRisk = 0;
bool gIsNeutral = false;

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
      UpdateCompound();
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

   // Manage open positions
   ManagePositions();

   // ── Pre-entry filters ────────────────────────────────────────────
   if(CountPositions() >= InpMaxPositions)
      return;
   if(gDailyTrades >= InpMaxDailyTrades)
      return;
   if(gConsecLosses >= InpConsecLimit)
      return;

   double spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpread)
      return;

   long vol = iVolume(_Symbol, PERIOD_M1, 0);
   if(vol < InpMinVolume)
      return;

   // Session check
   if(!IsSession(dt.hour))
      return;

   // ── Filtro de Mercado Neutral (NUEVO) ────────────────────────────
   if(InpEnableNeutralFilter)
   {
      gIsNeutral = IsNeutralMarket();
      if(gIsNeutral)
         return;  // No operar en mercado neutral
   }

   // ── Eficiencia (filtro adicional) ────────────────────────────────
   double eff = GetEfficiency();
   if(eff < InpMinEfficiency)
      return;

   // ── Bias direction ───────────────────────────────────────────────
   int bias = GetBias();
   if(bias == 0)
      return;

   // ── Calculate SL/TP ──────────────────────────────────────────────
   double atr = iATR(_Symbol, PERIOD_M15, InpATRperiod, 1);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double slPips = MathMax(10, atr * InpSLmult);
   slPips = MathMax(InpSLmultMin * atr, MathMin(slPips, InpSLmultMax * atr));
   double tpPips = slPips * InpTargetRatio;

   // ── Calculate lots ───────────────────────────────────────────────
   double lots = CalcLots(slPips);
   if(lots <= 0)
      return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // ── Execute ──────────────────────────────────────────────────────
   if(bias == 1)
   {
      double sl = ask - slPips * point * 10;
      double tp = ask + tpPips * point * 10;
      if(trade.Buy(lots, _Symbol, ask, sl, tp, "FA BUY"))
         gDailyTrades++;
   }
   else if(bias == -1)
   {
      double sl = bid + slPips * point * 10;
      double tp = bid - tpPips * point * 10;
      if(trade.Sell(lots, _Symbol, bid, sl, tp, "FA SELL"))
         gDailyTrades++;
   }
}

//+------------------------------------------------------------------+
//| Filtro de Mercado Neutral                                        |
//| Detecta rangos laterales donde el bot no debería operar         |
//+------------------------------------------------------------------+
bool IsNeutralMarket()
{
   // 1. Efficiency ratio bajo → mercado sin dirección
   double eff = GetEfficiency();
   if(eff < InpNeutralThreshold)
      return true;

   // 2. ADX bajo → sin tendencia
   double adx = GetADX();
   if(adx < InpADXthreshold)
      return true;

   // 3. Precio cerca de EMA → sin desviación clara
   double emaF = iMA(_Symbol, PERIOD_M1, InpEMAfast, 0, MODE_EMA, PRICE_CLOSE, 0);
   double emaS = iMA(_Symbol, PERIOD_M1, InpEMAslow, 0, MODE_EMA, PRICE_CLOSE, 0);
   double price = iClose(_Symbol, PERIOD_M1, 0);
   double emaSpread = MathAbs(emaF - emaS) / price * 10000;  // En pips

   if(emaSpread < 5)  // EMAs muy cerca = rango
      return true;

   // 4. Velas sin dirección en últimas N barras
   int bullishBars = 0;
   int bearishBars = 0;
   for(int i = 1; i <= InpNeutralBars; i++)
   {
      double close = iClose(_Symbol, PERIOD_M1, i);
      double open = iOpen(_Symbol, PERIOD_M1, i);
      if(close > open) bullishBars++;
      else if(close < open) bearishBars++;
   }

   double directionalBias = (double)(bullishBars - bearishBars) / InpNeutralBars;
   if(MathAbs(directionalBias) < 0.25)  // Menos de 25% de sesgo direccional
      return true;

   return false;
}

//+------------------------------------------------------------------+
//| Obtener ADX (Average Directional Index)                          |
//+------------------------------------------------------------------+
double GetADX()
{
   int adxHandle = iADX(_Symbol, PERIOD_M1, InpADXperiod);
   if(adxHandle == INVALID_HANDLE)
      return 0;

   double adxBuffer[];
   ArraySetAsSeries(adxBuffer, true);
   if(CopyBuffer(adxHandle, 0, 0, 1, adxBuffer) < 1)
      return 0;

   IndicatorRelease(adxHandle);
   return adxBuffer[0];
}

//+------------------------------------------------------------------+
void ManagePositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;

      double openP = PositionGetDouble(POSITION_PRICE_OPEN);
      double curSL = PositionGetDouble(POSITION_SL);
      double curTP = PositionGetDouble(POSITION_TP);
      datetime openT = (datetime)PositionGetInteger(POSITION_TIME);
      double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

      // Duration check
      int mins = (int)((TimeCurrent() - openT) / 60);
      if(mins >= InpMaxDuration)
      {
         trade.PositionClose(ticket);
         continue;
      }

      double atr = iATR(_Symbol, PERIOD_M15, InpATRperiod, 1);

      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
      {
         // Trailing stop
         double trail = SymbolInfoDouble(_Symbol, SYMBOL_BID) - atr * InpTrailMult;
         if(trail > curSL && trail > openP)
            trade.PositionModify(ticket, trail, curTP);

         // Partial profit
         double partialP = openP + (curTP - openP) * InpPartialPct;
         if(SymbolInfoDouble(_Symbol, SYMBOL_BID) >= partialP && curSL < openP)
            trade.PositionModify(ticket, openP, curTP);
      }
      else
      {
         // Trailing stop
         double trail = SymbolInfoDouble(_Symbol, SYMBOL_ASK) + atr * InpTrailMult;
         if(trail < curSL && trail < openP)
            trade.PositionModify(ticket, trail, curTP);

         // Partial profit
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
      if(PositionSelectByTicket(ticket))
         if(PositionGetInteger(POSITION_MAGIC) == InpMagic)
            trade.PositionClose(ticket);
   }
}

//+------------------------------------------------------------------+
int CountPositions()
{
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
         if(PositionGetInteger(POSITION_MAGIC) == InpMagic)
            c++;
   }
   return c;
}

//+------------------------------------------------------------------+
int GetBias()
{
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

//+------------------------------------------------------------------+
double GetEfficiency()
{
   int p = InpRegimePeriod;
   double net = MathAbs(iClose(_Symbol, PERIOD_M1, 0) - iClose(_Symbol, PERIOD_M1, p));
   double sv = 0;
   for(int i = 1; i <= p; i++)
      sv += MathAbs(iClose(_Symbol, PERIOD_M1, i - 1) - iClose(_Symbol, PERIOD_M1, i));
   return sv > 0 ? net / sv : 0;
}

//+------------------------------------------------------------------+
double CalcLots(double slPips)
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk = balance * gCurrentRisk / 100.0;
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double tickVal = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(tickVal <= 0 || tickSize <= 0 || price <= 0)
      return 0;
   double lots = risk / (slPips * 10 * tickVal / tickSize);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots / step) * step;
   lots = MathMax(lots, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN));
   lots = MathMin(lots, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX));
   double margin = lots * price * SymbolInfoInteger(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE) / AccountInfoInteger(ACCOUNT_LEVERAGE);
   if(margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.5)
      lots = 0;
   return lots;
}

//+------------------------------------------------------------------+
bool IsSession(int hour)
{
   if(hour >= InpLondonStart && hour < InpLondonEnd)
      return true;
   if(hour >= InpNYStart && hour < InpNYEnd)
      return true;
   return false;
}

//+------------------------------------------------------------------+
void UpdateCompound()
{
   if(!InpEnableCompound)
      return;
   double profit = AccountInfoDouble(ACCOUNT_BALANCE) - InpBalance;
   double extra = MathFloor(profit / InpCompoundStep) * 2.0;
   gCurrentRisk = MathMin(InpMaxRiskPct, InpRiskPct + extra);
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
