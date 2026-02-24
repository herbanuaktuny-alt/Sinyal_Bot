import yfinance as yf
import pandas as pd
import numpy as np
import requests

# =======================
# KONFIGURASI TETAP
# =======================
TELEGRAM_TOKEN = "8140044459:AAHTLV64V7wwOVI1OEYhc2Oh60_ozhO09t0"
TELEGRAM_CHAT_ID = "7753119384"
CSV_URL = "https://docs.google.com/spreadsheets/d/1iZ2Iny1GsaZpmQHkEuXXVg8qzq4WSa-LrcW3SeKzvAw/export?format=csv&gid=0"

# =======================
# UTIL
# =======================
def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=data, timeout=15)
        if r.status_code != 200:
            print(f"[ERROR] Telegram error: {r.text}")
    except Exception as e:
        print(f"[ERROR] Telegram exception: {e}")

# =======================
# INDIKATOR
# =======================
def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Hitung semua indikator (BUY SPIKE + BSJP)"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    for c in ['Open','High','Low','Close','Volume']:
        if c not in df.columns:
            raise ValueError(f"Missing column {c}")
        if isinstance(df[c], pd.DataFrame):
            df[c] = df[c].iloc[:,0]
        df[c] = pd.to_numeric(df[c], errors='coerce')

    df = df.dropna(subset=['Open','High','Low','Close','Volume'])

    close = df['Close']
    high  = df['High']
    low   = df['Low']
    vol   = df['Volume']

    # === Param BUY SPIKE ===
    volLenSpike = 50
    volMult     = 5
    maxGain     = 5.0  # persen
    sideBars    = 50
    lenPerc     = 50
    maxRange    = 0.25
    multiplier  = 10

    def getFraksiHarga(harga):
        if harga < 200: return 1
        if harga < 500: return 2
        if harga < 2000: return 5
        if harga < 5000: return 10
        return 25

    # Volume spike
    df['volMAspike'] = vol.rolling(volLenSpike, min_periods=volLenSpike).mean()
    df['volSpike']   = vol > (df['volMAspike'] * volMult)
    df['priceGain']  = (close - close.shift(1)) / close.shift(1) * 100
    df['priceOK']    = (df['priceGain'] >= 0) & (df['priceGain'] <= maxGain)
    df['volOK']      = vol > vol.shift(1).rolling(5, min_periods=5).max()

    # Sideways
    df['tickSize']  = close.apply(getFraksiHarga)
    df['rangeSide'] = high.rolling(sideBars, min_periods=sideBars).max() - low.rolling(sideBars, min_periods=sideBars).min()
    df['sideTick']  = df['rangeSide'] <= df['tickSize'] * multiplier
    hhPerc = high.rolling(lenPerc, min_periods=lenPerc).max()
    llPerc = low.rolling(lenPerc, min_periods=lenPerc).min()
    df['rangePerc'] = (hhPerc - llPerc) / llPerc
    df['sidePerc']  = df['rangePerc'] < maxRange
    df['isSideways'] = df['sideTick'] | df['sidePerc']

    # Final BUY SPIKE
    df['buySpike'] = df['volSpike'] & df['priceOK'] & df['volOK'] & df['isSideways']

    # === Param BSJP ===
    df['upBefore'] = close.shift(4) > close.shift(5)
    df['down4'] = (close < close.shift(1)) & \
                  (close.shift(1) < close.shift(2)) & \
                  (close.shift(2) < close.shift(3)) & \
                  (close.shift(3) < close.shift(4))
    # filter tambahan: candle tidak close di titik low
    df['notLowest'] = close > low

    # === Tambahan informasi Mini Uptrend (TIDAK memfilter sinyal) ===
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA50'] = df['Close'].rolling(50).mean()
    df['miniUp'] = df['MA20'] > df['MA50']  # hanya info

    # === Tambahan informasi Volume Rendah 4 Hari (TIDAK memfilter sinyal) ===
    df['volMA20'] = vol.rolling(20).mean()
    df['volRendah4'] = (vol < df['volMA20']).rolling(4).sum() == 4  # hanya info

    # === Tambahan ATR dan ATR% ===
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1) 
    df['ATR'] = tr.rolling(14).mean()
    df['ATR%'] = (df['ATR'] / close) * 100

    df['buyCustom'] = df['upBefore'] & df['down4'] & df['notLowest']

    return df

# =======================
# CEK SINYAL
# =======================
def check_signals(df: pd.DataFrame, recent_bars: int = 1):
    hasil = []
    if len(df) < 60:  # untuk spike butuh ≥ 60 bar
        return hasil

    total = len(df)
    last_pos = total - 1
    start_pos = max(0, last_pos - (recent_bars - 1))

    for pos in range(start_pos, last_pos + 1):
        bar = df.iloc[pos]
        date_str = df.index[pos].date() if hasattr(df.index[pos], 'date') else pos
        offset = last_pos - pos
        hari_str = "H-0 (hari ini)" if offset == 0 else f"H-{offset}"

        if bar.get('buySpike', False):
            harga = bar.get('Close', np.nan)
            if not np.isnan(harga):
                hasil.append(f"{date_str} - SPIKE 🚀 \nHarga : {harga:.0f} | [{hari_str}]")
            else:
                hasil.append(f"{date_str} - SPIKE [{hari_str}]")

        if bar.get('buyCustom', False):
            harga = bar.get('Close', np.nan)
            atr_pct = bar.get('ATR%', np.nan)
            tp = np.nan
            if not np.isnan(harga) and not np.isnan(atr_pct):
                tp = harga * (1 + (atr_pct * 0.5) / 100)

            info = []
            if not np.isnan(harga) and not np.isnan(tp) and not np.isnan(atr_pct):
                info.append(f"Harga : {harga:.0f} | TP = {tp:.0f} ({atr_pct * 0.5:.1f}%)")

            tambahan = []
            if bar.get('miniUp', False):
                tambahan.append("🔹Mini Uptrend")
            if bar.get('volRendah4', False):
                tambahan.append("🔹Volume OK")

            hasil.append(f"{date_str} - BSJP \n" +
                         (info[0] if info else "") + "\n" +
                         (' '.join(tambahan) if tambahan else ""))

    return hasil

# =======================
# GET DATA
# =======================
def get_tickers_from_sheet() -> list:
    try:
        df = pd.read_csv(CSV_URL)
        if 'ticker' in df.columns:
            tks = df['ticker'].dropna().astype(str).tolist()
        else:
            tks = df.iloc[:,0].dropna().astype(str).tolist()
        return tks
    except Exception as e:
        print(f"[ERROR] Gagal baca CSV: {e}")
        return []

def fetch_data_yf(ticker: str) -> pd.DataFrame:
    data = yf.download(
        ticker, period="12mo", interval="1d",
        auto_adjust=False, progress=False, threads=True
    )
    return data

# =======================
# MAIN
# =======================
def main():
    print("Mengambil daftar ticker dari Google Sheets...")
    tickers = get_tickers_from_sheet()
    print("Daftar ticker:", tickers)

    any_signal = False

    for tk in tickers:
        print(f"\nMemproses ticker {tk} ...")
        try:
            df = fetch_data_yf(tk)
            if df is None or df.empty:
                print(f"[WARN] {tk} - data kosong")
                continue

            df = calc_indicators(df)

            signals = check_signals(df, recent_bars=1)
            if signals:
                any_signal = True
                for s in signals:
                    msg = f"<b>{tk}</b> - {s}"
                    print(msg)
                    send_telegram(msg)
            else:
                print(f"{tk}: tidak ada sinyal")

        except Exception as e:
            print(f"[ERROR] Saat proses {tk}: {e}")

    if not any_signal:
        print("Tidak ada sinyal buy")
        send_telegram("Tidak ada sinyal buy")

if __name__ == "__main__":
    main()
